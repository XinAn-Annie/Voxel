from collections import Counter

import numpy as np

from config import settings
from octree.topology import (
    bridge_false_mask, component_count, has_separated_source_components, rasterize,
)


def validate(nodes, truth, analysis=None):
    output = rasterize(nodes, settings.grid_resolution)
    false_fill = output & ~truth.occupied
    missed = truth.occupied & ~output
    depths = Counter(node[0] for node in nodes)
    total = max(1, len(nodes))
    output_components = component_count(output)
    separated_component_bridges = 0
    protected_gap_fill = int((output & analysis.protected_gap).sum()) if analysis is not None else 0
    silhouette_gap_fill = int((output & analysis.silhouette_gap).sum()) if analysis is not None else 0
    if analysis is not None:
        for depth, x, y, z, *_ in nodes:
            width = settings.grid_resolution // (2 ** depth)
            lo = np.asarray((x, y, z)) * width
            hi = lo + width
            block = np.s_[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
            if has_separated_source_components(
                analysis.cell_component_ids[block],
                truth.surface[block],
                analysis.component_adjacency,
            ):
                separated_component_bridges += 1
    return {
        'false_fill_count': int(false_fill.sum()),
        'missed_occupied_count': int(missed.sum()),
        'false_bridge_count': int(component_count(bridge_false_mask(output, truth.occupied))),
        'separated_component_bridge_count': separated_component_bridges,
        'protected_gap_fill_count': protected_gap_fill,
        'protected_gap_cell_count': int(analysis.protected_gap.sum()) if analysis is not None else 0,
        'silhouette_gap_fill_count': silhouette_gap_fill,
        'silhouette_gap_cell_count': int(analysis.silhouette_gap.sum()) if analysis is not None else 0,
        'input_components': int(truth.component_count),
        'output_components': output_components,
        'floating_component_count': max(0, output_components - truth.component_count),
        'removed_source_floating_cells': int(truth.removed_floating_cells),
        'closed_surface': bool(nodes) and not missed.any(),
        'depth_counts': {str(k): v for k, v in sorted(depths.items())},
        'depth5_ratio': round(depths.get(settings.max_depth, 0) / total, 5),
        'depth5_target_met': depths.get(settings.max_depth, 0) / total <= settings.target_depth5_ratio,
    }


def serialize(nodes):
    result = []
    for depth, x, y, z, score, normal, error, thin, *extra in nodes:
        size = 1.0 / (2 ** depth)
        result.append({
            'x': round((x + .5) * size, 6),
            'y': round((y + .5) * size, 6),
            'z': round((z + .5) * size, 6),
            'size': round(size, 6), 'depth': depth,
            'importance': round(score, 4),
            'curvature': round(error, 4),
            'curvature_variation': round(normal / 180.0, 4),
            'thickness': round(thin, 4),
            'normal_variation': round(normal / 180.0, 4),
            'geometry_error': round(error, 4),
            'layer': extra[0] if extra else 'structure',
        })
    return result
