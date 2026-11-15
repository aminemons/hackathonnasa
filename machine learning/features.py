"""Build a compact georeferenced landslide feature stack on native GUNW pixels."""

from contextlib import ExitStack
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.io import MemoryFile
from rasterio.shutil import copy
from rasterio.transform import Affine, rowcol
from rasterio.warp import Resampling, transform_bounds, transform_geom
from rasterio.vrt import WarpedVRT

from gunw import header, match_pilot, open_product, read_window

FEATURES = ("event_coherence", "control_coherence", "coherence_loss",
            "event_phase_gradient_rad_per_m", "control_phase_gradient_rad_per_m",
            "terrain_slope_deg")
LABEL = "reviewed_slope_failure"


def spatial_gradient(values, dx, dy, valid, components=None):
    clean = np.where(valid, values, np.nan)
    gx = (clean[1:-1, 2:] - clean[1:-1, :-2]) / (2 * dx)
    gy = (clean[2:, 1:-1] - clean[:-2, 1:-1]) / (2 * dy)
    result = np.hypot(gx, gy)
    result[~valid[1:-1, 1:-1]] = np.nan
    if components is not None:
        center = components[1:-1, 1:-1]
        same = (center == components[1:-1, 2:]) & (center == components[1:-1, :-2])
        same &= (center == components[2:, 1:-1]) & (center == components[:-2, 1:-1])
        result[~same] = np.nan
    return result


def label_array(path, crs, transform, shape):
    doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if doc.get("type") != "FeatureCollection" or "crs" in doc:
        raise ValueError("Labels require an RFC 7946 WGS84 GeoJSON FeatureCollection")
    geometries = {0: [], 1: []}
    for item in doc["features"]:
        value = item["properties"]["label"]
        geometry = item["geometry"]
        if type(value) is not int or value not in geometries or geometry["type"] not in ("Polygon", "MultiPolygon"):
            raise ValueError("Labels require Polygon or MultiPolygon features with integer label 0 or 1")
        geometries[value].append(transform_geom("EPSG:4326", crs, geometry))
    masks = [rasterize(geometries[i], out_shape=shape, transform=transform, dtype="uint8").astype(bool)
             if geometries[i] else np.zeros(shape, dtype=bool) for i in (0, 1)]
    if np.any(masks[0] & masks[1]):
        raise ValueError("Reviewed stable and slope failure polygons overlap on this grid")
    return np.where(masks[1], 1, np.where(masks[0], 0, np.nan)).astype(np.float32)


def validate_geometry(event, control):
    for key in ("track", "frame", "pass", "polarization", "epsg"):
        if event[key] != control[key]:
            raise ValueError(f"Event and control differ in {key}")
    e, c = (Affine(*pair["transform"]) for pair in (event, control))
    col, row = ~c * (e.c, e.f)
    if ((e.a, e.e) != (c.a, c.e) or not np.allclose([col, row], np.rint([col, row]), atol=1e-4, rtol=0)):
        raise ValueError("GUNW pairs need the same native spacing and aligned pixel centers")
    return e, round(col), round(row)


def build(event_file, control_file, dem_file, pilot, output, labels=None, label_source=None,
          geometry_mask=None, earthdata=False, max_pixels=2_000_000):
    if bool(labels) != bool(label_source and label_source.strip()):
        raise ValueError("Supply both reviewed labels and their independent source")
    with ExitStack() as stack:
        opened = [stack.enter_context(open_product(str(path), limit=128 * 1024 * 1024, earthdata=earthdata))
                  for path in (event_file, control_file)]
        products, streams = zip(*opened)
        pol = pilot.get("polarization", "HH")
        event, control = [header(product, pol) for product in products]
        transform, col_shift, row_shift = validate_geometry(event, control)
        baselines = match_pilot(pilot, event, control)
        crs = rasterio.crs.CRS.from_epsg(event["epsg"])
        left, bottom, right, top = transform_bounds("EPSG:4326", crs, *pilot["bbox"])
        y0, x0 = rowcol(transform, left, top)
        y1, x1 = rowcol(transform, right, bottom)
        y0, x0, y1, x1 = y0 - 1, x0 - 1, y1 + 2, x1 + 2
        h, w = y1 - y0, x1 - x0
        if h <= 2 or w <= 2 or h * w > max_pixels:
            raise ValueError("Choose a valid crop of at most two million pixels")
        windows = [(y0, y1, x0, x1), (y0 + row_shift, y1 + row_shift, x0 + col_shift, x1 + col_shift)]
        pairs = []
        for product, info, bounds in zip(products, (event, control), windows):
            a, b, c, d = bounds
            if not (0 <= a < b <= info["shape"][0] and 0 <= c < d <= info["shape"][1]):
                raise ValueError("The crop and its one-pixel halo must fit inside both GUNW grids")
            pairs.append(read_window(product, info, slice(a, b), slice(c, d)))
        dem_transform = transform * Affine.translation(x0, y0)
        dem = stack.enter_context(rasterio.open(dem_file))
        if dem.crs is None or dem.count != 1:
            raise ValueError("Supply a georeferenced single-band elevation model in meters")
        aligned = stack.enter_context(WarpedVRT(
            dem, crs=crs, transform=dem_transform, height=h, width=w, dtype="float32",
            nodata=np.nan, resampling=Resampling.bilinear,
        ))
        elevation = aligned.read(1)
        dx, dy = transform.a, -transform.e
        slope = np.degrees(np.arctan(spatial_gradient(elevation, dx, dy, np.isfinite(elevation))))
        gradients = [spatial_gradient(phase, dx, dy, good & (coh >= .25) & (components > 0), components)
                     for good, coh, phase, components in pairs]
        core = np.s_[1:-1, 1:-1]
        c_event, c_control = [pair[1][core] for pair in pairs]
        good = pairs[0][0][core] & pairs[1][0][core] & np.isfinite(slope)
        cropped = dem_transform * Affine.translation(1, 1)
        if geometry_mask:
            mask = stack.enter_context(rasterio.open(geometry_mask))
            if mask.crs is None or mask.count != 1:
                raise ValueError("Geometry mask must be a single georeferenced band")
            aligned_mask = stack.enter_context(WarpedVRT(
                mask, crs=crs, transform=cropped, height=h - 2, width=w - 2,
                dtype="float32", nodata=np.nan, resampling=Resampling.nearest,
            ))
            good &= aligned_mask.read(1) == 1
        if not np.any(good):
            raise ValueError("The crop has no common valid radar and terrain coverage")
        arrays = np.stack([c_event, c_control, c_control - c_event, *gradients, slope]).astype(np.float32)
        arrays[:, ~good] = np.nan
        names = FEATURES
        if labels:
            reviewed = label_array(labels, crs, cropped, good.shape)
            reviewed[~good] = np.nan
            arrays = np.concatenate([arrays, reviewed[None]])
            names = (*FEATURES, LABEL)
        tags = {
            "kind": "post_event_slope_failure_features", "occurred": pilot["occurred"],
            "event_granule": pilot.get("event_granule", ""), "control_granule": pilot.get("control_granule", ""),
            "baseline_days": json.dumps(baselines),
            "remote_bytes": json.dumps([stream.transferred if stream else 0 for stream in streams]),
            "pair_headers": json.dumps({"event": event, "control": control}, allow_nan=False),
            "terrain_geometry_mask": str(geometry_mask or "unavailable"),
            "label_source": label_source or "", "dem_source": str(dem_file),
        }
        write_cog(output, arrays, names, crs, cropped, tags)


def write_cog(path, arrays, names, crs, transform, tags):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", count=len(arrays), height=arrays.shape[1], width=arrays.shape[2],
                      dtype="float32", crs=crs, transform=transform, nodata=np.nan) as dst:
            dst.write(arrays.astype(np.float32, copy=False))
            dst.descriptions = names
            dst.update_tags(**tags)
        with mem.open() as src, tempfile.TemporaryDirectory(dir=path.parent) as temp:
            staged = Path(temp) / "raster.tif"
            copy(src, staged, driver="COG", compress="DEFLATE", overview_resampling="NEAREST")
            os.link(staged, path)
