"""Verify the new host preserves API contracts, static files and size limits."""
import unittest
from unittest.mock import patch

from deployment.gateway import app
from api import exposure, chat_provider, events


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health_and_frontend(self):
        self.assertEqual(self.client.get('/healthz').json, {'status': 'ready'})
        with self.client.get('/') as result:
            self.assertEqual(result.status_code, 200)
            self.assertIn(b'TerraPulse', result.data)
            self.assertEqual(result.headers['Cache-Control'], 'no-cache')

    def test_catalog_geometry_csv_and_bad_site(self):
        self.assertEqual(len(self.client.get('/api/glof').json['sites']), 5)
        self.assertEqual(self.client.get('/api/glof?site=south_lhonak').json['site']['site_id'], 'south_lhonak')
        geometry = self.client.get('/api/glof?site=south_lhonak&view=geometry&date=2023-10-07')
        self.assertEqual(geometry.json['type'], 'FeatureCollection')
        csv = self.client.get('/api/glof?site=south_lhonak&view=csv')
        self.assertEqual(csv.status_code, 200)
        self.assertIn('text/csv', csv.content_type)
        self.assertIn('attachment', csv.headers['Content-Disposition'])
        self.assertEqual(self.client.get('/api/glof?site=missing').status_code, 404)

    def test_post_chat_uses_real_router(self):
        with patch.object(chat_provider, '_model_reply', return_value=None):
            result = self.client.post('/api/chat', json={'message': 'Open GLOF monitoring'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['actions'][0], {'type': 'open_tool', 'value': 'glof'})
        self.assertEqual(self.client.post('/api/chat', data='{', content_type='application/json').status_code, 400)

    def test_unavailable_keeps_status_and_retry_header(self):
        with patch.object(exposure, 'load_osm', side_effect=OSError('offline')):
            result = self.client.get('/api/exposure?lon=3&lat=36')
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.headers['Retry-After'], '60')
        self.assertNotIn('counts', result.json)

    def test_archive_can_be_viewed_without_becoming_a_live_alarm(self):
        with patch.object(events, '_request', return_value={'events': []}):
            current = self.client.get('/api/events?hazard=ls')
            archived = self.client.get('/api/events?hazard=ls&include_recent=1')
        self.assertEqual(current.json['records'], [])
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(len(archived.json['records']), 17)
        self.assertTrue(archived.json['archive_only'])

    def test_real_model_inference_and_body_limit(self):
        result = self.client.get('/api/landslide?example=1')
        self.assertEqual(result.status_code, 200)
        self.assertIn('example_evaluation', result.json)
        oversized = self.client.post('/api/landslide', data=b'x'*4_000_001, content_type='application/json')
        self.assertEqual(oversized.status_code, 413)

    def test_no_repository_or_spa_fallback_leaks(self):
        for path in ['/requirements.txt', '/server_data/landslide_spatial.onnx', '/api/unknown', '/../api/chat.py']:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post('/api/glof', json={}).status_code, 405)


if __name__ == '__main__':
    unittest.main()
