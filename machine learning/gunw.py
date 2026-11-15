"""Read the NISAR L-SAR GUNW header and safe windows on the native grid."""

from contextlib import contextmanager
from datetime import datetime, timezone
import io
import os
from urllib.parse import urlsplit

import h5py
import numpy as np
import requests
from rasterio.crs import CRS
from rasterio.transform import Affine

IDENT = "/science/LSAR/identification"
FREQUENCY = "/science/LSAR/GUNW/grids/frequencyA"
METADATA = {
    "track": "trackNumber", "frame": "frameNumber", "pass": "orbitPassDirection",
    "reference": "referenceZeroDopplerStartTime", "secondary": "secondaryZeroDopplerStartTime",
}
LAYERS = ("coherenceMagnitude", "unwrappedPhase", "connectedComponents")


def text(value):
    if isinstance(value, bytes):
        return value.decode().strip()
    return str(value).strip()


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Acquisition and event dates must include a timezone")
    return result


def temporal_check(event, control, occurred):
    event_times = sorted(timestamp(event[k]) for k in ("reference", "secondary"))
    control_times = sorted(timestamp(control[k]) for k in ("reference", "secondary"))
    if (not control_times[0] < control_times[1] < occurred
            or not event_times[0] < occurred < event_times[1]
            or abs((control_times[1] - event_times[0]).total_seconds()) >= 1):
        raise ValueError("Use a pre-event control sharing the event pair's earlier acquisition")
    return {"event": (event_times[1] - event_times[0]).total_seconds() / 86400,
            "control": (control_times[1] - control_times[0]).total_seconds() / 86400}


def match_pilot(pilot, event, control):
    baselines = temporal_check(event, control, timestamp(pilot["occurred"]))
    for name, pair in (("event", event), ("control", control)):
        for key in ("track", "frame", "pass", "polarization"):
            if key in pilot and str(pair[key]).upper() != str(pilot[key]).upper():
                raise ValueError(f"{name} pair does not match pilot {key}")
        if f"{name}_acquisitions" in pilot:
            expected = sorted(timestamp(value) for value in pilot[f"{name}_acquisitions"])
            actual = sorted(timestamp(pair[key]) for key in ("reference", "secondary"))
            if len(expected) != 2 or any(abs((a - e).total_seconds()) >= 1
                                         for a, e in zip(actual, expected)):
                raise ValueError(f"{name} pair does not match the pilot acquisitions")
    return baselines


class RangeFile(io.RawIOBase):
    """Supply h5py with small, bounded HTTPS byte ranges. Never accept a full body."""

    def __init__(self, url, limit=16 * 1024 * 1024, earthdata=False):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "nisar.asf.earthdatacloud.nasa.gov":
            raise ValueError("Remote headers require an HTTPS NISAR ASF product URL")
        if earthdata:
            import earthaccess
            if not earthaccess.login(strategy="netrc").authenticated:
                raise ValueError("No Earthdata Login credentials found in .netrc")
            self.session = earthaccess.get_requests_https_session()
        else:
            self.session = requests.Session()
            token = os.environ.get("EARTHDATA_TOKEN")
            if token:
                self.session.headers["Authorization"] = f"Bearer {token}"
        self.url = url
        self.limit = limit
        self.transferred = 0
        self.position = 0
        try:
            with self.session.head(url, allow_redirects=True, timeout=30) as response:
                self.size = int(response.headers.get("Content-Length", 0))
                if response.status_code != 200 or self.size <= limit:
                    raise ValueError("ASF did not report an HDF5 product larger than the header budget")
        except Exception:
            self.session.close()
            raise

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.size}[whence]
        if base + offset < 0:
            raise ValueError("Negative HDF5 offset")
        self.position = base + offset
        return self.position

    def readinto(self, buffer):
        count = min(len(buffer), max(0, self.size - self.position))
        if count == 0:
            return 0
        if self.transferred + count > self.limit:
            raise ValueError("HDF5 metadata exceeded the byte budget")
        end = self.position + count - 1
        expected = f"bytes {self.position}-{end}/{self.size}"
        headers = {"Range": f"bytes={self.position}-{end}", "Accept-Encoding": "identity"}
        with self.session.get(self.url, headers=headers, stream=True, timeout=30) as response:
            if response.status_code in (401, 403):
                raise ValueError("ASF requires Earthdata authentication for this granule")
            if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                raise ValueError(f"ASF did not honor the HDF5 byte range (HTTP {response.status_code})")
            payload = response.raw.read(count)
            if len(payload) != count:
                raise ValueError("Truncated HDF5 byte range")
        buffer[:count] = payload
        self.position += count
        self.transferred += count
        return count

    def close(self):
        self.session.close()
        super().close()


@contextmanager
def open_product(source, limit=16 * 1024 * 1024, earthdata=False):
    if source.startswith("https://"):
        with RangeFile(source, limit=limit, earthdata=earthdata) as stream, h5py.File(stream, "r") as handle:
            yield handle, stream
    else:
        with h5py.File(source, "r") as handle:
            yield handle, None


def header(handle, polarization):
    identity = handle[IDENT]
    if text(identity["productType"][()]) != "GUNW":
        raise ValueError("Expected a NISAR L-SAR GUNW product")
    group = handle[f"{FREQUENCY}/unwrappedInterferogram"]
    pol = group[polarization]

    def coord(name):
        return pol[name] if name in pol else group[name]

    mask = group["mask"]
    shape = pol["coherenceMagnitude"].shape
    if len(shape) != 2 or any(pol[key].shape != shape for key in LAYERS) or mask.shape != shape:
        raise ValueError("Phase, coherence, components and mask must share one 2-D grid")
    x, y = coord("xCoordinates"), coord("yCoordinates")
    if x.shape != (shape[1],) or y.shape != (shape[0],):
        raise ValueError("Coordinate lengths do not match GUNW raster dimensions")
    dx, dy = (float(coord(f"{a}CoordinateSpacing")[()]) for a in "xy")
    if not dx > 0 > dy:
        raise ValueError("Expected a north-up GUNW grid")
    x0, y0 = float(x[0]), float(y[0])
    if not np.allclose([x[-1], y[-1]], [x0 + dx * (shape[1] - 1), y0 + dy * (shape[0] - 1)],
                       atol=0.01, rtol=0):
        raise ValueError("GUNW grid endpoints disagree with coordinate spacing")
    for layer, accepted in (("coherenceMagnitude", ("1", "unitless", "dimensionless")),
                            ("unwrappedPhase", ("rad", "radian", "radians"))):
        if text(pol[layer].attrs.get("units", "")).lower() not in accepted:
            raise ValueError(f"Unexpected unit for {pol[layer].name}")
    if mask.dtype.kind != "u" or mask.dtype.itemsize not in (1, 4):
        raise ValueError("Expected the NISAR uint8 or uint32 mask encoding")
    frequency = float(handle[f"{FREQUENCY}/centerFrequency"][()])
    if not 1e9 < frequency < 2e9:
        raise ValueError("Expected a NISAR L-band center frequency in Hz")
    epsg = int(coord("projection")[()])
    crs = CRS.from_epsg(epsg)
    if not crs.is_projected or crs.linear_units_factor[1] != 1:
        raise ValueError("Expected a projected grid in meters")
    layers = {key: pol[key] for key in LAYERS}
    layers["mask"] = mask
    if "validDataMask" in pol:
        layers["validDataMask"] = pol["validDataMask"]
        if layers["validDataMask"].shape != shape:
            raise ValueError("Polarization validity mask does not match the GUNW grid")
    metadata = {key: text(identity[path][()]) for key, path in METADATA.items()}
    # GUNW identifies these zero-Doppler times as UTC even without a zone suffix.
    for key in ("reference", "secondary"):
        value = datetime.fromisoformat(metadata[key].replace("Z", "+00:00"))
        metadata[key] = (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    return {
        **metadata,
        "polarization": polarization, "center_frequency_hz": frequency,
        "epsg": epsg, "shape": list(shape),
        "transform": list(Affine(dx, 0, x0 - dx / 2, 0, dy, y0 - dy / 2))[:6],
        "layers": {
            key: {"path": ds.name, "dtype": str(ds.dtype), "fill": text(ds.attrs.get("_FillValue", ""))}
            for key, ds in layers.items()
        },
    }


def read_window(handle, info, y, x):
    arrays = {}
    for name, layer in info["layers"].items():
        ds = handle[layer["path"]]
        data = ds[y, x]
        default_fill = {"connectedComponents": 65535, "validDataMask": 255}.get(name)
        if name == "mask":
            default_fill = np.iinfo(ds.dtype).max
        fill = ds.attrs.get("_FillValue", default_fill)
        invalid = np.zeros(data.shape, dtype=bool) if fill is None else data == fill
        if name == "mask":
            bits = data.astype(np.uint32)
            code = bits & 255
            arrays[name] = (~invalid & (code < 100) & (code // 10 > 0) & (code % 10 > 0)
                            & ((bits & 0x00FFFF00) == 0))
        else:
            arrays[name] = np.where(invalid, np.nan, data.astype(np.float32))
    coherence = arrays["coherenceMagnitude"]
    valid = arrays["mask"] & (coherence >= 0) & (coherence <= 1)
    if "validDataMask" in arrays:
        # Bits 0 and 1 encode fully focused data in the two acquisitions.
        valid &= np.isfinite(arrays["validDataMask"]) & (
            np.nan_to_num(arrays["validDataMask"]).astype(np.uint8) & 3 == 3)
    return valid, coherence, arrays["unwrappedPhase"], arrays["connectedComponents"]
