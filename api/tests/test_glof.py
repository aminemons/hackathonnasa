"""Release, missing-data and actual HTTP contracts for GLOF monitoring."""
import csv
import hashlib
from http.server import ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from api import glof


class GlofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), glof.handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/api/glof'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_every_packaged_asset_matches_release_hash(self):
        manifest = glof.read(glof.DATA / 'release_manifest.json')
        self.assertEqual(manifest['radar_epochs'], 253)
        for row in manifest['files']:
            path = ROOT / row['file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['sha256'], row['file'])

    def test_all_lakes_keep_observation_dates_and_missing_hazard_values(self):
        catalog = glof.response({})
        self.assertEqual(len(catalog['sites']), 5)
        for site in catalog['sites']:
            data = glof.response({'site':[site['site_id']]})
            self.assertFalse(data['operational_warning_ready'])
            self.assertIsNone(data['breach_probability'])
            self.assertIsNone(data['lake']['water_level_m'])
            self.assertIsNone(data['lake']['lake_volume_m3'])
            dates = [r['date'] for r in data['lake']['series']]
            self.assertEqual(dates, sorted(set(dates)))
            weight = glof.DATA / 'model/water_model.json'
            self.assertEqual(data['model']['sha256'], hashlib.sha256(weight.read_bytes()).hexdigest())

    def test_missing_glacier_observations_are_null(self):
        data = glof.response({'site':['palcacocha']})
        self.assertIsNone(data['movement']['value_m_yr'])
        self.assertIsNone(data['elevation']['partial_surface_volume_change_m3'])
        self.assertNotIn('velocity', data['assets'])

    def test_dated_geometry_is_the_selected_epoch_and_context_is_separate(self):
        for day in ['2023-09-25','2023-10-07']:
            fc = glof.response({'site':['south_lhonak'],'view':['geometry'],'date':[day]})
            self.assertEqual(fc['radar_date'], day)
            lake = [f for f in fc['features'] if f['properties']['layer'] == 'glacial_lake']
            self.assertTrue(lake)
            self.assertTrue(all(f['properties']['date'] == day for f in lake))
            self.assertTrue(any(f['properties']['layer'] == 'historical_lake_inventory' for f in fc['features']))

    def test_unknown_site_traversal_and_unobserved_date_fail(self):
        for sid in ['../water', 'missing', '/etc/passwd']:
            with self.assertRaises(KeyError):
                glof.response({'site':[sid]})
        with self.assertRaises(KeyError):
            glof.response({'site':['south_lhonak'],'view':['geometry'],'date':['2023-10-04']})

    def test_csv_preserves_unresolved_values_as_blank(self):
        rows = list(csv.DictReader(StringIO(glof.response({'site':['suicide_basin'],'view':['csv']}))))
        self.assertEqual(len(rows), 52)
        missing = [r for r in rows if r['area_estimate_status'] != 'mapped_component']
        self.assertTrue(missing)
        self.assertTrue(all(r['modelled_lake_area_km2'] == '' for r in missing))

    def test_http_json_csv_and_errors(self):
        with urlopen(self.url) as response:
            self.assertEqual(response.headers.get_content_type(), 'application/json')
            self.assertEqual(len(json.load(response)['sites']), 5)
        with urlopen(self.url + '?site=south_lhonak&view=csv') as response:
            self.assertEqual(response.headers.get_content_type(), 'text/csv')
            self.assertIn('2023-10-07', response.read().decode())
        for query, status in [('?site=unknown',404), ('?site=south_lhonak&view=bad',400)]:
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + query)
            self.assertEqual(error.exception.code, status)
            self.assertIn('error', json.load(error.exception))

    def test_partial_volume_is_not_whole_glacier_volume(self):
        data = glof.response({'site':['south_lhonak']})
        self.assertLess(data['elevation']['fraction_of_full_historical_glacier_observed'], .06)
        self.assertFalse(data['whole_glacier_volume_measured'])
        self.assertEqual(data['lake']['independent_checks'][3]['iou'], 855/(855+473))


if __name__ == '__main__':
    unittest.main()
