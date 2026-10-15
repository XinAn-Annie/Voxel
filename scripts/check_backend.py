"""V5 integration checks: saliency hierarchy, topology, print size and cache reuse."""
import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from cache.store import cache
from main import app


def wait_ready(client, model_id):
    for _ in range(600):
        response = client.get(f'/api/models/{model_id}')
        assert response.status_code == 200, response.text
        if response.json()['status'] == 'ready':
            return response.json()
        if response.json()['status'] == 'error':
            raise AssertionError(response.text)
        time.sleep(.1)
    raise AssertionError('analysis timeout')


def main():
    client = TestClient(app)
    assert client.post('/api/upload', files={'file': ('bad.glb', b'bad')}).status_code == 400
    report = []
    for name in ('cube', 'sphere', 'animal', 'Bear_3d'):
        raw = (ROOT / 'samples' / f'{name}.glb').read_bytes()
        response = client.post('/api/upload', files={'file': (f'{name}.glb', raw)})
        assert response.status_code == 202, response.text
        model_id = response.json()['model_id']
        status = wait_ready(client, model_id)
        cached = cache.get(model_id)
        identity = (id(cached.geometry), id(cached.truth), cached.analysis_runs)
        counts = []
        for detail in (0, .5, 1):
            result = client.post('/api/voxelize', json={
                'model_id': model_id,
                'detail_level': detail,
                'target_model_size_mm': 320,
                'min_printed_voxel_mm': 10,
            })
            assert result.status_code == 200, result.text
            stats = result.json()['stats']
            assert stats['max_depth'] <= 5
            assert stats['min_size_mm'] >= 10
            assert stats['missed_occupied_count'] == 0
            assert stats['false_bridge_count'] == 0
            assert stats['separated_component_bridge_count'] == 0
            assert stats['protected_gap_fill_count'] == 0
            assert stats['silhouette_gap_fill_count'] == 0
            assert stats['floating_component_count'] == 0
            assert stats['closed_surface']
            counts.append(stats['voxel_count'])
        assert counts == sorted(counts)
        if name == 'Bear_3d':
            assert stats['protected_gap_cell_count'] > 0
            assert stats['silhouette_gap_cell_count'] > 0
            assert counts[-1] >= counts[0] * 1.2, counts
            structure_result = client.post('/api/voxelize', json={
                'model_id': model_id, 'detail_level': .4,
                'target_model_size_mm': 320, 'min_printed_voxel_mm': 10,
            })
            structure_voxels = structure_result.json()['voxels']
            face_depths = [
                voxel['depth'] for voxel in structure_voxels
                if voxel['y'] > .55 and voxel['z'] > .58 and .28 < voxel['x'] < .72
            ]
            back_depths = [
                voxel['depth'] for voxel in structure_voxels
                if .50 < voxel['y'] < .78 and voxel['z'] < .38 and .28 < voxel['x'] < .72
            ]
            assert face_depths and back_depths
            assert sum(face_depths) / len(face_depths) >= sum(back_depths) / len(back_depths) + .5
            low_weight_count = client.post('/api/voxelize', json={
                'model_id': model_id, 'detail_level': .4, 'curvature_weight': 0,
            }).json()['stats']['voxel_count']
            high_weight_count = client.post('/api/voxelize', json={
                'model_id': model_id, 'detail_level': .4, 'curvature_weight': 1,
            }).json()['stats']['voxel_count']
            assert high_weight_count > low_weight_count
            default_result = client.post('/api/voxelize', json={'model_id': model_id})
            assert default_result.status_code == 200, default_result.text
            default_stats = default_result.json()['stats']
            assert default_stats['depth5_ratio'] < 0.60, default_stats
            assert default_stats['feature_voxel_count'] > 0, default_stats
            assert default_stats['false_bridge_count'] == 0
            coarse_print = client.post('/api/voxelize', json={
                'model_id': model_id,
                'min_voxel_size_cm': 10,
                'target_model_size_mm': 320,
            })
            assert coarse_print.status_code == 200, coarse_print.text
            coarse_stats = coarse_print.json()['stats']
            assert coarse_stats['min_size_cm'] >= 10
            assert coarse_stats['effective_max_depth'] <= 1
            assert not coarse_stats['print_scale_adjusted']
            assert coarse_stats['false_bridge_count'] == 0
        assert identity == (id(cached.geometry), id(cached.truth), cached.analysis_runs)
        item = {'model': name, 'candidate_nodes': status['candidate_nodes'], 'counts': counts}
        if name == 'Bear_3d':
            item['face_mean_depth'] = round(sum(face_depths) / len(face_depths), 3)
            item['back_mean_depth'] = round(sum(back_depths) / len(back_depths), 3)
            item['curvature_weight_counts'] = [low_weight_count, high_weight_count]
        report.append(item)
        print(json.dumps(report[-1]), flush=True)
    (ROOT / 'tests').mkdir(exist_ok=True)
    (ROOT / 'tests' / 'backend-results-v5.json').write_text(
        json.dumps(report, indent=2), encoding='utf-8'
    )
    print('V5 backend checks PASS', flush=True)


if __name__ == '__main__':
    main()
