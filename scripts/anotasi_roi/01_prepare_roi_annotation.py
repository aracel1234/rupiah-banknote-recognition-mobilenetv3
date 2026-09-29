#!/usr/bin/env python3
"""Prepare DRAFT banknote-boundary annotations from POCO/Redmi calibration ZIPs.

This script never edits the raw ZIPs. It extracts copies into the output work folder,
reads manifest.csv, keeps only ROI samples, and creates automatic boundary proposals
for the seven nominal classes. All 210 nominal proposals MUST be reviewed manually
with 02_review_roi_annotation.py before final geometry metrics are allowed.
"""
from __future__ import annotations

import argparse, json, math, shutil, zipfile
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

MONEY = ["1000","2000","5000","10000","20000","50000","100000"]


def order_quad(pts: np.ndarray) -> np.ndarray:
    pts=np.asarray(pts,dtype=np.float32).reshape(4,2)
    c=pts.mean(axis=0)
    ang=np.arctan2(pts[:,1]-c[1],pts[:,0]-c[0])
    pts=pts[np.argsort(ang)]
    # rotate to top-left-ish first (minimum x+y)
    i=int(np.argmin(pts.sum(axis=1)))
    pts=np.roll(pts,-i,axis=0)
    # ensure clockwise order in image coordinates
    area=cv2.contourArea(pts.reshape(-1,1,2), oriented=True)
    if area < 0:
        pts=np.array([pts[0],pts[3],pts[2],pts[1]],dtype=np.float32)
    return pts


def roi_rect(width:int,height:int,fraction:float,aspect:float=1.3420920964096548,cap:float=0.90):
    w=min(width*fraction,height*cap*aspect)
    h=w/aspect
    return ((width-w)/2,(height-h)/2,(width+w)/2,(height+h)/2)


def detect_banknote(img_bgr: np.ndarray, distance_cm: int):
    """Return (quad, score, method, source_truncated_candidate).

    Conservative automatic proposal based primarily on chroma/saturation contrast
    against the neutral calibration background. It is only a draft: every sample
    still requires human review.
    """
    h,w=img_bgr.shape[:2]
    area_img=float(h*w)
    lab=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2LAB)
    hsv=cv2.cvtColor(img_bgr,cv2.COLOR_BGR2HSV)
    _,a,b=cv2.split(lab)
    chroma=np.sqrt((a.astype(np.float32)-128)**2+(b.astype(np.float32)-128)**2)
    sat=hsv[:,:,1].astype(np.float32)

    # Neutral white/gray background tends to have low chroma and saturation.
    fg=((chroma>8.0)|(sat>15.0)).astype(np.uint8)*255
    k=max(5,int(round(min(h,w)*0.02))|1)
    fg=cv2.morphologyEx(fg,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(k,k)),iterations=2)
    fg=cv2.morphologyEx(fg,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)),iterations=1)

    contours,_=cv2.findContours(fg,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    cx0,cy0=w/2,h/2
    candidates=[]
    for c in contours:
        ca=cv2.contourArea(c)
        if ca < 0.008*area_img:
            continue
        rect=cv2.minAreaRect(c)
        (cx,cy),(rw,rh),_=rect
        if rw<8 or rh<8:
            continue
        long=max(rw,rh); short=min(rw,rh)
        ar=long/max(short,1e-6)
        if ar<1.05 or ar>5.0:
            continue
        box=order_quad(cv2.boxPoints(rect))
        box_area=abs(cv2.contourArea(box.reshape(-1,1,2)))
        if box_area<=0:
            continue
        fill=min(1.0,ca/box_area)
        center_dist=math.hypot((cx-cx0)/(w/2),(cy-cy0)/(h/2))
        center_score=max(0.0,1.0-center_dist/1.0)
        ar_score=max(0.0,1.0-abs(ar-2.0)/2.0)
        area_ratio=box_area/area_img
        # Known capture distance is part of the experiment design and is used only
        # to reject obviously implausible background components from the draft detector.
        if distance_cm <= 10:
            target_area, lo_area, hi_area = 0.72, 0.20, 1.05
        elif distance_cm <= 20:
            target_area, lo_area, hi_area = 0.28, 0.05, 0.65
        else:
            target_area, lo_area, hi_area = 0.085, 0.012, 0.30
        if not (lo_area <= area_ratio <= hi_area):
            continue
        area_score=max(0.0,1.0-abs(area_ratio-target_area)/max(target_area,0.05))
        score=0.36*fill+0.27*center_score+0.20*ar_score+0.17*area_score
        candidates.append((score,box,ca,area_ratio,ar))

    if not candidates:
        return None,0.0,"none",False
    candidates.sort(key=lambda x:x[0],reverse=True)
    score,box,_,area_ratio,ar=candidates[0]
    # Only a review hint: if the proposed banknote boundary itself reaches the source border.
    mx=max(2,int(round(w*0.015))); my=max(2,int(round(h*0.015)))
    trunc_hint=bool(np.any((box[:,0]<=mx)|(box[:,0]>=w-1-mx)|(box[:,1]<=my)|(box[:,1]>=h-1-my)))
    return box,float(max(0,min(1,score))),"chroma_saturation_minAreaRect",trunc_hint

def draw_overlay(img,quad,score,trunc_hint):
    out=img.copy()
    if quad is not None:
        p=np.round(quad).astype(int).reshape(-1,1,2)
        cv2.polylines(out,[p],True,(0,255,255),2,cv2.LINE_AA)
        for i,(x,y) in enumerate(np.round(quad).astype(int),1):
            cv2.circle(out,(x,y),4,(0,0,255),-1)
            cv2.putText(out,str(i),(x+5,y-5),cv2.FONT_HERSHEY_SIMPLEX,0.45,(0,0,255),1,cv2.LINE_AA)
    label=f"DRAFT score={score:.3f} trunc_hint={trunc_hint}"
    cv2.rectangle(out,(0,0),(out.shape[1],24),(0,0,0),-1)
    cv2.putText(out,label,(6,17),cv2.FONT_HERSHEY_SIMPLEX,0.48,(255,255,255),1,cv2.LINE_AA)
    return out


def unzip_clean(z:Path,dst:Path):
    if dst.exists(): shutil.rmtree(dst)
    dst.mkdir(parents=True)
    with zipfile.ZipFile(z) as f: f.extractall(dst)
    mans=list(dst.rglob('manifest.csv'))
    if len(mans)!=1: raise RuntimeError(f"Expected one manifest.csv in {z}, got {len(mans)}")
    return mans[0].parent


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--poco-zip',required=True,type=Path)
    ap.add_argument('--redmi-zip',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args()
    out=args.out; out.mkdir(parents=True,exist_ok=True)
    work=out/'_extracted'; work.mkdir(exist_ok=True)
    roots={
      'poco':unzip_clean(args.poco_zip,work/'poco'),
      'redmi':unzip_clean(args.redmi_zip,work/'redmi')
    }
    overlays=out/'draft_overlays'; overlays.mkdir(exist_ok=True)
    review_images=out/'review_images'; review_images.mkdir(exist_ok=True)
    rows=[]
    for dev,root in roots.items():
        df=pd.read_csv(root/'manifest.csv',dtype={'class_label':str})
        sdf=df[(df['experiment_group']=='roi') & (df['class_label'].isin(MONEY))].copy()
        for _,r in sdf.iterrows():
            img_path=root/str(r['relative_rgb_path'])
            img=cv2.imread(str(img_path),cv2.IMREAD_COLOR)
            if img is None: raise RuntimeError(f"Cannot read {img_path}")
            quad,score,method,trunc_hint=detect_banknote(img,int(float(r['distance_cm'])))
            q=[np.nan]*8 if quad is None else quad.reshape(-1).tolist()
            review_dir=review_images/dev
            review_dir.mkdir(parents=True,exist_ok=True)
            review_path=review_dir/f"{r['sample_id']}.png"
            if not review_path.exists():
                shutil.copy2(img_path,review_path)
            rows.append({
                'device':dev,'sample_id':r['sample_id'],'class_label':r['class_label'],
                'distance_cm':int(float(r['distance_cm'])),'repeat_index':int(r['repeat_index']),
                'image_width':img.shape[1],'image_height':img.shape[0],
                'relative_rgb_path':str(r['relative_rgb_path']),
                'review_image_path':str(review_path.relative_to(out)),
                'auto_method':method,'auto_score':score,'auto_truncated_hint':trunc_hint,
                'p1_x':q[0],'p1_y':q[1],'p2_x':q[2],'p2_y':q[3],
                'p3_x':q[4],'p3_y':q[5],'p4_x':q[6],'p4_y':q[7],
                'review_status':'PENDING','review_note':''
            })
            od=overlays/dev/str(r['distance_cm']).replace('.0','')
            od.mkdir(parents=True,exist_ok=True)
            ov=draw_overlay(img,quad,score,trunc_hint)
            cv2.imwrite(str(od/f"{r['sample_id']}.png"),ov)
    ann=pd.DataFrame(rows).sort_values(['device','distance_cm','class_label','repeat_index','sample_id'])
    ann.to_csv(out/'roi_object_annotations_draft.csv',index=False)
    summary={
        'nominal_samples':int(len(ann)),
        'per_device':ann.groupby('device').size().to_dict(),
        'per_distance':{str(k):int(v) for k,v in ann.groupby('distance_cm').size().to_dict().items()},
        'auto_score':{'min':float(ann.auto_score.min()),'median':float(ann.auto_score.median()),'max':float(ann.auto_score.max())},
        'truncated_hints':int(ann.auto_truncated_hint.sum()),
        'important':'DRAFT ONLY. Every one of the 210 nominal samples requires human review.'
    }
    (out/'prepare_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
