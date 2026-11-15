"""Run the shipped water model on an actual, dated South Lhonak SAR example."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def check():
    with tempfile.TemporaryDirectory(prefix='terrapulse-glof-') as work:
        artifacts = Path(work)
        shutil.copytree(ROOT / 'server_data/glof/model', artifacts / 'water')
        (artifacts / 'water/models').mkdir()
        shutil.move(artifacts / 'water/water_model.json', artifacts / 'water/models/water_model.json')
        shutil.copytree(HERE / 'example/south_lhonak', artifacts / 'observed/south_lhonak')
        subprocess.run([sys.executable, '-m', 'real_mvp.infer', '--root', str(artifacts), '--site', 'south_lhonak'],
                       cwd=HERE, check=True)
        result = json.loads((artifacts / 'observed/south_lhonak/observed_summary.json').read_text())
        expected = json.loads((HERE / 'example/south_lhonak/expected.json').read_text())
        actual = result['timeseries'][0]['lake_area_km2']
        if actual is None or abs(actual - expected['lake_area_km2']) > expected['tolerance_km2']:
            raise AssertionError(f'Published area {expected["lake_area_km2"]}, fresh inference {actual}')
        if result['model']['sha256'] != expected['weights_sha256']:
            raise AssertionError('Model weights differ from the published execution')
        print(json.dumps({'date': expected['date'], 'fresh_lake_area_km2': actual,
                          'published_lake_area_km2': expected['lake_area_km2'],
                          'within_one_20m_pixel': True, 'operational_warning_ready': False}, indent=2))


if __name__ == '__main__':
    check()
