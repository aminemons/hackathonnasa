"""Validation-only hyperparameter tuning for GPU histogram boosting."""

import json
import sys

import numpy as np
from sklearn.metrics import average_precision_score


def tune(x_train, y_train, x_val, y_val, device, trials):
    if trials < 1:
        raise ValueError("Use at least one CUDA trial")
    try:
        from xgboost import XGBClassifier, build_info, __version__
        from xgboost.callback import EarlyStopping
    except ImportError as error:
        raise ValueError("Install the CUDA-enabled xgboost package in the training environment") from error
    if not build_info().get("USE_CUDA"):
        raise ValueError("The installed XGBoost build does not support CUDA")

    rng = np.random.default_rng(42)
    imbalance = float((y_train == 0).sum() / y_train.sum())
    best = None
    log = []
    for trial in range(trials):
        params = {
            "max_depth": int(rng.integers(2, 9)),
            "min_child_weight": float(np.exp(rng.uniform(np.log(2), np.log(64)))),
            "learning_rate": float(np.exp(rng.uniform(np.log(.015), np.log(.15)))),
            "subsample": float(rng.uniform(.65, 1)),
            "colsample_bytree": float(rng.uniform(.75, 1)),
            "reg_lambda": float(np.exp(rng.uniform(np.log(.5), np.log(40)))),
            "reg_alpha": float(np.exp(rng.uniform(np.log(.001), np.log(4)))),
            "scale_pos_weight": float(max(1., imbalance) ** rng.uniform(0, 1)),
        }
        if trial == 0:
            params.update(max_depth=4, min_child_weight=10, learning_rate=.045, subsample=.85,
                          colsample_bytree=1., reg_lambda=4., reg_alpha=.1,
                          scale_pos_weight=max(1., imbalance) ** .5)
        callback = EarlyStopping(rounds=100, metric_name="aucpr", data_name="validation_0",
                                 maximize=True, save_best=True)
        estimator = XGBClassifier(device=device, tree_method="hist", max_bin=256,
                                  n_estimators=2400, eval_metric="aucpr", n_jobs=4,
                                  random_state=42, callbacks=[callback], **params)
        estimator.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
        booster = estimator.get_booster()
        actual_device = json.loads(booster.save_config())["learner"]["generic_param"]["device"]
        if not actual_device.startswith("cuda"):
            raise ValueError("XGBoost fell back to CPU. Check CUDA visibility and driver compatibility.")
        estimator.set_params(device="cpu", callbacks=None)
        validation_scores = estimator.predict_proba(x_val)[:, 1]
        ap = float(average_precision_score(y_val, validation_scores))
        result = {"trial": trial + 1, "validation_ap": ap,
                  "trees": booster.num_boosted_rounds(), "params": params}
        log.append(result)
        print(f"CUDA trial {trial + 1}/{trials} | validation AP {ap:.5f} | {result['trees']} trees",
              file=sys.stderr, flush=True)
        if best is None or ap > best[0]:
            best = ap, estimator, validation_scores, trial + 1
    _, winner, predictions, best_trial = best
    return winner, predictions, {"device": device, "xgboost": __version__,
                                 "best_trial": best_trial, "trials": log}
