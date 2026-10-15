"""Saliency-directed octree planning for recognisable block abstraction."""
import numpy as np

from config import settings
from octree.topology import (
    bridge_false_mask, component_count, has_separated_source_components,
    normal_spread_degrees, rasterize,
)


def _detail_level(params):
    explicit = getattr(params, 'detail_level', None)
    if explicit is not None:
        return float(np.clip(explicit, 0.0, 1.0))
    return float(np.clip((0.90 - float(params.split_threshold)) / 0.77, 0.0, 1.0))


def _metrics(analysis, score_field, lo, hi):
    block = np.s_[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
    surface = analysis.truth.surface[block]
    occupied = analysis.truth.occupied[block]
    if surface.any():
        sal = score_field[block][surface]
        # A lone high cell must not pull an entire smooth parent to a fine
        # depth. The 90th percentile localises feature refinement while still
        # retaining coherent eye, muzzle and attachment patches.
        importance = float(np.percentile(sal, 90))
        normal = normal_spread_degrees(analysis.cell_normals[block][surface])
        width = max(1, int(hi[0] - lo[0]))
        error = float(np.percentile(analysis.surface_error[block][surface], 90) / width)
        thin = float(np.max(analysis.thin_risk[block][surface]))
    else:
        importance = normal = error = thin = 0.0
    return importance, normal, error, thin, float(occupied.mean())


def _target_depth(importance, detail, allowed_max_depth):
    if importance >= 0.70:
        target = 4 + (1 if detail >= 0.76 else 0)
    elif importance >= 0.54:
        target = 3 + (1 if detail >= 0.36 else 0)
    elif importance >= 0.27:
        target = 2 + (1 if detail >= 0.62 else 0)
    else:
        target = 2 + (1 if detail >= 0.88 else 0)
    return min(int(allowed_max_depth), target, settings.max_depth)


def plan_features(analysis, params, allowed_max_depth):
    """Build coarse structural masses and reserve fine leaves for salient areas.

    The slider moves every band gradually, but never removes the relative
    ordering between low-complexity masses and high-saliency features.
    """
    truth = analysis.truth.occupied
    detail = _detail_level(params)
    score_field = analysis.complexity_field(
        params.curvature_weight, params.normal_weight, params.thickness_weight
    )
    active = {}

    def visit(depth, x, y, z):
        width = settings.grid_resolution // (2 ** depth)
        lo = np.asarray((x, y, z), dtype=int) * width
        hi = lo + width
        block = truth[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
        if not block.any():
            return
        importance, normal, error, thin, coverage = _metrics(analysis, score_field, lo, hi)
        target = _target_depth(importance, detail, allowed_max_depth)
        local_parts = component_count(block)
        block_slice = np.s_[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]]
        spans_separated_components = has_separated_source_components(
            analysis.cell_component_ids[block_slice],
            analysis.truth.surface[block_slice],
            analysis.component_adjacency,
        )
        covers_protected_gap = bool(analysis.protected_gap[block_slice].any())
        # Low occupancy alone is not complexity: a smooth rounded back can
        # legitimately be represented by one coarse block. Only multiple
        # disconnected truth islands are a mandatory structural split.
        # The global bridge pass below remains the hard no-false-connection
        # guard for ear gaps and separated limbs.
        # A tiny sliver may not inflate into a very large cube; 8% is only a
        # leakage guard, far below the old curvature-following threshold.
        must_split = (
            local_parts > 1
            or spans_separated_components
            or covers_protected_gap
            or (depth >= settings.base_depth and coverage < 0.08)
        )
        should_split = depth < settings.base_depth or depth < target or must_split
        if should_split and depth < allowed_max_depth:
            for dx in (0, 1):
                for dy in (0, 1):
                    for dz in (0, 1):
                        visit(depth + 1, x * 2 + dx, y * 2 + dy, z * 2 + dz)
            return
        layer = 'feature' if importance >= 0.54 and depth >= 3 else 'structure'
        active[(depth, x, y, z)] = (importance, normal, error, thin, layer)

    visit(0, 0, 0, 0)

    # Re-open only unsafe parents. This is deliberately after saliency planning:
    # topology is a hard constraint, visual importance is the allocation policy.
    while True:
        unsafe = bridge_false_mask(rasterize(active, settings.grid_resolution), truth)
        if not unsafe.any():
            break
        changed = False
        for key in list(active):
            depth, x, y, z = key
            if depth >= allowed_max_depth:
                continue
            width = settings.grid_resolution // (2 ** depth)
            lo = np.asarray((x, y, z)) * width
            hi = lo + width
            if not unsafe[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]].any():
                continue
            active.pop(key)
            for dx in (0, 1):
                for dy in (0, 1):
                    for dz in (0, 1):
                        child = (depth + 1, x * 2 + dx, y * 2 + dy, z * 2 + dz)
                        cw = settings.grid_resolution // (2 ** (depth + 1))
                        clo = np.asarray(child[1:]) * cw
                        chi = clo + cw
                        if truth[clo[0]:chi[0], clo[1]:chi[1], clo[2]:chi[2]].any():
                            m = _metrics(analysis, score_field, clo, chi)
                            layer = 'feature' if m[0] >= 0.54 and depth + 1 >= 3 else 'structure'
                            active[child] = (*m[:4], layer)
            changed = True
        if not changed:
            break

    return [(*key, *metrics) for key, metrics in active.items()]
