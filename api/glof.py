"""Serve published, dated GLOF monitoring outputs without scientific runtimes."""
import csv
from http.server import BaseHTTPRequestHandler
from io import StringIO
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

DATA = Path(__file__).resolve().parents[1] / 'server_data/glof'


def read(path):
    return json.loads(path.read_text())


def response(query):
    catalog = read(DATA / 'catalog.json')
    sid = query.get('site', [None])[0]
    view = query.get('view', ['summary'])[0]
    if sid is None:
        if view == 'validation':
            return read(DATA / 'validation.json')
        if view != 'summary':
            raise ValueError('Choose a study lake first.')
        return catalog
    if sid not in {s['site_id'] for s in catalog['sites']}:
        raise KeyError('Unknown study lake.')
    if view not in ('summary', 'geometry', 'csv'):
        raise ValueError('Unknown GLOF view.')
    summary = read(DATA / sid / 'summary.json')
    if view == 'summary':
        return summary
    if view == 'csv':
        out = StringIO()
        writer = csv.writer(out)
        writer.writerow(['date', 'modelled_lake_area_km2', 'area_estimate_status',
                         'accepted', 'valid_fraction', 'sensor', 'operational_status'])
        for row in summary['lake']['series']:
            writer.writerow([row['date'], row['lake_area_km2'], row['area_estimate_status'],
                             row['accepted'], row['valid_fraction'], 'ESA Sentinel-1', 'not_assessed'])
        return out.getvalue()
    day = query.get('date', [summary['lake']['series'][-1]['date']])[0]
    if day not in {r['date'] for r in summary['lake']['series']}:
        raise KeyError('No observation for this date; no interpolation is supplied.')
    context = read(DATA / sid / 'context.geojson')
    lake = read(DATA / sid / 'epochs.geojson.json')[day]
    return {'type': 'FeatureCollection', 'features': context['features'] + lake['features'],
            'site_id': sid, 'radar_date': day,
            'interpretation': 'Dated modelled water with separately dated historical glacier/inventory context.'}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            result = response(parse_qs(urlsplit(self.path).query))
        except KeyError as error:
            return self.send_json({'error': str(error.args[0])}, 404)
        except ValueError as error:
            return self.send_json({'error': str(error)}, 400)
        except (OSError, json.JSONDecodeError):
            return self.send_json({'error': 'The published GLOF evidence bundle is unavailable.'}, 503)
        if isinstance(result, str):
            body = result.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="glof-lake-area.csv"')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_json(result, cache='public, max-age=300, s-maxage=3600')

    def send_json(self, body, status=200, cache='no-store'):
        content = json.dumps(body, separators=(',', ':'), allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', cache)
        self.end_headers()
        self.wfile.write(content)
