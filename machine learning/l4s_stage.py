"""Stage reproducibly sampled full Landslide4Sense tiles for spatial training."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import sys
from threading import local
import time

import h5py
import numpy as np
import requests

BASE = "https://huggingface.co/datasets/ibm-nasa-geospatial/Landslide4sense"
worker = local()


def read(revision, split, index, band):
    if not hasattr(worker, "session"):
        worker.session = requests.Session()
    kind, prefix, key = ("images", "image", "img") if band else ("annotations", "mask", "mask")
    url = f"{BASE}/resolve/{revision}/{kind}/{split}/{prefix}_{index}.h5"
    for attempt in range(4):
        try:
            response = worker.session.get(url, timeout=(12, 28))
            response.raise_for_status()
            with h5py.File(io.BytesIO(response.content), "r") as handle:
                return handle[key][()]
        except (OSError, requests.RequestException):
            if attempt == 3:
                raise
            time.sleep(1 + attempt)


def stage(spec):
    root, revision, split, index = spec
    path = root / split / f"{index}.npz"
    if path.exists():
        return
    x = read(revision, split, index, True)
    y = read(revision, split, index, False)
    if x.shape != (128, 128, 14) or y.shape != x.shape[:2] or not np.isin(y, [0, 1]).all():
        raise ValueError(f"Invalid published tile {split}/{index}")
    temp = path.with_suffix(".tmp")
    with temp.open("wb") as handle:
        np.savez(handle, x=x.astype(np.float32), y=y.astype(np.uint8))
    temp.replace(path)


def main():
    baseline, root, count = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    metadata = json.loads(baseline.read_text())
    revision = metadata["revision"]
    groups = {key: metadata["chip_ids"][key] for key in ("validation", "test")}
    seeded = np.random.default_rng(87954)
    original = metadata["chip_ids"]["train"]
    extra = seeded.choice(np.setdiff1d(np.arange(1, 3800), original), count - len(original), replace=False).tolist()
    groups["train"] = sorted(original + extra)
    jobs = []
    for split, ids in groups.items():
        (root / split).mkdir(parents=True, exist_ok=True)
        jobs.extend((root, revision, split, index) for index in ids)
    for attempt in range(2):
        failures = []
        with ThreadPoolExecutor(max_workers=36) as pool:
            from concurrent.futures import as_completed

            tasks = {pool.submit(stage, job): job for job in jobs}
            for i, task in enumerate(as_completed(tasks), 1):
                try:
                    task.result()
                except Exception as problem:
                    print(repr(problem), flush=True)
                    failures.append(tasks[task])
                if i % 32 == 0 or i == len(tasks):
                    print(f"Staged {i - len(failures)}/{len(tasks)} on pass {attempt + 1}", flush=True)
        if not failures:
            break
        jobs = failures
    if failures:
        raise RuntimeError(f"{len(failures)} dataset items failed to stage")
    (root / "manifest.json").write_text(json.dumps({"revision": revision, "chip_ids": groups}, indent=2) + "\n")


if __name__ == "__main__":
    main()
