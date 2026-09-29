#!/usr/bin/env python3
"""Finalize ROI geometry metrics after all 210 nominal annotations are reviewed.

This script refuses to run if any nominal sample is still PENDING.
It reproduces the Android RoiGeometry.kt formula exactly:
    w = min(width * fraction, height * 0.90 * aspect)
    h = w / aspect
    centered rectangle
"""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
import cv2,numpy as np,pandas as pd


def sha256(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def roi_rect(width,height,fraction,aspect,cap):
    w=min(width*fraction,height*cap*aspect); h=w/aspect
    return np.array([[ (width-w)/2,(height-h)/2 ],[(width+w)/2,(height-h)/2],[(width+w)/2,(height+h)/2],[(width-w)/2,(height+h)/2]],dtype=np.float32)

def get_quad(row):
    return np.array([[row[f'p{i}_x'],row[f'p{i}_y']] for i in range(1,5)],dtype=np.float32)

def inside_all(poly,rect,eps=1e-5):
    x0,y0=rect[:,0].min(),rect[:,1].min(); x1,y1=rect[:,0].max(),rect[:,1].max()
    return bool(np.all((poly[:,0]>=x0-eps)&(poly[:,0]<=x1+eps)&(poly[:,1]>=y0-eps)&(poly[:,1]<=y1+eps)))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--work-dir',required=True,type=Path); args=ap.parse_args(); wd=args.work_dir
    cfg=json.loads((wd/'config.json').read_text()) if (wd/'config.json').exists() else json.loads((Path(__file__).with_name('config.json')).read_text())
    ann=wd/'roi_object_annotations_reviewed.csv'
    if not ann.exists(): raise SystemExit('Missing roi_object_annotations_reviewed.csv. Run human review first.')
    df=pd.read_csv(ann,dtype={'class_label':str})
    bad=df[~df.review_status.isin(['ACCEPTED_AUTO','ACCEPTED_MANUAL','SOURCE_TRUNCATED'])]
    if len(bad): raise SystemExit(f'Refusing finalization: {len(bad)} samples are not reviewed/final.')
    aspect=float(cfg['roi_aspect_ratio']); cap=float(cfg['roi_height_cap_fraction']); occ_thr=float(cfg['banknote_occupancy_threshold'])
    rows=[]
    for _,r in df.iterrows():
        truncated=r.review_status=='SOURCE_TRUNCATED'
        poly=None if truncated else get_quad(r)
        poly_area=np.nan if truncated else abs(cv2.contourArea(poly.reshape(-1,1,2)))
        for frac in cfg['candidate_roi_width_fractions']:
            rect=roi_rect(int(r.image_width),int(r.image_height),float(frac),aspect,cap)
            roi_area=abs(cv2.contourArea(rect.reshape(-1,1,2)))
            if truncated:
                contained=False; coverage=np.nan; occ=np.nan; bg=np.nan; excessive=np.nan
            else:
                inter,_=cv2.intersectConvexConvex(poly.astype(np.float32),rect.astype(np.float32))
                coverage=float(inter/poly_area) if poly_area>0 else np.nan
                contained=inside_all(poly,rect)
                occ=float(inter/roi_area) if roi_area>0 else np.nan
                bg=float(1-occ)
                excessive=bool(occ<occ_thr) if contained else np.nan
            rows.append({
              'device':r.device,'sample_id':r.sample_id,'class_label':r.class_label,'distance_cm':int(r.distance_cm),'repeat_index':int(r.repeat_index),
              'candidate_roi_width_fraction':float(frac),'source_truncated':truncated,'fully_contained':contained,
              'banknote_coverage_ratio':coverage,'banknote_occupancy_in_roi':occ,'background_ratio_in_roi':bg,'excessive_background':excessive,
              'roi_left':float(rect[:,0].min()),'roi_top':float(rect[:,1].min()),'roi_right':float(rect[:,0].max()),'roi_bottom':float(rect[:,1].max())
            })
    m=pd.DataFrame(rows); m.to_csv(wd/'roi_geometric_metrics.csv',index=False)
    # Summaries. Background is only evaluated when source-complete and fully contained.
    s=m.groupby('candidate_roi_width_fraction').agg(
       total_samples=('sample_id','size'),
       fully_contained_count=('fully_contained','sum'),
       mean_coverage=('banknote_coverage_ratio','mean'),
       mean_occupancy=('banknote_occupancy_in_roi','mean')
    ).reset_index()
    bg=(m[m.fully_contained].groupby('candidate_roi_width_fraction')['excessive_background'].agg(['count','sum']).reset_index().rename(columns={'count':'background_evaluable_count','sum':'excessive_background_count'}))
    s=s.merge(bg,on='candidate_roi_width_fraction',how='left')
    s['fully_contained_rate']=s.fully_contained_count/s.total_samples
    s.to_csv(wd/'roi_geometric_summary.csv',index=False)
    by=m.groupby(['device','distance_cm','candidate_roi_width_fraction']).agg(total=('sample_id','size'),contained=('fully_contained','sum'),mean_coverage=('banknote_coverage_ratio','mean'),mean_occupancy=('banknote_occupancy_in_roi','mean')).reset_index()
    by['contained_rate']=by.contained/by.total
    by.to_csv(wd/'roi_geometric_by_device_distance.csv',index=False)
    lock={
      'status':'geometry_annotation_complete',
      'reviewed_nominal_samples':int(len(df)),
      'annotation_csv_sha256':sha256(ann),
      'config_sha256':sha256(wd/'config.json'),
      'geometry_formula':'w=min(width*fraction,height*0.90*aspect); h=w/aspect; centered',
      'candidate_fractions':cfg['candidate_roi_width_fractions'],
      'aspect_ratio':aspect,'height_cap_fraction':cap,'occupancy_threshold':occ_thr,
      'note':'This lock covers geometric ROI evidence only. It does not select final ROI; macro F1 remains the second-priority criterion in the thesis.'
    }
    (wd/'roi_geometry_lock.json').write_text(json.dumps(lock,indent=2,ensure_ascii=False))
    print(s.to_string(index=False)); print('\nWrote geometric metrics and lock.')

if __name__=='__main__': main()
