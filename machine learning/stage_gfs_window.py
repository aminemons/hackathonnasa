"""Stage exactly one issued NOAA GFS 24-hour precipitation forecast for a storm."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import ceil, floor
from pathlib import Path
from urllib.request import Request, urlopen

import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import Window


HOST = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"


def retrieve(issue):
    date, cycle = issue.strftime("%Y%m%d"), issue.strftime("%H")
    product = f"{HOST}/gfs.{date}/{cycle}/atmos/gfs.t{cycle}z.pgrb2.0p25.f024"
    with urlopen(product + ".idx", timeout=15) as stream:
        records = stream.read(1_000_000).decode("ascii").splitlines()
    index = next(i for i, row in enumerate(records) if ":APCP:surface:0-1 day acc fcst:" in row)
    record = records[index]
    start = int(record.split(":")[1])
    end = int(records[index + 1].split(":")[1]) - 1
    request = Request(product, headers={"Range": f"bytes={start}-{end}"})
    with urlopen(request, timeout=20) as stream:
        if stream.status != 206:
            raise OSError("NOAA did not return a partial response")
        data = stream.read(end - start + 2)
    if len(data) != end - start + 1 or not data.startswith(b"GRIB") or not data.endswith(b"7777"):
        raise OSError("GFS GRIB response was incomplete")
    return product, record, data


def stage(issue, bounds, directory):
    url, record, grib = retrieve(issue)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "gfs_24h_precipitation.tif"
    with MemoryFile(grib) as memory, memory.open() as source:
        if source.count != 1 or source.crs is None:
            raise ValueError("GFS record did not contain one georeferenced band")
        tags = source.tags(1)
        if "APCP" not in tags.get("GRIB_ELEMENT", ""):
            raise ValueError("Unexpected nonprecipitation GRIB record")
        left, bottom, right, top = bounds
        raw = source.window(left, bottom, right, top)
        c0, r0 = floor(raw.col_off), floor(raw.row_off)
        c1, r1 = ceil(raw.col_off + raw.width), ceil(raw.row_off + raw.height)
        window = Window(c0, r0, c1 - c0, r1 - r0)
        if not (0 <= c0 < c1 <= source.width and 0 <= r0 < r1 <= source.height):
            raise ValueError("Bounds fall outside the GRIB grid")
        values = source.read(1, window=window)
        profile = {
            "driver": "GTiff", "dtype": values.dtype, "count": 1,
            "width": values.shape[1], "height": values.shape[0], "crs": source.crs,
            "transform": source.window_transform(window), "compress": "deflate",
        }
        with rasterio.open(path, "w", **profile) as target:
            target.write(values, 1)
            target.update_tags(1, **tags)
            target.set_band_unit(1, "mm")
    manifest = {
        "source": url, "index_entry": record, "initialized_at_utc": issue.isoformat(), "published_at_utc": None,
        "valid_from_utc": issue.isoformat(), "valid_to_utc": (issue + timedelta(hours=24)).isoformat(),
        "forecast_variable": "24-hour surface accumulated precipitation", "units": "mm",
        "bounds_requested": bounds, "rows": values.shape[0], "columns": values.shape[1],
        "max_cell_mm": float(values.max()), "grib_sha256": hashlib.sha256(grib).hexdigest(),
        "tiff_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (directory / "gfs_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("issue", help="a NOAA GFS run time, in yyyymmddHH UTC")
    parser.add_argument("output", type=Path)
    parser.add_argument("--bounds", type=float, nargs=4, required=True, help="west south east north")
    args = parser.parse_args()
    parsed = datetime.strptime(args.issue, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    stage(parsed, args.bounds, args.output)
