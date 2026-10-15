"""Bottom-up adaptive coarsening from a depth-5 occupancy truth grid."""
from collections import defaultdict

import numpy as np

from config import settings
from octree.topology import bridge_false_mask, component_count, normal_spread_degrees, rasterize


def _score_block(analysis, lo, hi, params):
    block = np.s_[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
    surface = analysis.truth.surface[block]
    if surface.any():
        normals = analysis.cell_normals[block][surface]
        normal_degrees = normal_spread_degrees(normals)
        width = max(1, int(hi[0] - lo[0]))
        error = float(np.percentile(analysis.surface_error[block][surface], 95) / width)
        thin = float(np.max(analysis.thin_risk[block][surface]))
    else:
        normal_degrees = error = thin = 0.0
    normal = min(1.0, normal_degrees / settings.max_normal_angle_deg)
    # SDF/QEM-like residual, normal change and EDT thin-part risk all act on
    # the same cached truth grid. Weights remain compatible with the UI API.
    score = (
        params.curvature_weight * min(1.0, error)
        + params.normal_weight * normal
        + params.thickness_weight * thin
        + settings.geometry_error_weight * min(1.0, error)
    )
    return float(score), normal_degrees, error, thin


def coarsen(analysis, params, allowed_max_depth):
    occupied = analysis.truth.occupied
    active = {
        (settings.max_depth, int(x), int(y), int(z)): None
        for x, y, z in np.argwhere(occupied)
    }

    for child_depth in range(settings.max_depth, 0, -1):
        parent_depth = child_depth - 1
        groups = defaultdict(list)
        for key in active:
            depth, x, y, z = key
            if depth >= child_depth:
                shift = depth - parent_depth
                groups[(parent_depth, x >> shift, y >> shift, z >> shift)].append(key)
        for parent, children in groups.items():
            _, px, py, pz = parent
            width = settings.grid_resolution // (2 ** parent_depth)
            lo = np.asarray((px, py, pz)) * width
            hi = lo + width
            block = occupied[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
            false_fill_ratio = 1.0 - float(block.mean())
            force_for_print = child_depth > allowed_max_depth
            detail_budget = np.sqrt(np.clip(
                (float(params.split_threshold) - 0.13) / 0.70, 0.0, 1.0
            ))
            allowed_false_fill = min(
                0.75 if force_for_print else 0.65,
                0.05 + 0.65 * detail_budget,
            )
            # Mixed cells are allowed as a surface approximation. Multiple
            # local truth islands are never collapsed into one parent.
            if false_fill_ratio > allowed_false_fill or component_count(block) != 1:
                continue
            score, normal_degrees, error, thin = _score_block(analysis, lo, hi, params)
            score += 0.25 * false_fill_ratio
            threshold = float(params.split_threshold)
            allowed_normal = settings.max_normal_angle_deg + 100.0 * threshold
            if not force_for_print and (normal_degrees > allowed_normal or score > threshold):
                continue
            if force_for_print and normal_degrees > 150.0:
                continue
            for child in children:
                active.pop(child)
            active[parent] = (score, normal_degrees, error, thin)

    # Any approximate parent that bridges locally separate truth regions is
    # split again. This preserves ear gaps and removes the old false bridges.
    while True:
        unsafe = bridge_false_mask(rasterize(active, settings.grid_resolution), occupied)
        if not unsafe.any():
            break
        changed = False
        for key in list(active):
            depth, x, y, z = key
            if depth >= settings.max_depth:
                continue
            width = settings.grid_resolution // (2 ** depth)
            lo = np.asarray((x, y, z)) * width
            hi = lo + width
            if not unsafe[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]].any():
                continue
            active.pop(key)
            child_width = width // 2
            for dx in (0, 1):
                for dy in (0, 1):
                    for dz in (0, 1):
                        child_lo = lo + np.asarray((dx, dy, dz)) * child_width
                        child_hi = child_lo + child_width
                        child_block = occupied[
                            child_lo[0]:child_hi[0], child_lo[1]:child_hi[1], child_lo[2]:child_hi[2]
                        ]
                        if child_block.any():
                            active[(depth + 1, x * 2 + dx, y * 2 + dy, z * 2 + dz)] = None
            changed = True
        if not changed:
            break

    output = []
    for key, metrics in active.items():
        depth, x, y, z = key
        if metrics is None:
            width = settings.grid_resolution // (2 ** depth)
            lo = np.asarray((x, y, z)) * width
            metrics = _score_block(analysis, lo, lo + width, params)
        output.append((*key, *metrics))
    return output
