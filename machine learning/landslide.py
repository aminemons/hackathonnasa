"""TerraPulse offline slope failure backend."""

import argparse
import json
from pathlib import Path

import requests

from catalog import pilot_metadata
from gunw import header, open_product


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="Check CMR metadata only")
    catalog.add_argument("pilot")
    inspect = commands.add_parser("inspect", help="Inspect a local or ASF HDF5 header")
    inspect.add_argument("source")
    inspect.add_argument("--polarization", choices=("HH", "VV"), default="HH")
    inspect.add_argument("--earthdata", action="store_true", help="Authenticate using Earthdata .netrc")
    prepare = commands.add_parser("prepare", help="Build a native-grid feature crop from local or bounded ASF data")
    for option in ("pilot", "event", "control", "dem", "output"):
        prepare.add_argument(f"--{option}", required=True)
    for option in ("labels", "label-source", "geometry-mask"):
        prepare.add_argument(f"--{option}")
    prepare.add_argument("--earthdata", action="store_true", help="Authenticate using Earthdata .netrc")
    train = commands.add_parser("train", help="Fit a model on three disjoint reviewed splits")
    train.add_argument("manifest")
    train.add_argument("output")
    train.add_argument("--gpu", choices=("cuda", "cuda:0", "cuda:1"),
                       help="Tune XGBoost using the selected CUDA device")
    train.add_argument("--trials", type=int, default=48, help="Number of CUDA tuning trials")
    predict = commands.add_parser("predict", help="Export a candidate score and candidate mask")
    for option in ("stack", "model", "output"):
        predict.add_argument(option)

    args = parser.parse_args()
    try:
        result = run(args)
    except (ValueError, OSError, KeyError, TypeError, requests.RequestException) as error:
        if isinstance(error, requests.RequestException):
            error = f"Network request failed ({type(error).__name__}). Check connectivity and Earthdata access."
        parser.exit(1, f"Error: {error}\n")
    if result is not None:
        print(json.dumps(result, indent=2, allow_nan=False))


def run(args):
    if args.command in ("catalog", "prepare"):
        pilot = json.loads(Path(args.pilot).read_text(encoding="utf-8-sig"))
    if args.command == "catalog":
        return pilot_metadata(pilot)
    if args.command == "inspect":
        with open_product(args.source, earthdata=args.earthdata) as (product, stream):
            info = header(product, args.polarization)
            if stream:
                info["http_bytes_transferred"] = stream.transferred
                info["hdf5_content_length"] = stream.size
            return info
    if args.command == "prepare":
        from features import build
        return build(args.event, args.control, args.dem, pilot, args.output,
                     labels=args.labels, label_source=args.label_source, geometry_mask=args.geometry_mask,
                     earthdata=args.earthdata)
    import model
    if args.command == "train":
        return model.train(args.manifest, args.output, gpu=args.gpu, trials=args.trials)
    return model.predict(args.stack, args.model, args.output)


if __name__ == "__main__":
    main()
