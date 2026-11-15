"""Train a Sentinel-1 landslide candidate model on disjoint Sen12Landslides inventories."""

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import io
import json
from pathlib import Path
import tarfile

import h5py
import joblib
import numpy as np
import requests
from sklearn.metrics import average_precision_score, precision_recall_curve
from scipy.ndimage import uniform_filter

from gpu_train import tune
from model import summarize

URL = "https://huggingface.co/datasets/paulhoehn/Sen12Landslides"
REVISION = "311f426d0e2fa9b532772fbee0641e2f9db6da00"
REGIONS = {
    "chimanimani": ("train", (1, 2)),
    "dominicadavid": ("train", (3,)),
    "dominicamaria": ("train", (3,)),
    "itogon": ("train", (11,)),
    "italy": ("validation", (6, 7, 8, 9, 10)),
    "hiroshima": ("test", (3, 4)),
}
FEATURES = ("pre_vv_db", "post_vv_db", "delta_vv_db", "pre_vh_db", "post_vh_db",
            "delta_vh_db", "slope_deg")
CONTEXT_FEATURES = tuple(f"{band}_{stat}" for band in ("vv", "vh")
                         for stat in ("median_change_db", "before_spread_db", "after_spread_db",
                                      "neighbor_change_db"))


def read_chip(payload, context):
    with h5py.File(io.BytesIO(payload), "r") as chip:
        dates = chip.attrs["event_date"].decode().split(",")
        if len(dates) != 1 or not dates[0]:
            return None
        if any(float(value) < .99 for value in chip.attrs["date_confidence"].decode().split(",")):
            return None
        endpoints = ast.literal_eval(chip.attrs["pre_post_dates"].decode())
        before, after = endpoints["pre"], endpoints["post"]
        if not 0 <= before < after < len(chip["time"]):
            return None
        origin = date.fromisoformat(chip["time"].attrs["units"].decode().split()[-1][:10])
        offsets = chip["time"][[before, after]]
        event = date.fromisoformat(dates[0])
        first, second = [origin + timedelta(days=int(offset)) for offset in offsets]
        if not first < event <= second or (second - first).days > 60:
            return None
        bands = []
        context_bands = []
        for key in ("VV", "VH"):
            pre, post = chip[key][[before, after]]
            bands.extend([pre, post, post - pre])
            if context:
                pre_stack = chip[key][max(0, before - 2):before + 1]
                post_stack = chip[key][after:min(after + 3, len(chip["time"]))]
                prior = np.median(pre_stack, axis=0)
                later = np.median(post_stack, axis=0)
                change = later - prior
                present = np.isfinite(change)
                weights = uniform_filter(present.astype(np.float32), size=5)
                local_sum = uniform_filter(np.where(present, change, 0), size=5)
                local = np.divide(local_sum, weights, where=weights > 0,
                                  out=np.full_like(local_sum, np.nan))
                context_bands.extend([change, np.std(pre_stack, axis=0),
                                      np.std(post_stack, axis=0), local])
        dem = chip["DEM"][0].astype(np.float32)
        spacing = abs(float(chip["x"][1] - chip["x"][0]))
        dy, dx = np.gradient(dem, spacing)
        bands.append(np.degrees(np.arctan(np.hypot(dx,dy))))
        features = np.stack(bands + context_bands, axis=-1)
        target = chip["MASK"][after]
        valid = np.isfinite(features[..., :len(FEATURES)]).all(axis=-1) & (dem > -9999) & np.isin(target,[0,1])
        if not np.any(valid & (target == 1)):
            return None
        return features[valid], target[valid], [first.isoformat(), second.isoformat()]


def ingest(part, limit, context):
    base = f"{URL}/resolve/{REVISION}/data_harmonized/s1asc/s1asc"
    results = []
    counts = {}
    with requests.get(f"{base}_part{part:02}.tar.gz", stream=True, timeout=(15, 40)) as response:
        response.raise_for_status()
        with tarfile.open(fileobj=response.raw, mode="r|gz") as archive:
            for entry_index, member in enumerate(archive):
                if entry_index >= 300:
                    break
                name = Path(member.name).name
                region = name.split("_s1asc_")[0]
                if (not member.isfile() or region not in REGIONS or part not in REGIONS[region][1]
                    or counts.get(region,0) >= limit):
                    continue
                record = read_chip(archive.extractfile(member).read(), context)
                if record is None:
                    continue
                x, y, dates = record
                split = REGIONS[region][0]
                if split == "train":
                    rng = np.random.default_rng(int(name.rsplit("_", 1)[-1].split(".")[0]))
                    negatives = np.flatnonzero(y == 0)
                    sel = np.r_[np.flatnonzero(y == 1), rng.choice(negatives,min(2000,len(negatives)),replace=False)]
                    x, y = x[sel], y[sel]
                results.append((split, name, x, y, dates))
                counts[region] = counts.get(region,0) + 1
                if sum(counts.values()) >= limit:
                    break
    print(f"Archive {part:02d} accepted {counts}",flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--trials",type=int,default=24)
    parser.add_argument("--device",choices=("cuda:0","cuda:1"),default="cuda:0")
    parser.add_argument("--context", action="store_true", help="Add multi-date and neighborhood radar features")
    args = parser.parse_args()
    feature_names = (*FEATURES, *CONTEXT_FEATURES) if args.context else FEATURES
    args.output.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for group in pool.map(lambda part: ingest(part,24,args.context),(1,2,3,4,6,7,8,9,10,11)) for r in group]
    data = {}
    provenance = {}
    for split in ("train","validation","test"):
        selected = [(name,x,y,dates) for group,name,x,y,dates in rows if group == split]
        if not selected:
            raise ValueError(f"No valid acquisitions for {split}")
        data[split] = tuple(np.concatenate(items) for items in zip(*[(x,y) for _,x,y,_ in selected]))
        provenance[split] = [{"chip":name,"dates":dates} for name,_,_,dates in selected]
        if np.unique(data[split][1]).size != 2:
            raise ValueError(f"{split} lacks one label class")
    print({k:len(v) for k,v in provenance.items()},flush=True)
    xt,yt = data["train"]
    xv,yv = data["validation"]
    estimator, scores, tuning = tune(xt,yt,xv,yv,args.device,args.trials)
    precision,recall,thresholds = precision_recall_curve(yv,scores)
    denominator = precision[:-1]+recall[:-1]
    f1 = np.divide(2*precision[:-1]*recall[:-1],denominator,out=np.zeros_like(denominator),where=denominator>0)
    threshold = float(thresholds[np.flatnonzero(f1 == f1.max())[-1]])
    xe,ye = data["test"]
    test_score = estimator.predict_proba(xe)[:,1]
    report = {
        "source": URL, "revision": REVISION, "sensor": "Sentinel-1 C-band ascending",
        "experiment": "event-aligned chips with entire inventories held out",
        "feature_names": feature_names, "chips": provenance, "threshold":threshold, "tuning":tuning,
        "validation":summarize(yv,scores,threshold), "test":summarize(ye,test_score,threshold),
        "test_absolute_vv_change_average_precision":float(average_precision_score(ye,np.abs(xe[:,2]))),
    }
    joblib.dump({"model":estimator,"threshold":threshold,"features":feature_names,"sensor":"Sentinel-1 C-band",
                 "dataset":URL,"revision":REVISION},args.output/"sentinel1-landslide.joblib")
    (args.output/"metrics.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:report[k] for k in ("validation","test","test_absolute_vv_change_average_precision")}),flush=True)


if __name__ == "__main__":
    main()
