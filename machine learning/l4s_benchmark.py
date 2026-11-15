"""CUDA benchmark on published Landslide4Sense splits (optical and terrain)."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import sys
import time

import h5py
import joblib
import numpy as np
import requests
from sklearn.metrics import precision_recall_curve

from gpu_train import tune
from model import summarize

REVISION = "4b291891badf301b5c75c2153f0f8fe00eeb1435"
REPO = "https://huggingface.co/datasets/ibm-nasa-geospatial/Landslide4sense"
SPLITS = {"train": (3799, 120), "validation": (245, 48), "test": (800, 80)}


def fetch(revision, split, kind, index):
    prefix, path = ("image", "images") if kind == "img" else ("mask", "annotations")
    for attempt in range(3):
        try:
            res = requests.get(f"{REPO}/resolve/{revision}/{path}/{split}/{prefix}_{index}.h5", timeout=(12, 45))
            res.raise_for_status()
            with h5py.File(io.BytesIO(res.content), "r") as f:
                return f[kind][()]
        except (OSError, requests.RequestException):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def chip(args):
    revision, split, index = args
    mask = fetch(revision, split, "mask", index)
    img = fetch(revision, split, "img", index)
    if img.shape != (128, 128, 14) or mask.shape != img.shape[:2] or not np.isin(mask, [0, 1]).all():
        raise ValueError(f"Unexpected image or mask schema in {split}/{index}")
    x = img.reshape(-1, 14).astype(np.float32)
    x[~np.isfinite(x)] = np.nan
    y = mask.reshape(-1)
    if split == "train":
        rng = np.random.default_rng(index)
        negative = np.flatnonzero(y == 0)
        keep = np.r_[np.flatnonzero(y == 1), rng.choice(negative, min(len(negative), 2048), replace=False)]
        return x[keep], y[keep]
    return x, y


def load(root, revision, split):
    total, count = SPLITS[split]
    indices = sorted(np.random.default_rng(4982).choice(np.arange(1, total + 1), count, replace=False).tolist())
    cache = root / f"{revision[:10]}-{split}.npz"
    if cache.exists():
        with np.load(cache) as f:
            return f["x"], f["y"], indices
    with ThreadPoolExecutor(max_workers=18) as pool:
        arrays = []
        for number, data in enumerate(pool.map(chip, ((revision, split, index) for index in indices)), 1):
            arrays.append(data)
            if number % 16 == 0 or number == count:
                print(f"{split}: {number}/{count} chips", file=sys.stderr, flush=True)
    x, y = map(np.concatenate, zip(*arrays))
    if np.unique(y).size < 2:
        raise ValueError(f"No positive labels in {split} subset")
    pending = cache.with_suffix(".partial.npz")
    np.savez(pending, x=x, y=y)
    pending.replace(cache)
    return x, y, indices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("--device", default="cuda:0", choices=("cuda:0", "cuda:1"))
    args = parser.parse_args()
    root = args.results_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    xt, yt, train = load(root, REVISION, "train")
    xv, yv, val = load(root, REVISION, "validation")
    model, vpred, tuning = tune(xt, yt, xv, yv, args.device, 12)
    precision, recall, thresholds = precision_recall_curve(yv, vpred)
    p, r = precision[:-1], recall[:-1]
    f1 = np.divide(2*p*r, p+r, out=np.zeros_like(p), where=p+r>0)
    threshold = float(thresholds[np.flatnonzero(f1 == f1.max())[-1]])
    # Load held-out test only after model and threshold selection.
    xe, ye, test = load(root, REVISION, "test")
    score = model.predict_proba(xe)[:,1]
    checkpoint = root / "sentinel2-terrain.joblib"
    joblib.dump({"model":model,"threshold":threshold,"dataset_revision":REVISION,"bands":14},checkpoint)
    report = {"dataset":REPO,"revision":REVISION,"input":"12 Sentinel-2 bands and ALOS slope/elevation",
              "device":args.device,"chip_ids":{"train":train,"validation":val,"test":test},
              "training_rows":len(yt), "threshold":threshold,
              "validation":summarize(yv,vpred,threshold), "test":summarize(ye,score,threshold),
              "tuning":tuning,"checkpoint":str(checkpoint)}
    (root / "metrics.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({"threshold":threshold,"validation":report["validation"],"test":report["test"],
                      "best_trial":tuning["best_trial"],"checkpoint":str(checkpoint)},indent=2))


if __name__ == "__main__":
    main()
