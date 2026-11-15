"""Exercise the pipeline with small synthetic products. No model fitting or downloads."""

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import h5py
import numpy as np
import rasterio
from rasterio.transform import array_bounds, from_origin
from rasterio.warp import transform_bounds, transform_geom

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features import FEATURES, build, label_array, spatial_gradient
from gunw import FREQUENCY, IDENT, METADATA, RangeFile, header, read_window, temporal_check
from model import collect, predict


class SyntheticScore:
    def predict_proba(self, features):
        scores = features[:, 2].clip(0, 1)
        return np.column_stack((1 - scores, scores))


class PipelineTest(unittest.TestCase):
    def make_pair(self, path, reference, secondary, coherence):
        shape = (48, 48)
        with h5py.File(path, "w") as ds:
            ident = ds.create_group(IDENT)
            for key, value in {"track": 98, "frame": 16, "pass": b"Ascending",
                               "reference": reference.encode(), "secondary": secondary.encode()}.items():
                ident[METADATA[key]] = value
            ident["productType"] = b"GUNW"
            freq = ds.create_group(FREQUENCY)
            freq["centerFrequency"] = 1.257e9
            group = freq.create_group("unwrappedInterferogram")
            group["xCoordinates"] = 500040 + 80 * np.arange(shape[1])
            group["yCoordinates"] = 3159960 - 80 * np.arange(shape[0])
            group["xCoordinateSpacing"], group["yCoordinateSpacing"] = 80, -80
            group["projection"] = 32645
            mask = np.full(shape, 11, np.uint32)
            mask[20, 20] = 111
            mask[21, 20] = 11 | (1 << 8)
            group["mask"] = mask
            pol = group.create_group("HH")
            pol["unwrappedPhase"] = np.indices(shape)[1].astype("float32")
            pol["unwrappedPhase"].attrs["units"] = "radians"
            pol["coherenceMagnitude"] = np.full(shape, coherence, np.float32)
            pol["coherenceMagnitude"].attrs["units"] = "1"
            pol["connectedComponents"] = np.ones(shape, np.uint16)
            pol["validDataMask"] = np.full(shape, 3, np.uint8)
            pol["validDataMask"][22, 20] = 1

    def test_build_and_predict_using_stub(self):
        import joblib
        import sklearn
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event, control, dem = [root / name for name in ("event.h5", "control.h5", "dem.tif")]
            self.make_pair(event, "2026-08-19T23:39:18Z", "2026-08-31T23:39:18Z", .45)
            self.make_pair(control, "2026-07-26T23:39:19Z", "2026-08-19T23:39:18Z", .8)
            transform = from_origin(500000, 3160000, 80, 80)
            with rasterio.open(dem, "w", driver="GTiff", count=1, height=48, width=48,
                               transform=transform, crs="EPSG:32645", dtype="float32") as dst:
                dst.write(np.indices((48, 48))[1].astype("float32") * 8, 1)
            bounds = transform_bounds("EPSG:32645", "EPSG:4326",
                                      *array_bounds(20, 20, from_origin(500800, 3159200, 80, 80)))
            pilot = {"occurred": "2026-08-26T02:52:10Z", "bbox": bounds}
            out = root / "features.tif"
            with h5py.File(event, "r") as source:
                info = header(source, "HH")
                good, *_ = read_window(source, info, slice(20, 23), slice(20, 21))
                self.assertFalse(good.any())
            build(event, control, dem, pilot, out)
            with rasterio.open(out) as src:
                self.assertEqual(src.descriptions, FEATURES)
                self.assertEqual(src.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG")
                for band, expected in ((3, .35), (4, .0125), (6, np.degrees(np.arctan(.1)))):
                    vals = src.read(band, masked=True).compressed()
                    np.testing.assert_allclose(vals, expected, atol=1e-4)
                self.assertGreater(src.read(1, masked=True).mask.sum(), 0)
            fake = root / "synthetic.joblib"
            joblib.dump({"version": 1, "features": FEATURES, "sklearn": sklearn.__version__,
                         "model": SyntheticScore(), "threshold": .2}, fake)
            result = root / "candidates.tif"
            predict(out, fake, result)
            with rasterio.open(result) as src:
                self.assertEqual(src.descriptions, ("candidate_score", "candidate_mask"))
                self.assertTrue((src.read(2, masked=True).compressed() == 1).all())

    def test_provider_header_normalizes_utc_without_zone_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provider.h5"
            self.make_pair(path, "2026-08-19T23:39:18.567105263", "2026-08-31T23:39:18.442763158", .4)
            with h5py.File(path, "r") as source:
                info = header(source, "HH")
            self.assertEqual(info["reference"], "2026-08-19T23:39:18.567105+00:00")
            self.assertEqual(info["secondary"], "2026-08-31T23:39:18.442763+00:00")

    def test_component_boundaries_and_invalid_centers(self):
        data = np.ones((5, 5))
        labels = np.ones((5, 5))
        labels[0, 2] = 2
        valid = np.ones((5, 5), dtype=bool)
        valid[3, 3] = False
        result = spatial_gradient(data, 1, 1, valid, labels)
        self.assertTrue(np.isnan(result[0, 1]) and np.isnan(result[2, 2]))
        self.assertEqual(result[1, 1], 0)

    def test_unknown_pixels_and_overlapping_labels(self):
        transform = from_origin(500000, 3160000, 80, 80)
        x, y = 500000, 3160000
        tile = {"type": "Polygon", "coordinates": [[
            (x, y), (x + 80, y), (x + 80, y - 80), (x, y - 80), (x, y)
        ]]}
        crs = "EPSG:32645"
        polygon = transform_geom(crs, "EPSG:4326", tile)
        features = [{"type": "Feature", "geometry": polygon, "properties": {"label": 1}}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "labels.geojson"
            doc = {"type": "FeatureCollection", "features": features}
            path.write_text(json.dumps(doc))
            labels = label_array(path, crs, transform, (2, 2))
            self.assertEqual(labels[0, 0], 1)
            self.assertEqual(np.isnan(labels).sum(), 3)
            features.append({**features[0], "properties": {"label": 0}})
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, "overlap"):
                label_array(path, crs, transform, (2, 2))

    def test_wrong_event_timing_rejected(self):
        pair = {"reference": "2026-07-01T00:00:00Z", "secondary": "2026-07-13T00:00:00Z"}
        with self.assertRaisesRegex(ValueError, "pre-event control"):
            temporal_check(pair, pair, datetime(2026, 7, 5, tzinfo=timezone.utc))

    def test_cross_split_granule_rejected_before_training(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "splits.json"
            rows = [{"stack": f"{split}.tif", "split": split, "event": split, "site": split}
                    for split in ("train", "validation", "test")]
            manifest.write_text(json.dumps(rows))
            arrays = np.ones((len(FEATURES) + 1, 2, 2))
            tags = {"event_granule": "event", "control_granule": "control", "pair_headers": "{}"}
            with patch("model.read_stack", return_value=(arrays, tags, None, None)):
                with self.assertRaisesRegex(ValueError, "crosses splits"):
                    collect(manifest)

    def test_range_reader_never_consumes_full_response(self):
        url = "https://nisar.asf.earthdatacloud.nasa.gov/NISAR/test.h5"
        head = Mock(status_code=200, headers={"Content-Length": "100"})
        partial = Mock(status_code=206, headers={"Content-Range": "bytes 0-3/100"}, raw=io.BytesIO(b"abcd"))
        full = Mock(status_code=200, headers={}, raw=Mock())
        session = Mock()
        session.head.return_value.__enter__ = Mock(return_value=head)
        session.head.return_value.__exit__ = Mock(return_value=False)
        session.get.return_value.__enter__ = Mock(side_effect=[partial, full])
        session.get.return_value.__exit__ = Mock(return_value=False)
        with patch("gunw.requests.Session", return_value=session):
            with RangeFile(url, limit=8) as stream:
                self.assertEqual(stream.read(4), b"abcd")
                with self.assertRaisesRegex(ValueError, "byte range"):
                    stream.read(4)
                full.raw.read.assert_not_called()
                with self.assertRaisesRegex(ValueError, "byte budget"):
                    stream.read(5)


if __name__ == "__main__":
    unittest.main()
