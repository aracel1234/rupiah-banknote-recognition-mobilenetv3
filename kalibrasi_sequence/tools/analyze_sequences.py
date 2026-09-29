#!/usr/bin/env python3
"""Replay the thesis post-inference rule over collected frame-score sequences.

This script intentionally does NOT choose the final configuration automatically.
It exports comparable metrics for every candidate requested by the thesis:
FPS {3,5}, confidence threshold 0.50..0.95 step 0.05, temporal window {1000,1500,2000} ms,
minimum 3 results, mean of complete 8-class score vectors.
"""
import argparse, csv, json, math, statistics
from pathlib import Path

LABELS = ["1000","2000","5000","10000","20000","50000","100000","nonuang"]
SCORE_COLS = [f"score_{x}" for x in LABELS]
THRESHOLDS = [x/100 for x in range(50,96,5)]
WINDOWS = [1000,1500,2000]
FPS_VALUES = [3,5]
MIN_RESULTS = 3


def read_sequences(root: Path):
    out = []
    for meta in sorted((root / "sequences").rglob("metadata.json")):
        d = meta.parent
        m = json.loads(meta.read_text())
        stages = json.loads((d / "stages.json").read_text())["stages"]
        with (d / "frames.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        out.append((m, stages, rows))
    return out


def downsample(rows, fps):
    interval = (1000 + fps - 1) // fps  # exact integer rule used by the Android thesis app
    selected, last = [], None
    for r in rows:
        t = int(r["elapsed_ms"])
        if last is None or t - last >= interval:
            selected.append(r); last = t
    return selected


def winner(scores):
    idx = max(range(len(scores)), key=lambda i: scores[i])
    return idx, LABELS[idx], scores[idx]


def simulate(rows, threshold, window_ms):
    window = []
    last_observation = None
    decisions = []
    for r in rows:
        now = int(r["elapsed_ms"])
        if last_observation is not None and now - last_observation > window_ms:
            window.clear()
        last_observation = now
        window = [(t,s) for (t,s) in window if now - t <= window_ms]

        if r.get("quality_pass", "").lower() != "true":
            window.clear()
            continue
        try:
            scores = [float(r[c]) for c in SCORE_COLS]
        except Exception:
            window.clear(); continue
        idx, label, conf = winner(scores)
        if label == "nonuang" or conf < threshold:
            window.clear()
            continue
        window.append((now, scores))
        if len(window) < MIN_RESULTS:
            continue
        mean = [sum(s[i] for _,s in window)/len(window) for i in range(8)]
        best_idx, best_label, best_conf = winner(mean)
        # Match current production TemporalDecision: averaged winner must also match current-frame winner.
        if best_label == "nonuang" or best_conf < threshold or best_idx != idx:
            continue
        decisions.append((now, best_label, best_conf))
    return decisions


def segments(stages):
    """Merge adjacent analyzable stages with the same expected label."""
    result=[]
    for s in stages:
        label = s.get("expected_label")
        role = s.get("analysis_role")
        if label is None or role == "transition":
            continue
        start, end = int(s["start_ms"]), int(s["end_ms"])
        if result and result[-1][2] == label and result[-1][1] == start:
            result[-1] = (result[-1][0], end, label, result[-1][3] + "+" + role)
        else:
            result.append((start, end, label, role))
    return result


def percentile(values, p):
    if not values: return None
    xs=sorted(values); idx=int((len(xs)-1)*p); return xs[idx]


def analyze_roots(roots, out_dir: Path):
    rows_out=[]
    detailed=[]
    all_sequences=[]
    for root in roots:
        device=root.name
        for m, stages, rows in read_sequences(root):
            all_sequences.append((device,m,stages,rows))

    for fps in FPS_VALUES:
      for threshold in THRESHOLDS:
       for window in WINDOWS:
        counters={"correct":0,"wrong":0,"reject":0,"nonmoney_segments":0,"false_accept":0,"reset_segments":0,"reset_false_accept":0}
        decision_times=[]
        per_device={}
        for device,m,stages,rows in all_sequences:
            chosen=downsample(rows,fps)
            decisions=simulate(chosen,threshold,window)
            dev=per_device.setdefault(device,{"correct":0,"wrong":0,"reject":0,"nonmoney_segments":0,"false_accept":0,"reset_segments":0,"reset_false_accept":0,"lat":[]})
            for start,end,label,role in segments(stages):
                # 300 ms guard against human response time at cue boundary.
                eval_start=min(end,start+300)
                ds=[d for d in decisions if eval_start <= d[0] < end]
                if label == "nonuang":
                    bad=any(d[1] != "nonuang" for d in ds)
                    is_object = "nonmoney" in role
                    if is_object:
                        counters["nonmoney_segments"]+=1; dev["nonmoney_segments"]+=1
                        if bad: counters["false_accept"]+=1; dev["false_accept"]+=1
                    else:
                        counters["reset_segments"]+=1; dev["reset_segments"]+=1
                        if bad: counters["reset_false_accept"]+=1; dev["reset_false_accept"]+=1
                    detailed.append({"device":device,"sequence_id":m["sequence_id"],"segment_start_ms":start,"segment_end_ms":end,"expected_label":label,"fps":fps,"threshold":threshold,"window_ms":window,"outcome":"false_accept" if bad else "correct_reject","decision_ms":"","segment_role":role})
                else:
                    if not ds:
                        outcome="reject"; counters["reject"]+=1; dev["reject"]+=1; latency=""
                    else:
                        first=ds[0]
                        latency=first[0]-start
                        if first[1] == label:
                            outcome="correct"; counters["correct"]+=1; dev["correct"]+=1; decision_times.append(latency); dev["lat"].append(latency)
                        else:
                            outcome="wrong"; counters["wrong"]+=1; dev["wrong"]+=1
                    detailed.append({"device":device,"sequence_id":m["sequence_id"],"segment_start_ms":start,"segment_end_ms":end,"expected_label":label,"fps":fps,"threshold":threshold,"window_ms":window,"outcome":outcome,"decision_ms":latency,"segment_role":role})
        nominal_n=counters["correct"]+counters["wrong"]+counters["reject"]
        rows_out.append({
            "scope":"pooled","fps":fps,"threshold":f"{threshold:.2f}","window_ms":window,"minimum_results":MIN_RESULTS,
            "nominal_segments":nominal_n,"correct":counters["correct"],"wrong":counters["wrong"],"reject":counters["reject"],
            "car":counters["correct"]/nominal_n if nominal_n else "","war":counters["wrong"]/nominal_n if nominal_n else "","rr":counters["reject"]/nominal_n if nominal_n else "",
            "nonmoney_segments":counters["nonmoney_segments"],"false_accept":counters["false_accept"],
            "far_nonuang":counters["false_accept"]/counters["nonmoney_segments"] if counters["nonmoney_segments"] else "",
            "reset_segments":counters["reset_segments"],"reset_false_accept":counters["reset_false_accept"],
            "reset_false_accept_rate":counters["reset_false_accept"]/counters["reset_segments"] if counters["reset_segments"] else "",
            "median_decision_ms":statistics.median(decision_times) if decision_times else "","p95_decision_ms":percentile(decision_times,.95) if decision_times else ""
        })
        for device,d in per_device.items():
            n=d["correct"]+d["wrong"]+d["reject"]
            rows_out.append({"scope":device,"fps":fps,"threshold":f"{threshold:.2f}","window_ms":window,"minimum_results":MIN_RESULTS,
                "nominal_segments":n,"correct":d["correct"],"wrong":d["wrong"],"reject":d["reject"],"car":d["correct"]/n if n else "","war":d["wrong"]/n if n else "","rr":d["reject"]/n if n else "",
                "nonmoney_segments":d["nonmoney_segments"],"false_accept":d["false_accept"],"far_nonuang":d["false_accept"]/d["nonmoney_segments"] if d["nonmoney_segments"] else "",
                "reset_segments":d["reset_segments"],"reset_false_accept":d["reset_false_accept"],"reset_false_accept_rate":d["reset_false_accept"]/d["reset_segments"] if d["reset_segments"] else "",
                "median_decision_ms":statistics.median(d["lat"]) if d["lat"] else "","p95_decision_ms":percentile(d["lat"],.95) if d["lat"] else ""})

    out_dir.mkdir(parents=True,exist_ok=True)
    headers=list(rows_out[0].keys()) if rows_out else []
    with (out_dir/"candidate_metrics.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=headers); w.writeheader(); w.writerows(rows_out)
    if detailed:
        with (out_dir/"segment_results.csv").open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(detailed[0].keys())); w.writeheader(); w.writerows(detailed)
    summary={
        "schema_version":1,
        "devices":[r.name for r in roots],
        "sequences_loaded":len(all_sequences),
        "candidate_fps":FPS_VALUES,
        "candidate_thresholds":THRESHOLDS,
        "candidate_windows_ms":WINDOWS,
        "minimum_results":MIN_RESULTS,
        "automatic_winner_selected":False,
        "note":"This script exports candidate metrics only. Final parameter choice must follow the thesis method and be documented in Subchapter 5.7.3. A 300 ms stage-boundary guard is excluded from endpoint scoring to reduce cue-response timing contamination."
    }
    (out_dir/"analysis_summary.json").write_text(json.dumps(summary,indent=2))
    return summary


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("roots", nargs="+", type=Path, help="One or two device dataset roots")
    ap.add_argument("--out-dir", type=Path, default=Path("sequence_analysis"))
    args=ap.parse_args()
    summary=analyze_roots(args.roots,args.out_dir)
    print(json.dumps(summary,indent=2))

if __name__=="__main__": main()
