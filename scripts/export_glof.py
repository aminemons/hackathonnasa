"""Publish an executed GLOF run into TerraPulse's small, offline-serving bundle.

No acquisition, training, interpolation or replacement of missing values occurs
here. Run the scientific pipeline separately, then export its reviewed outputs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    geometry = path.name in ('context.geojson', 'epochs.geojson.json')
    path.write_text(json.dumps(value, indent=None if geometry else 2,
                               separators=(',', ':') if geometry else None,
                               allow_nan=False) + '\n')


def export(source, destination=ROOT):
    data = destination / 'server_data/glof'
    public = destination / 'public/data/glof'
    rows, hashes = [], []

    def copy(src, dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        hashes.append({'file': str(dst.relative_to(destination)),
                       'sha256': hashlib.sha256(dst.read_bytes()).hexdigest()})

    for entry in load(source / 'simplified/run_manifest.json')['sites']:
        sid = entry['site_id']
        if not sid.replace('_', '').isalpha():
            raise ValueError('Invalid site identifier')
        summary = load(source / 'simplified' / sid / 'summary.json')
        if summary['operational_warning_ready'] or summary['breach_probability'] is not None:
            raise ValueError('This integration only accepts the monitoring contract')
        epochs = summary['lake']['series']
        geometry = {}
        for epoch in epochs:
            day = epoch['date']
            # Missing geometry is an error, not an empty lake substituted at export.
            geometry[day] = load(source / 'observed' / sid / f'lake_{day}.geojson')
        write(data / sid / 'epochs.geojson.json', geometry)
        assets = {}
        for kind in ['velocity', 'elevation']:
            path = source / 'simplified' / sid / f'{kind}.png'
            if path.exists():
                copy(path, public / sid / path.name)
                assets[kind] = f'/data/glof/{sid}/{path.name}'
        change = source / 'simplified' / sid / 'glacier_surface_change_m.tif'
        if change.exists():
            copy(change, public / sid / change.name)
            assets['surface_change'] = f'/data/glof/{sid}/{change.name}'
        summary['assets'] = assets
        # Keep lake-specific evidence separate from the multi-indicator grade.
        observed = load(source / 'observed' / sid / 'observed_summary.json')
        summary['lake']['confidence_basis'] = observed['evidence']['confidence_basis']
        summary['lake']['confidence_kind'] = 'Heuristic water-map grade from automatic optical references; not event probability.'
        summary['data_sources'] = observed['data_sources']
        summary['model'] = observed['model']
        summary['sources'] = observed['evidence']['sources'] + summary['sources']
        write(data / sid / 'context.geojson', load(source / 'simplified' / sid / 'context.geojson'))
        write(data / sid / 'summary.json', summary)
        rows.append({'site_id': sid, 'name': summary['site']['name'],
                     'country': summary['site']['country'],
                     'lon': summary['site']['lake_lon'], 'lat': summary['site']['lake_lat'],
                     'epochs': len(epochs), 'confidence': summary['confidence'],
                     'water_map_confidence': summary['lake']['confidence'],
                     'date_range': summary['observation_date_range']})
    validation = load(source / 'water/water_validation.json')
    validation.pop('folds', None)
    write(data / 'validation.json', validation)
    copy(source / 'water/models/water_model.json', data / 'model/water_model.json')
    copy(source / 'water/water_model_card.json', data / 'model/water_model_card.json')
    write(data / 'catalog.json', {'schema_version': '1.0', 'sites': rows,
                                'execution_mode': 'published_historical_model_outputs',
                                'operational_warning_ready': False})
    # Hash generated files as well as copied assets. This is a release inventory,
    # not a substitute for upstream provenance embedded in each summary.
    known = {h['file'] for h in hashes}
    for path in sorted(data.rglob('*')):
        if path.is_file() and path.name != 'release_manifest.json' and str(path.relative_to(destination)) not in known:
            hashes.append({'file': str(path.relative_to(destination)),
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    write(data / 'release_manifest.json', {'files': hashes, 'sites': len(rows),
                                         'radar_epochs': sum(s['epochs'] for s in rows)})
    print(f'Published {len(rows)} sites, {sum(s["epochs"] for s in rows)} dated radar geometries.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    export(parser.parse_args().artifacts)
