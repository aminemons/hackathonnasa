"""Export the trained trees and a test example for dependency-free inference."""
import gzip
import json
from pathlib import Path
import sys

import joblib
import numpy as np
from scipy.special import expit

source, target = map(Path, sys.argv[1:])
target.mkdir(parents=True, exist_ok=True)
metrics = json.loads((source / "metrics.json").read_text())
checkpoint = joblib.load(source / "sentinel2-terrain.joblib")
estimator = checkpoint["model"]
booster = estimator.get_booster()
learner = json.loads(booster.save_raw(raw_format="json"))["learner"]
objective = learner["objective"]["name"]
if objective != "binary:logistic":
    raise ValueError(f"Unexpected objective {objective}")

base = float(np.asarray(json.loads(learner["learner_model_param"]["base_score"]), dtype=np.float32).item())
trees = [
    [tree[field] for field in (
        "left_children", "right_children", "split_indices", "split_conditions", "default_left"
    )]
    for tree in learner["gradient_booster"]["model"]["trees"]
]
if len(trees) != booster.num_boosted_rounds():
    raise ValueError("Unexpected tree grouping")
model = {
    "base_margin": float(np.float32(np.log(base / (1 - base)))),
    "trees": trees,
    "card": {
        "model": "TerraPulse Sentinel-2 + Terrain",
        "revision": metrics["revision"],
        "source": metrics["dataset"],
        "input": metrics["input"],
        "bands": ["B01","B02","B03","B04","B05","B06","B07","B08","B09","B10","B11","B12","slope","elevation"],
        "threshold": metrics["threshold"],
        "test": metrics["test"],
        "chips": {split: len(ids) for split, ids in metrics["chip_ids"].items()},
    },
}
with gzip.open(target / "landslide_model.json.gz", "wt") as out:
    json.dump(model, out, separators=(",", ":"))

with np.load(source / f'{metrics["revision"][:10]}-test.npz') as arrays:
    patches = arrays["x"].reshape(-1, 128, 128, 14)
    masks = arrays["y"].reshape(-1, 128, 128)
    index = next(i for i, mask in enumerate(masks) if 100 <= mask.sum() <= 1000)
    patch = np.asarray(patches[index], dtype=np.float32)
    rows = patch.reshape(-1, 14)
    scores = estimator.predict_proba(rows)[:, 1]
    selected = np.random.default_rng(41).choice(rows.shape[0], 512, replace=False)
    margin = np.full(len(selected), model["base_margin"], dtype=np.float32)
    for left, right, features, splits, default in trees:
        splits = np.asarray(splits, dtype=np.float32)
        for i, row in enumerate(rows[selected]):
            node = 0
            while left[node] != -1:
                value = row[features[node]]
                goes_left = bool(default[node]) if np.isnan(value) else value < splits[node]
                node = left[node] if goes_left else right[node]
            margin[i] += splits[node]
    np.testing.assert_allclose(expit(margin), scores[selected], atol=3e-7, rtol=1e-6)
    rgb = patch[:, :, [3, 2, 1]]
    low, high = np.nanpercentile(rgb, [2, 98], axis=(0, 1))
    rgb = np.nan_to_num(np.clip((rgb - low) / np.maximum(high - low, 1e-6), 0, 1))
    fixture = {
        "id": f'Landslide4Sense test chip {metrics["chip_ids"]["test"][index]}',
        "width": 128, "height": 128,
        "rows": [[float(value) if np.isfinite(value) else None for value in row] for row in rows],
        "rgb": np.rint(rgb.reshape(-1) * 255).astype(np.uint8).tolist(),
        "labels": masks[index].reshape(-1).astype(int).tolist(),
        "parity": [[int(i), float(scores[i])] for i in selected],
    }
with gzip.open(target / "landslide_example.json.gz", "wt") as out:
    json.dump(fixture, out, separators=(",", ":"), allow_nan=False)
print(f'{fixture["id"]}; reference candidates: {(scores >= metrics["threshold"]).sum()}; labels: {sum(fixture["labels"])}; parity verified on {len(selected)} pixels')
