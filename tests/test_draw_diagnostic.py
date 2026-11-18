from scripts.analyze_draw_oos import metric_rows, wilson

def rows():
    return [
        {"actual_result":"X","model_probabilities":{"dc":{"1":.3,"X":.4,"2":.3}}},
        {"actual_result":"1","model_probabilities":{"dc":{"1":.5,"X":.2,"2":.3}}},
        {"actual_result":"2","model_probabilities":{"dc":{"1":.3,"X":.25,"2":.45}}},
        {"actual_result":"X","model_probabilities":{"dc":{"1":.4,"X":.35,"2":.25}}},
    ]

def test_draw_metrics_top1_top2_and_binary_scores():
    m=metric_rows(rows(),"dc",4)
    assert m["n"]==4
    assert m["x_top1_n"]==1
    assert m["x_top1_hits"]==1
    assert m["x_top1_precision"]==1
    assert m["draw_recall_when_x_top1"]==.5
    assert m["x_in_top2_n"]==2
    assert m["x_top2_hits"]==2
    assert m["x_top2_recall"]==1
    assert m["brier_x_binary"]>=0
    assert m["logloss_x_binary"]>=0
    assert len(m["calibration_bins"])>0

def test_wilson_handles_empty_and_nonempty():
    assert wilson(0,0) is None
    lo,hi=wilson(5,10)
    assert lo<.5<hi
