"""Train and apply a slope failure candidate model when reviewed labels are available."""

import json
import os
from pathlib import Path
import tempfile

import joblib
import numpy as np
import rasterio
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, precision_recall_curve, precision_recall_fscore_support

from features import FEATURES, LABEL, write_cog
from gunw import timestamp

SCHEMA_VERSION = 1


def read_stack(path, labeled=False):
    with rasterio.open(path) as src:
        tags = src.tags()
        expected = (*FEATURES, LABEL) if labeled else FEATURES
        if tags.get("kind") != "post_event_slope_failure_features" or src.descriptions[:len(expected)] != expected:
            raise ValueError(f"Unexpected feature schema in {path}")
        if labeled and not tags.get("label_source"):
            raise ValueError(f"Missing independent label source in {path}")
        if src.crs is None:
            raise ValueError(f"Missing feature CRS in {path}")
        data = src.read(masked=True).filled(np.nan)
        return data, tags, src.crs, src.transform


def summarize(labels, scores, threshold):
    active = scores >= threshold
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, active, average="binary", zero_division=0)
    return {"reviewed_pixels": len(labels), "positive_pixels": int(labels.sum()),
            "average_precision": float(average_precision_score(labels, scores)),
            "precision": precision, "recall": recall, "f1": f1}


def collect(manifest):
    path = Path(manifest)
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    data = {"train": [], "validation": [], "test": []}
    seen = set()
    assigned = {}
    for row in rows:
        src = (path.parent / row["stack"]).resolve()
        split, event, site = (row[key].strip() for key in ("split", "event", "site"))
        if src in seen or split not in data or not event or not site:
            raise ValueError(f"Duplicate stack or invalid split, event or site in {row}")
        seen.add(src)
        stack, tags, _, _ = read_stack(src, labeled=True)
        for key in ("event_granule", "control_granule"):
            if not tags.get(key):
                raise ValueError(f"Missing {key} in {src}")
        actual = json.loads(tags["pair_headers"])
        acquisitions = set()
        for pair in actual.values():
            for time in ("reference", "secondary"):
                acquisitions.add((int(pair["track"]), pair["pass"].upper(), timestamp(pair[time])))
        groups = [("event", event), ("site", site),
                  ("granule", tags["event_granule"]), ("granule", tags["control_granule"]),
                  *(("acquisition", key) for key in acquisitions)]
        for group in groups:
            if assigned.setdefault(group, split) != split:
                raise ValueError(f"{group} crosses splits")
        labels = stack[len(FEATURES)]
        if np.any(np.isfinite(labels) & (labels != 0) & (labels != 1)):
            raise ValueError(f"Unsupported reviewed label in {src}")
        selected = np.isfinite(labels)
        if not selected.any():
            raise ValueError(f"No reviewed pixels remain in {src}")
        data[split].append((stack[:len(FEATURES), selected].T, labels[selected].astype(np.uint8)))
    combined = {}
    for key, values in data.items():
        if not values:
            raise ValueError(f"Missing independent {key} observations")
        features, labels = (np.concatenate(parts) for parts in zip(*values))
        if np.unique(labels).size != 2:
            raise ValueError(f"{key} needs independently reviewed positives and negatives")
        combined[key] = features, labels
    return combined


def train(manifest, output, gpu=None, trials=48):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    data = collect(manifest)
    x_train, y_train = data["train"]
    x_val, y_val = data["validation"]
    tuning = None
    if gpu:
        from gpu_train import tune
        model, val, tuning = tune(x_train, y_train, x_val, y_val, gpu, trials)
    else:
        model = HistGradientBoostingClassifier(
            max_iter=180, max_leaf_nodes=15, min_samples_leaf=30,
            class_weight="balanced", random_state=42, early_stopping=False,
        )
        model.fit(x_train, y_train)
        val = model.predict_proba(x_val)[:, 1]
    precision, recall, thresholds = precision_recall_curve(y_val, val)
    total = precision[:-1] + recall[:-1]
    f1 = np.divide(2 * precision[:-1] * recall[:-1], total,
                   out=np.zeros_like(total), where=total > 0)
    threshold = float(thresholds[np.flatnonzero(f1 == f1.max())[-1]])
    x_test, y_test = data["test"]
    report = {
        "threshold_selected_on_validation": threshold,
        "validation": summarize(y_val, val, threshold),
        "held_out_test": summarize(y_test, model.predict_proba(x_test)[:, 1], threshold),
        "test_coherence_loss_average_precision": float(average_precision_score(y_test, x_test[:, 2])),
    }
    if tuning:
        report["gpu_tuning"] = tuning
    artifact = {"version": SCHEMA_VERSION, "sklearn": sklearn.__version__, "features": FEATURES,
                "model": model, "threshold": threshold, "metrics": report}
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        pending = Path(temp) / "model.joblib"
        joblib.dump(artifact, pending, compress=3)
        os.link(pending, output)
    return report


def predict(stack, model_file, output):
    artifact = joblib.load(model_file)
    if (artifact["version"], artifact["features"], artifact["sklearn"]) != (
            SCHEMA_VERSION, FEATURES, sklearn.__version__):
        raise ValueError("Feature or scikit-learn version differs from the trained artifact")
    data, tags, crs, transform = read_stack(stack)
    valid = np.isfinite(data[[0, 1, 2, 5]]).all(axis=0)
    if not valid.any():
        raise ValueError("Feature stack has no valid prediction pixels")
    score = np.full(valid.shape, np.nan, dtype=np.float32)
    score[valid] = artifact["model"].predict_proba(data[:len(FEATURES), valid].T)[:, 1]
    threshold = artifact["threshold"]
    candidate = np.where(valid, score >= threshold, np.nan)
    tags.update(kind="post_event_slope_failure_candidates", score="uncalibrated_classifier_score",
                threshold=str(threshold), model=Path(model_file).name,
                valid_fraction=str(float(valid.mean())))
    write_cog(output, np.stack([score, candidate]), ("candidate_score", "candidate_mask"),
              crs, transform, tags)
