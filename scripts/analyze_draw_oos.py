#!/usr/bin/env python3
"""Analyze out-of-sample draw (X) forecasts from a Kini prediction-ledger JSONL.

This is a diagnostic-only tool: it never modifies forecasts or model parameters.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

SIGNS = ("1", "X", "2")


def read_ledger(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not records or records[0].get("record_type") != "run_manifest":
        raise ValueError("JSONL must begin with a run_manifest")
    manifest = {k: v for k, v in records[0].items() if k != "record_type"}
    rows = []
    seen = set()
    for rec in records[1:]:
        if rec.get("record_type") != "forecast":
            raise ValueError("unexpected record type in ledger")
        row = {k: v for k, v in rec.items() if k != "record_type"}
        if row.get("fixture_id") in seen:
            raise ValueError("duplicate fixture_id")
        seen.add(row.get("fixture_id"))
        if row.get("actual_result") not in SIGNS:
            raise ValueError("invalid actual_result")
        for mode, probs in row.get("model_probabilities", {}).items():
            _validate_vector(probs, f"{mode} fixture")
        rows.append(row)
    if len(rows) != manifest.get("forecast_count"):
        raise ValueError("manifest forecast_count mismatch")
    return manifest, rows


def _validate_vector(p: dict[str, Any], context: str) -> None:
    if not isinstance(p, dict) or set(p) != set(SIGNS):
        raise ValueError(f"{context}: probability vector must contain 1/X/2")
    vals = [p[s] for s in SIGNS]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or v > 1 for v in vals):
        raise ValueError(f"{context}: invalid probabilities")
    if abs(sum(vals)-1) > 1e-6:
        raise ValueError(f"{context}: probabilities do not sum to one")


def wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n == 0:
        return None
    p = k/n
    den = 1 + z*z/n
    center = (p + z*z/(2*n))/den
    radius = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return [max(0, center-radius), min(1, center+radius)]


def metric_rows(rows: list[dict[str, Any]], mode: str, bins: int) -> dict[str, Any]:
    usable = [r for r in rows if mode in r.get("model_probabilities", {})]
    if not usable:
        return {"n": 0}
    actual_draws = sum(r["actual_result"] == "X" for r in usable)
    selected = [r for r in usable if max(r["model_probabilities"][mode], key=r["model_probabilities"][mode].get) == "X"]
    hits = sum(r["actual_result"] == "X" for r in selected)
    top2 = [r for r in usable if "X" in sorted(SIGNS, key=lambda s: r["model_probabilities"][mode][s], reverse=True)[:2]]
    top2_hits = sum(r["actual_result"] == "X" for r in top2)
    px = [r["model_probabilities"][mode]["X"] for r in usable]
    obs = [int(r["actual_result"] == "X") for r in usable]
    brier = sum((p-y)**2 for p,y in zip(px,obs))/len(px)
    logloss = -sum(y*math.log(max(p,1e-15))+(1-y)*math.log(max(1-p,1e-15)) for p,y in zip(px,obs))/len(px)
    # fixed-width bins over [0,1], last bin includes 1
    calibration=[]
    for i in range(bins):
        lo,hi=i/bins,(i+1)/bins
        grp=[(p,y) for p,y in zip(px,obs) if (lo<=p<hi) or (i==bins-1 and p==1)]
        if grp:
            calibration.append({"bin":f"[{lo:.2f},{hi:.2f}{']' if i==bins-1 else ')'}","n":len(grp),"mean_predicted":sum(p for p,_ in grp)/len(grp),"observed_rate":sum(y for _,y in grp)/len(grp)})
    return {
        "n":len(usable),"draw_rate":actual_draws/len(usable),
        "x_top1_n":len(selected),"x_top1_hits":hits,"x_top1_precision":hits/len(selected) if selected else None,"x_top1_precision_wilson":wilson(hits,len(selected)),
        "draw_recall_when_x_top1":hits/actual_draws if actual_draws else None,"draw_recall_wilson":wilson(hits,actual_draws),
        "x_in_top2_n":len(top2),"x_in_top2_hits":top2_hits,"x_top2_recall":top2_hits/actual_draws if actual_draws else None,"x_top2_precision":top2_hits/len(top2) if top2 else None,
        "mean_p_x":sum(px)/len(px),"brier_x_binary":brier,"logloss_x_binary":logloss,"calibration_bins":calibration,
    }


def group_metrics(rows: list[dict[str, Any]], mode: str, field: str, bins: int) -> dict[str, Any]:
    groups=defaultdict(list)
    for row in rows:
        if field in row and row[field] is not None:
            groups[str(row[field])].append(row)
    return {key:metric_rows(value,mode,bins) for key,value in sorted(groups.items())}


def run(path: Path, output_dir: Path, bins: int) -> dict[str, Any]:
    manifest, rows=read_ledger(path)
    modes=sorted(set().union(*(r.get("model_probabilities",{}).keys() for r in rows)))
    results={}
    for mode in modes:
        results[mode]=metric_rows(rows,mode,bins)
        results[mode]["segments"]={field:group_metrics(rows,mode,field,bins) for field in ("season","league")}
    # Paired comparison: model and market are scored on identical fixture IDs.
    market_rows = [r for r in rows if r.get('market_eligible') and r.get('market_probabilities')]
    market_by_id = {r['fixture_id']: r for r in market_rows}
    results['market_snapshot_eligible'] = metric_rows([
        {**r, 'model_probabilities': {'market': r['market_probabilities']}} for r in market_rows
    ], 'market', bins)
    results['market_snapshot_eligible']['n_market_eligible'] = len(market_rows)
    paired = {}
    for mode in modes:
        common = [r for r in rows if r['fixture_id'] in market_by_id and mode in r.get('model_probabilities', {})]
        if not common:
            paired[mode] = {'n': 0}
            continue
        mb, kb, ml, kl = [], [], [], []
        mh, kh = 0, 0
        for row in common:
            y = int(row['actual_result'] == 'X')
            pm = float(row['model_probabilities'][mode]['X'])
            pk = float(market_by_id[row['fixture_id']]['market_probabilities']['X'])
            mb.append((pm-y)**2); kb.append((pk-y)**2)
            ml.append(-(y*math.log(max(pm,1e-15))+(1-y)*math.log(max(1-pm,1e-15))))
            kl.append(-(y*math.log(max(pk,1e-15))+(1-y)*math.log(max(1-pk,1e-15))))
            mh += int(max(row['model_probabilities'][mode], key=row['model_probabilities'][mode].get) == 'X' and y == 1)
            kp = market_by_id[row['fixture_id']]['market_probabilities']
            kh += int(max(kp, key=kp.get) == 'X' and y == 1)
        paired[mode] = {'n': len(common), 'model_x_brier': sum(mb)/len(common), 'market_x_brier': sum(kb)/len(common), 'delta_brier_model_minus_market': sum(a-b for a,b in zip(mb,kb))/len(common), 'model_x_logloss': sum(ml)/len(common), 'market_x_logloss': sum(kl)/len(common), 'delta_logloss_model_minus_market': sum(a-b for a,b in zip(ml,kl))/len(common), 'model_x_top1_hits': mh, 'market_x_top1_hits': kh}
    results['paired_market_comparison_same_fixtures'] = paired
    report={'schema_version':1,'source_ledger':str(path),'manifest':manifest,'rows':len(rows),'diagnostics':results,'limitations':['Segmentation fields are reported only when present in source ledger rows; xG/strength/disagreement are not inferred.','Market comparison is restricted to identical fixture IDs marked market_eligible; eligibility does not certify exact odds capture timestamps.','Paired differences are descriptive; no temporal block-bootstrap confidence intervals or significance tests are claimed.','No causal interpretation or model adjustment is performed.']}
    output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/"draw_diagnostic.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# OOS draw (X) diagnostic","",f"- Rows: {len(rows)}",f"- Source ledger: {path}",f"- Ledger code revision: {manifest.get('code_revision','unknown')}","", "## Summary"]
    for mode, m in results.items():
        if mode.startswith("market"):
            label="Market benchmark (eligible rows)"
        else: label=mode
        lines += [f"### {label}", "",f"- n: {m.get('n',0)}",f"- Draw prevalence: {m.get('draw_rate',float('nan')):.4f}",f"- P(X) mean: {m.get('mean_p_x',float('nan')):.4f}",f"- Binary X Brier: {m.get('brier_x_binary',float('nan')):.4f}",f"- Binary X Log Loss: {m.get('logloss_x_binary',float('nan')):.4f}",f"- X top-1 precision: {m.get('x_top1_precision')}",f"- X top-1 recall: {m.get('draw_recall_when_x_top1')}",f"- X included top-2 recall: {m.get('x_top2_recall')}", "", "Calibration bins:"]
        lines.append("| Bin | n | mean P(X) | observed |")
        lines.append("|---|---:|---:|---:|")
        for b in m.get("calibration_bins",[]): lines.append(f"| {b['bin']} | {b['n']} | {b['mean_predicted']:.4f} | {b['observed_rate']:.4f} |")
        lines.append("")
    lines += ["## Caveats",""]+[f"- {item}" for item in report["limitations"]]
    (output_dir/"draw_diagnostic.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return report


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger",type=Path)
    parser.add_argument("--output-dir",type=Path,default=Path("draw-diagnostic"))
    parser.add_argument("--bins",type=int,default=10)
    args=parser.parse_args()
    if not 2<=args.bins<=50: parser.error("--bins must be between 2 and 50")
    report=run(args.ledger,args.output_dir,args.bins)
    print(json.dumps({"rows":report["rows"],"models":list(report["diagnostics"]),"outputs":[str(args.output_dir/"draw_diagnostic.md"),str(args.output_dir/"draw_diagnostic.json")]},indent=2))


if __name__=="__main__":
    main()
