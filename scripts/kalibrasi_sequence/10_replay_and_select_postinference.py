#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

LABELS = ['1000','2000','5000','10000','20000','50000','100000','nonuang']
SCORE_COLS = [f'score_{x}' for x in LABELS]
SCENARIO_ORDER = ['stable','motion','distance','orientation','nonmoney','transition']


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def bool_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().eq('true')


def discover_sequence_dirs(root: Path) -> List[Path]:
    return sorted({p.parent for p in root.rglob('metadata.json') if '/sequences/' in p.as_posix()})


def dataset_fingerprint(root: Path) -> str:
    rels = ['checklist.csv','manifest.csv','collector_config.json','experiment_plan.json','checklist.json','manifest.jsonl']
    for d in discover_sequence_dirs(root):
        base = d.relative_to(root).as_posix()
        for fn in ['metadata.json','frames.csv','config_snapshot.json','stages.json']:
            rels.append(f'{base}/{fn}')
    entries = []
    for rel in sorted(rels):
        p = root / rel
        entries.append(f'{sha256_file(p)}  {rel}\n')
    return sha256_bytes(''.join(entries).encode('utf-8'))


@dataclass
class Stage:
    stage_id: str
    start_ms: int
    end_ms: int
    expected_label: Optional[str]
    analysis_role: str


@dataclass
class SequenceData:
    device: str
    sequence_id: str
    kind: str
    scenario: str
    primary_label: Optional[str]
    secondary_label: Optional[str]
    frames: pd.DataFrame
    stages: List[Stage]


class TemporalDecisionReplay:
    """Numerically mirrors the current Android TemporalDecision.kt semantics."""

    def __init__(self, threshold: float, window_ms: int, minimum_results: int = 3):
        self.threshold = np.float32(threshold)
        self.window_ms = int(window_ms)
        self.minimum_results = int(minimum_results)
        self.window: deque[Tuple[int, np.ndarray]] = deque()
        self.rejected_since: Optional[int] = None
        self.announced: Optional[str] = None
        self.last_observation: Optional[int] = None

    def observe(self, now: int) -> None:
        if self.last_observation is not None and now - self.last_observation > self.window_ms:
            self.window.clear()
            self.rejected_since = None
        self.last_observation = now
        while self.window and now - self.window[0][0] > self.window_ms:
            self.window.popleft()

    def reject(self, now: int) -> Tuple[Optional[str], bool, str]:
        self.observe(now)
        self.window.clear()
        if self.rejected_since is None:
            self.rejected_since = now
        if now - self.rejected_since >= self.window_ms:
            self.announced = None
        return None, False, 'reject'

    def accept(self, scores: np.ndarray, now: int) -> Tuple[Optional[str], bool, str]:
        self.observe(now)
        scores = np.asarray(scores, dtype=np.float32)
        winner = int(np.argmax(scores))
        if LABELS[winner] == 'nonuang' or scores[winner] < self.threshold:
            return self.reject(now)

        self.rejected_since = None
        self.window.append((now, scores.copy()))

        if len(self.window) < self.minimum_results:
            return None, False, 'warming'

        mean = np.zeros(len(LABELS), dtype=np.float32)
        n = np.float32(len(self.window))
        for _, item in self.window:
            mean += item / n

        best = int(np.argmax(mean))
        if LABELS[best] == 'nonuang' or mean[best] < self.threshold or best != winner:
            return None, False, 'unstable'

        label = LABELS[best]
        announce = label != self.announced
        if announce:
            # Offline replay assumes TTS accepts the request; this is the point at which
            # RecognitionSession calls markAnnounced on the same worker.
            self.announced = label
        return label, announce, 'stable'


def load_sequences(poco: Path, redmi: Path) -> List[SequenceData]:
    out: List[SequenceData] = []
    for device, root in [('poco', poco), ('redmi_4x_santoni', redmi)]:
        for d in discover_sequence_dirs(root):
            meta = read_json(d / 'metadata.json')
            stages_raw = read_json(d / 'stages.json')['stages']
            stages = [Stage(
                stage_id=str(s['stage_id']),
                start_ms=int(s['start_ms']),
                end_ms=int(s['end_ms']),
                expected_label=None if s.get('expected_label') is None else str(s.get('expected_label')),
                analysis_role=str(s['analysis_role'])
            ) for s in stages_raw]
            df = pd.read_csv(d / 'frames.csv', dtype={'expected_label':'string'})
            df['quality_pass_bool'] = bool_series(df['quality_pass'])
            df['elapsed_ms'] = df['elapsed_ms'].astype(int)
            df['frame_index'] = df['frame_index'].astype(int)
            for c in SCORE_COLS + ['top_score','pipeline_ms']:
                df[c] = pd.to_numeric(df[c], errors='coerce')
            out.append(SequenceData(
                device=device,
                sequence_id=str(meta['sequence_id']),
                kind=str(meta['kind']),
                scenario=str(meta['scenario']),
                primary_label=None if meta.get('primary_label') is None else str(meta.get('primary_label')),
                secondary_label=None if meta.get('secondary_label') is None else str(meta.get('secondary_label')),
                frames=df.sort_values('elapsed_ms').reset_index(drop=True),
                stages=stages,
            ))
    if len(out) != 80:
        raise RuntimeError(f'Sequence loaded={len(out)}, expected=80')
    return sorted(out, key=lambda x: (x.device, x.sequence_id))


def downsample_android_throttle(df: pd.DataFrame, fps: int) -> pd.DataFrame:
    interval = int(math.ceil(1000.0 / fps))
    keep = []
    last: Optional[int] = None
    for i, t in enumerate(df['elapsed_ms'].astype(int).tolist()):
        if last is None or t - last >= interval:
            keep.append(i)
            last = t
    return df.iloc[keep].copy().reset_index(drop=True)


def merge_target_segments(stages: Sequence[Stage]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for idx, s in enumerate(stages):
        if s.analysis_role != 'target':
            if cur is not None:
                out.append(cur)
                cur = None
            continue
        if cur is not None and cur['expected_label'] == s.expected_label and cur['end_ms'] == s.start_ms:
            cur['end_ms'] = s.end_ms
            cur['stage_ids'].append(s.stage_id)
            cur['last_stage_index'] = idx
        else:
            if cur is not None:
                out.append(cur)
            cur = {
                'expected_label': s.expected_label,
                'start_ms': s.start_ms,
                'end_ms': s.end_ms,
                'stage_ids': [s.stage_id],
                'first_stage_index': idx,
                'last_stage_index': idx,
            }
    if cur is not None:
        out.append(cur)
    return out


def stage_for_time(stages: Sequence[Stage], t: int) -> Optional[Stage]:
    for s in stages:
        if s.start_ms <= t < s.end_ms:
            return s
    return None


def replay_sequence(seq: SequenceData, fps: int, threshold: float, window_ms: int, minimum_results: int) -> Dict[str, Any]:
    selected = downsample_android_throttle(seq.frames, fps)
    td = TemporalDecisionReplay(threshold, window_ms, minimum_results)
    events = []

    for row in selected.itertuples(index=False):
        now = int(row.elapsed_ms)
        qp = bool(row.quality_pass_bool)
        raw_top = None
        raw_score = None
        if qp:
            vals = np.asarray([getattr(row, c) for c in SCORE_COLS], dtype=np.float32)
            raw_idx = int(np.argmax(vals))
            raw_top = LABELS[raw_idx]
            raw_score = float(vals[raw_idx])
            label, announce, state = td.accept(vals, now)
        else:
            label, announce, state = td.reject(now)
        st = stage_for_time(seq.stages, now)
        events.append({
            'elapsed_ms': now,
            'stage_id': None if st is None else st.stage_id,
            'analysis_role': None if st is None else st.analysis_role,
            'expected_label': None if st is None else st.expected_label,
            'quality_pass': qp,
            'raw_top_label': raw_top,
            'raw_top_score': raw_score,
            'decision_label': label,
            'announce': bool(announce),
            'decision_state': state,
        })

    target_rows = []
    targets = merge_target_segments(seq.stages)
    for j, seg in enumerate(targets):
        expected = str(seg['expected_label'])
        start = int(seg['start_ms'])
        end = int(seg['end_ms'])
        first_idx = int(seg['first_stage_index'])

        # Direct transition special case: a correct B announcement during the unlabeled
        # direct-swap stage is allowed to count as an early successful transition.
        direct_transition_start = None
        if first_idx > 0:
            prev = seq.stages[first_idx - 1]
            if prev.analysis_role == 'transition' and prev.expected_label is None:
                direct_transition_start = prev.start_ms

        interval_start = direct_transition_start if direct_transition_start is not None else start
        interval_events = [e for e in events if interval_start <= e['elapsed_ms'] < end]
        target_events = [e for e in events if start <= e['elapsed_ms'] < end]
        qp_target = [e for e in target_events if e['quality_pass']]
        t_start = qp_target[0]['elapsed_ms'] if qp_target else None

        announces_eval = [e for e in interval_events if e['announce'] and e['decision_label'] is not None]
        correct_events = [e for e in announces_eval if e['decision_label'] == expected]
        wrong_events_target = [e for e in target_events if e['announce'] and e['decision_label'] is not None and e['decision_label'] != expected]

        if wrong_events_target:
            outcome = 'wrong'
        elif correct_events:
            outcome = 'correct'
        else:
            outcome = 'reject'

        first_correct_time = correct_events[0]['elapsed_ms'] if correct_events else None
        if first_correct_time is not None:
            if t_start is None:
                # Early correct announcement during direct transition before target proper.
                decision_ms = 0.0 if direct_transition_start is not None and first_correct_time < start else None
            else:
                decision_ms = float(max(0, first_correct_time - t_start))
        else:
            decision_ms = None

        target_rows.append({
            'device': seq.device,
            'sequence_id': seq.sequence_id,
            'scenario': seq.scenario,
            'segment_index': j,
            'expected_label': expected,
            'target_start_ms': start,
            'target_end_ms': end,
            'direct_transition_eval_start_ms': direct_transition_start,
            'first_quality_pass_ms': t_start,
            'outcome': outcome,
            'decision_ms': decision_ms,
            'correct_announcement_count': len(correct_events),
            'wrong_announcement_count': len(wrong_events_target),
            'announced_labels_eval_interval': '|'.join(str(e['decision_label']) for e in announces_eval),
        })

    nonmoney_rows = []
    for s in seq.stages:
        if s.analysis_role != 'nonmoney':
            continue
        anns = [e for e in events if s.start_ms <= e['elapsed_ms'] < s.end_ms and e['announce'] and e['decision_label'] is not None]
        nonmoney_rows.append({
            'device': seq.device,
            'sequence_id': seq.sequence_id,
            'scenario': seq.scenario,
            'stage_id': s.stage_id,
            'start_ms': s.start_ms,
            'end_ms': s.end_ms,
            'false_accept': bool(anns),
            'announcement_count': len(anns),
            'announced_labels': '|'.join(str(e['decision_label']) for e in anns),
        })

    reset_rows = []
    for s in seq.stages:
        if s.analysis_role != 'reset':
            continue
        anns = [e for e in events if s.start_ms <= e['elapsed_ms'] < s.end_ms and e['announce'] and e['decision_label'] is not None]
        reset_rows.append({
            'device': seq.device,
            'sequence_id': seq.sequence_id,
            'scenario': seq.scenario,
            'stage_id': s.stage_id,
            'expected_label': s.expected_label,
            'false_nominal_announcement': bool(anns),
            'announcement_count': len(anns),
            'announced_labels': '|'.join(str(e['decision_label']) for e in anns),
        })

    transition_rows = []
    for s in seq.stages:
        if s.analysis_role != 'transition':
            continue
        anns = [e for e in events if s.start_ms <= e['elapsed_ms'] < s.end_ms and e['announce'] and e['decision_label'] is not None]
        transition_rows.append({
            'device': seq.device,
            'sequence_id': seq.sequence_id,
            'scenario': seq.scenario,
            'stage_id': s.stage_id,
            'announcement_count': len(anns),
            'announced_labels': '|'.join(str(e['decision_label']) for e in anns),
        })

    # Predeclared sequence-success rules.
    if seq.kind == 'nominal':
        success = len(target_rows) == 1 and target_rows[0]['outcome'] == 'correct'
        scenario_group = seq.scenario
    elif seq.kind == 'nonuang':
        success = bool(nonmoney_rows) and all(not x['false_accept'] for x in nonmoney_rows)
        scenario_group = 'nonmoney'
    elif seq.kind == 'transition':
        target_ok = len(target_rows) == 2 and all(x['outcome'] == 'correct' for x in target_rows)
        # Only a labelled nonmoney/empty middle stage is scored. Prepare/remove reset stages
        # remain diagnostics and do not dominate the transition scenario.
        middle_reset = [x for x in reset_rows if x['stage_id'] == 'middle' and x['expected_label'] == 'nonuang']
        middle_ok = all(not x['false_nominal_announcement'] for x in middle_reset)
        success = target_ok and middle_ok
        scenario_group = 'transition'
    else:
        raise RuntimeError(f'kind tidak dikenal: {seq.kind}')

    return {
        'selected_frames': selected,
        'events': events,
        'targets': target_rows,
        'nonmoney': nonmoney_rows,
        'resets': reset_rows,
        'transitions': transition_rows,
        'sequence': {
            'device': seq.device,
            'sequence_id': seq.sequence_id,
            'kind': seq.kind,
            'scenario': seq.scenario,
            'scenario_group': scenario_group,
            'success': bool(success),
            'replayed_frame_count': int(len(selected)),
            'replayed_quality_pass_count': int(selected['quality_pass_bool'].sum()),
        }
    }


def safe_percentile(values: Sequence[float], p: float) -> float:
    vals = np.asarray([x for x in values if x is not None and np.isfinite(x)], dtype=np.float64)
    return float(np.percentile(vals, p)) if len(vals) else float('nan')


def run_candidate(seqs: Sequence[SequenceData], fps: int, threshold: float, window_ms: int, minimum_results: int) -> Tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    targets, nonmoney, resets, transitions, sequence_rows = [], [], [], [], []
    for seq in seqs:
        r = replay_sequence(seq, fps, threshold, window_ms, minimum_results)
        targets.extend(r['targets'])
        nonmoney.extend(r['nonmoney'])
        resets.extend(r['resets'])
        transitions.extend(r['transitions'])
        sequence_rows.append(r['sequence'])
    return (pd.DataFrame(targets), pd.DataFrame(nonmoney), pd.DataFrame(resets), pd.DataFrame(transitions), pd.DataFrame(sequence_rows))


def candidate_id(threshold: float, window_ms: int) -> str:
    return f't{int(round(threshold*100)):02d}_w{int(window_ms)}'


def compute_metrics(T: pd.DataFrame, N: pd.DataFrame, R: pd.DataFrame, S: pd.DataFrame, threshold: float, window_ms: int, fps: int) -> Tuple[Dict[str,Any], pd.DataFrame, pd.DataFrame]:
    n = len(T)
    correct = int((T['outcome'] == 'correct').sum())
    wrong = int((T['outcome'] == 'wrong').sum())
    reject = int((T['outcome'] == 'reject').sum())
    if correct + wrong + reject != n:
        raise RuntimeError('Target outcome tidak saling eksklusif')

    scen = S.groupby('scenario_group', sort=False)['success'].mean().reindex(SCENARIO_ORDER)
    if scen.isna().any():
        raise RuntimeError(f'Scenario group tidak lengkap: {scen}')
    mssr = float(scen.mean())
    ds = S.groupby(['device','scenario_group'])['success'].mean()
    mssr_device_balanced = float(ds.mean())

    class_stats = []
    for label in LABELS[:-1]:
        x = T[T['expected_label'] == label]
        if x.empty:
            raise RuntimeError(f'Tidak ada target untuk kelas {label}')
        class_stats.append({
            'expected_label': label,
            'n_target': len(x),
            'correct': int((x['outcome']=='correct').sum()),
            'wrong': int((x['outcome']=='wrong').sum()),
            'reject': int((x['outcome']=='reject').sum()),
            'car': float((x['outcome']=='correct').mean()),
        })
    C = pd.DataFrame(class_stats)

    D = T.loc[T['outcome']=='correct','decision_ms'].dropna().astype(float).tolist()
    nonmoney_fa = int(N['false_accept'].sum()) if not N.empty else 0
    reset_fa = int(R['false_nominal_announcement'].sum()) if not R.empty else 0

    metric = {
        'candidate_id': candidate_id(threshold, window_ms),
        'analysis_fps': int(fps),
        'threshold': float(threshold),
        'window_ms': int(window_ms),
        'minimum_results': 3,
        'target_segments': int(n),
        'correct_count': correct,
        'wrong_count': wrong,
        'reject_count': reject,
        'car': correct / n,
        'war': wrong / n,
        'rr_nominal': reject / n,
        'nonmoney_segments': int(len(N)),
        'nonmoney_false_accept_count': nonmoney_fa,
        'nonmoney_false_accept_rate': nonmoney_fa / len(N) if len(N) else float('nan'),
        'reset_stage_count': int(len(R)),
        'reset_false_announcement_count': reset_fa,
        'sequence_success_count': int(S['success'].sum()),
        'sequence_count': int(len(S)),
        'mssr': mssr,
        'mssr_device_balanced': mssr_device_balanced,
        'median_decision_ms': float(np.median(D)) if D else float('nan'),
        'p95_decision_ms': safe_percentile(D, 95),
        'min_class_car': float(C['car'].min()),
    }
    scenario_df = scen.rename('success_rate').reset_index().rename(columns={'scenario_group':'scenario_group'})
    return metric, C, scenario_df


def frame_level_youden(seqs: Sequence[SequenceData], fps: int, thresholds: Sequence[float]) -> pd.DataFrame:
    rows = []
    obs = []
    for seq in seqs:
        df = downsample_android_throttle(seq.frames, fps)
        for r in df.itertuples(index=False):
            if not bool(r.quality_pass_bool):
                continue
            role = str(r.analysis_role)
            exp = None if pd.isna(r.expected_label) else str(r.expected_label)
            if role != 'target' or exp not in LABELS[:-1]:
                continue
            vals = np.asarray([getattr(r, c) for c in SCORE_COLS], dtype=np.float32)
            idx = int(np.argmax(vals))
            top_label = LABELS[idx]
            top_score = float(vals[idx])
            obs.append((top_label == exp, top_label, top_score))
    n_correct = sum(1 for x in obs if x[0])
    n_wrong = sum(1 for x in obs if not x[0])
    for th in thresholds:
        tp = fn = tn = fp = 0
        for is_correct, top_label, top_score in obs:
            accepted = (top_label != 'nonuang') and (top_score >= th)
            if is_correct and accepted: tp += 1
            elif is_correct and not accepted: fn += 1
            elif (not is_correct) and accepted: fp += 1
            else: tn += 1
        sens = tp/(tp+fn) if (tp+fn) else float('nan')
        spec = tn/(tn+fp) if (tn+fp) else float('nan')
        rows.append({
            'analysis_fps': fps,
            'threshold': th,
            'n_correct_raw_frames': n_correct,
            'n_wrong_raw_frames': n_wrong,
            'tp_correct_accepted': tp,
            'fn_correct_rejected': fn,
            'tn_wrong_rejected': tn,
            'fp_wrong_accepted': fp,
            'sensitivity': sens,
            'specificity': spec,
            'youden_j': sens + spec - 1.0,
        })
    return pd.DataFrame(rows)


def bootstrap_mssr(sequence_results: pd.DataFrame, candidate_order: List[str], iterations: int, seed: int) -> Tuple[pd.DataFrame, Dict[str,float]]:
    pivot = sequence_results.pivot(index=['device','sequence_id','scenario_group'], columns='candidate_id', values='success')
    pivot = pivot[candidate_order].astype(float)
    index_df = pivot.index.to_frame(index=False)
    mat = pivot.to_numpy(dtype=np.float64).T  # candidates x sequences

    strata = []
    for _, g in index_df.groupby(['device','scenario_group'], sort=True):
        strata.append(g.index.to_numpy(dtype=int))
    if len(strata) != 12:
        raise RuntimeError(f'Bootstrap strata={len(strata)}, expected 12')

    rng = np.random.default_rng(seed)
    samples = np.empty((iterations, len(candidate_order)), dtype=np.float64)
    for b in range(iterations):
        stratum_means = []
        for idx in strata:
            draw = rng.choice(idx, size=len(idx), replace=True)
            stratum_means.append(mat[:, draw].mean(axis=1))
        samples[b, :] = np.vstack(stratum_means).mean(axis=0)

    summary = []
    se_map = {}
    for j, cid in enumerate(candidate_order):
        vals = samples[:, j]
        se = float(vals.std(ddof=1))
        se_map[cid] = se
        summary.append({
            'candidate_id': cid,
            'bootstrap_iterations': iterations,
            'bootstrap_seed': seed,
            'mssr_bootstrap_mean': float(vals.mean()),
            'mssr_bootstrap_se': se,
            'ci95_low': float(np.percentile(vals, 2.5)),
            'ci95_high': float(np.percentile(vals, 97.5)),
        })
    return pd.DataFrame(summary), se_map


def select_final(metrics: pd.DataFrame, bootstrap_summary: pd.DataFrame, plan: Dict[str,Any]) -> Dict[str,Any]:
    m = metrics.copy()
    b = bootstrap_summary.set_index('candidate_id')
    max_mssr = float(m['mssr'].max())
    best = m[np.isclose(m['mssr'], max_mssr, atol=1e-12, rtol=0.0)]
    best_ids = best['candidate_id'].tolist()
    best_se = max(float(b.loc[cid,'mssr_bootstrap_se']) for cid in best_ids)
    gate_threshold = max_mssr - best_se
    m['passes_one_se_mssr'] = m['mssr'] >= gate_threshold - 1e-12
    m['passes_all_class_car_positive'] = m['min_class_car'] > 0.0
    m['eligible'] = m['passes_one_se_mssr'] & m['passes_all_class_car_positive']
    eligible = m[m['eligible']].copy()
    if eligible.empty:
        raise RuntimeError('Tidak ada kandidat yang lolos quality gate. Jangan melonggarkan aturan secara otomatis.')

    eligible['_p95'] = eligible['p95_decision_ms'].fillna(np.inf)
    eligible['_median'] = eligible['median_decision_ms'].fillna(np.inf)
    eligible = eligible.sort_values(
        ['wrong_count','reject_count','_p95','_median','window_ms','threshold'],
        ascending=[True,True,True,True,True,False],
        kind='mergesort'
    )
    selected = eligible.iloc[0]

    # Explicit trace with remaining candidates after each priority.
    remaining = m[m['eligible']].copy()
    trace = []
    rules = [
        ('wrong_count','min'),
        ('reject_count','min'),
        ('p95_decision_ms','min'),
        ('median_decision_ms','min'),
        ('window_ms','min'),
        ('threshold','max'),
    ]
    for priority, (col, direction) in enumerate(rules, start=1):
        vals = remaining[col].copy()
        if col in ['p95_decision_ms','median_decision_ms']:
            vals = vals.fillna(np.inf)
        best_val = vals.min() if direction == 'min' else vals.max()
        mask = np.isclose(vals.astype(float), float(best_val), atol=1e-12, rtol=0.0) if np.isfinite(float(best_val)) else vals.eq(best_val)
        remaining = remaining.loc[mask].copy()
        trace.append({
            'priority': priority,
            'criterion': col,
            'direction': direction,
            'best_value': None if not np.isfinite(float(best_val)) else float(best_val),
            'remaining_candidates': remaining['candidate_id'].tolist(),
        })
        if len(remaining) == 1:
            break

    return {
        'selection_status': 'selected_unique_postinference_configuration',
        'quality_gate': {
            'max_observed_mssr': max_mssr,
            'best_mssr_candidate_ids': best_ids,
            'reference_se_for_one_se_gate': best_se,
            'mssr_one_se_threshold': gate_threshold,
            'eligible_candidate_count': int(m['eligible'].sum()),
            'class_gate': 'min_class_car > 0',
        },
        'selected': {
            'candidate_id': str(selected['candidate_id']),
            'analysis_fps': int(selected['analysis_fps']),
            'confidence_threshold': float(selected['threshold']),
            'temporal_window_ms': int(selected['window_ms']),
            'minimum_results': int(selected['minimum_results']),
            'mssr': float(selected['mssr']),
            'car': float(selected['car']),
            'war': float(selected['war']),
            'rr_nominal': float(selected['rr_nominal']),
            'nonmoney_false_accept_rate': float(selected['nonmoney_false_accept_rate']),
            'median_decision_ms': float(selected['median_decision_ms']),
            'p95_decision_ms': float(selected['p95_decision_ms']),
            'min_class_car': float(selected['min_class_car']),
        },
        'lexicographic_trace': trace,
        'selection_rule': plan['final_lexicographic_selection'],
    }, m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--poco', type=Path, required=True)
    ap.add_argument('--redmi', type=Path, required=True)
    ap.add_argument('--input-audit-dir', type=Path, required=True)
    ap.add_argument('--plan', type=Path, default=Path(__file__).with_name('analysis_plan.json'))
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()

    plan = read_json(args.plan)
    lock_path = args.input_audit_dir / 'sequence_input_lock.json'
    audit_path = args.input_audit_dir / 'sequence_input_audit.json'
    lock = read_json(lock_path)
    audit = read_json(audit_path)

    # Verify Stage 09 artifacts.
    for name, expected in lock['output_sha256'].items():
        actual = sha256_file(args.input_audit_dir / name)
        if actual != expected:
            raise RuntimeError(f'Stage09 output hash mismatch {name}')
    if sha256_file(args.plan) != lock['analysis_plan_sha256']:
        raise RuntimeError('analysis_plan.json berubah setelah Stage09')
    if dataset_fingerprint(args.poco) != lock['input_fingerprints']['poco']:
        raise RuntimeError('Dataset POCO berubah setelah Stage09')
    if dataset_fingerprint(args.redmi) != lock['input_fingerprints']['redmi_4x_santoni']:
        raise RuntimeError('Dataset Redmi berubah setelah Stage09')

    fps = int(lock['selected_analysis_fps'])
    thresholds = [float(x) for x in plan['confidence_thresholds']]
    windows = [int(x) for x in plan['temporal_windows_ms']]
    minimum_results = int(plan['minimum_results'])
    seqs = load_sequences(args.poco, args.redmi)

    args.out.mkdir(parents=True, exist_ok=True)

    # Frame-level confidence evidence (descriptive initial Youden stage).
    youden = frame_level_youden(seqs, fps, thresholds)
    youden.to_csv(args.out / 'frame_level_youden.csv', index=False)
    max_j = float(youden['youden_j'].max())
    youden_best = youden[np.isclose(youden['youden_j'], max_j, atol=1e-12, rtol=0.0)]
    write_json(args.out / 'frame_level_youden_summary.json', {
        'analysis_fps': fps,
        'max_youden_j': max_j,
        'argmax_thresholds': youden_best['threshold'].astype(float).tolist(),
        'role': 'descriptive initial confidence evidence; does not replace sequence-level final selection'
    })

    metric_rows = []
    all_targets = []
    all_nonmoney = []
    all_resets = []
    all_transitions = []
    all_sequence = []
    all_class = []
    all_scenario = []

    for th in thresholds:
        for win in windows:
            cid = candidate_id(th, win)
            T,N,R,X,S = run_candidate(seqs, fps, th, win, minimum_results)
            metric,C,G = compute_metrics(T,N,R,S,th,win,fps)
            metric_rows.append(metric)
            for df in [T,N,R,X,S,C,G]:
                df.insert(0,'candidate_id',cid)
                df.insert(1,'analysis_fps',fps)
                df.insert(2,'threshold',th)
                df.insert(3,'window_ms',win)
            all_targets.append(T); all_nonmoney.append(N); all_resets.append(R); all_transitions.append(X); all_sequence.append(S); all_class.append(C); all_scenario.append(G)

    metrics = pd.DataFrame(metric_rows).sort_values(['threshold','window_ms']).reset_index(drop=True)
    targets = pd.concat(all_targets, ignore_index=True)
    nonmoney = pd.concat(all_nonmoney, ignore_index=True)
    resets = pd.concat(all_resets, ignore_index=True)
    transitions = pd.concat(all_transitions, ignore_index=True)
    sequence_results = pd.concat(all_sequence, ignore_index=True)
    class_metrics = pd.concat(all_class, ignore_index=True)
    scenario_metrics = pd.concat(all_scenario, ignore_index=True)

    candidate_order = metrics['candidate_id'].tolist()
    boot_cfg = plan['mssr']['bootstrap']
    boot_summary, _ = bootstrap_mssr(sequence_results, candidate_order, int(boot_cfg['iterations']), int(boot_cfg['seed']))
    decision, metrics_with_gate = select_final(metrics, boot_summary, plan)

    # Merge bootstrap and gate columns into final candidate table.
    final_metrics = metrics_with_gate.merge(boot_summary, on='candidate_id', how='left')
    final_metrics = final_metrics.sort_values(['threshold','window_ms']).reset_index(drop=True)

    final_metrics.to_csv(args.out / 'candidate_metrics.csv', index=False)
    targets.to_csv(args.out / 'target_episode_outcomes.csv', index=False)
    nonmoney.to_csv(args.out / 'nonmoney_episode_outcomes.csv', index=False)
    resets.to_csv(args.out / 'reset_stage_diagnostics.csv', index=False)
    transitions.to_csv(args.out / 'direct_transition_diagnostics.csv', index=False)
    sequence_results.to_csv(args.out / 'sequence_success_results.csv', index=False)
    class_metrics.to_csv(args.out / 'per_class_car.csv', index=False)
    scenario_metrics.to_csv(args.out / 'scenario_success_rates.csv', index=False)
    boot_summary.to_csv(args.out / 'bootstrap_mssr_summary.csv', index=False)

    decision['analysis_plan_sha256'] = sha256_file(args.plan)
    decision['sequence_input_lock_sha256'] = sha256_file(lock_path)
    decision['source_fingerprints'] = lock['input_fingerprints']
    decision['android_source_hashes'] = lock['android_source_hashes']
    write_json(args.out / 'postinference_selection_decision.json', decision)

    out_names = [
        'frame_level_youden.csv','frame_level_youden_summary.json','candidate_metrics.csv',
        'target_episode_outcomes.csv','nonmoney_episode_outcomes.csv','reset_stage_diagnostics.csv',
        'direct_transition_diagnostics.csv','sequence_success_results.csv','per_class_car.csv',
        'scenario_success_rates.csv','bootstrap_mssr_summary.csv','postinference_selection_decision.json'
    ]
    output_hashes = {n: sha256_file(args.out / n) for n in out_names}
    final_lock = {
        'status': 'postinference_sequence_calibration_locked',
        'analysis_plan_sha256': sha256_file(args.plan),
        'sequence_input_lock_sha256': sha256_file(lock_path),
        'selected_analysis_fps': fps,
        'selected_postinference': decision['selected'],
        'output_sha256': output_hashes,
    }
    write_json(args.out / 'postinference_calibration_lock.json', final_lock)

    print('=== POST-INFERENCE SEQUENCE CALIBRATION ===')
    print(f'analysis_fps={fps}')
    print(f'candidates={len(final_metrics)}')
    print(f"MSSR best={decision['quality_gate']['max_observed_mssr']:.6f}")
    print(f"1-SE gate={decision['quality_gate']['mssr_one_se_threshold']:.6f}")
    print(f"eligible={decision['quality_gate']['eligible_candidate_count']}")
    print(json.dumps(decision['selected'], indent=2, ensure_ascii=False))
    print('SELECTION_STATUS=POSTINFERENCE_CONFIGURATION_SELECTED')
    print(f'Wrote: {args.out}')


if __name__ == '__main__':
    main()
