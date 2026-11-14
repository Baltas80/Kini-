from __future__ import annotations

import argparse
import json
import traceback
from collections import Counter

import numpy as np

from kini_engine.backtest import _calendar_day, _date_groups
from kini_engine.core import FeatureModel
from kini_engine.dataio import load_matches_csv, validate_matches


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose the first real walk-forward ML forecast.")
    parser.add_argument("csv")
    parser.add_argument("--min-train", type=int, default=300)
    args = parser.parse_args()

    matches = load_matches_csv(args.csv)
    validate_matches(matches)
    train = []
    target = None

    for group in _date_groups(matches):
        if len(train) < args.min_train:
            train.extend(group)
            continue
        target = group[0]
        break

    if target is None:
        raise SystemExit(f"No forecast date available after min_train={args.min_train}")

    labels = Counter(match.outcome() for match in train)
    feature_model = FeatureModel()
    feature_rows = [
        feature_model._features(train[:index], match)
        for index, match in enumerate(train)
        if match.home_goals is not None and match.away_goals is not None
    ]
    matrix = np.vstack(feature_rows) if feature_rows else np.empty((0, 0))
    report = {
        "n_matches": len(matches),
        "n_train": len(train),
        "n_train_labels": sum(labels.values()),
        "label_counts": dict(labels),
        "train_start_date": min(_calendar_day(match.date) for match in train),
        "train_end_date": max(_calendar_day(match.date) for match in train),
        "forecast_date": _calendar_day(target.date),
        "forecast_home": target.home,
        "forecast_away": target.away,
        "feature_shape": list(matrix.shape),
        "features_finite": bool(np.isfinite(matrix).all()) if matrix.size else False,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)

    try:
        probabilities = feature_model.fit_predict_proba(train, target)
    except Exception:
        traceback.print_exc()
        return 1

    if probabilities is None:
        print(
            "ML_DIAGNOSTIC_FAILED: FeatureModel returned None. "
            f"n_train={len(train)}, classes={sorted(labels)}",
            flush=True,
        )
        return 2

    result = {
        "probabilities": [float(value) for value in probabilities],
        "sum": float(np.sum(probabilities)),
        "finite": bool(np.isfinite(probabilities).all()),
        "non_negative": bool(np.all(np.asarray(probabilities) >= 0)),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)

    if not result["finite"] or not result["non_negative"] or not np.isclose(result["sum"], 1.0):
        print("ML_DIAGNOSTIC_FAILED: invalid probability vector", flush=True)
        return 3

    print("ML_DIAGNOSTIC_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
