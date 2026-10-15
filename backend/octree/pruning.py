from config import settings
from octree.node import NodeState


def prune(root, params, original_scale=1.0, watertight=True):
    voxels = []
    # params.min_voxel_size is normalized by the API from the intended final
    # print size. Keep a config fallback for direct library callers. The source
    # GLB scale must not affect this threshold.
    print_minimum = settings.min_printed_voxel_mm / settings.target_model_size_mm
    minimum = max(params.min_voxel_size, print_minimum)

    def visit(node):
        if node.state == NodeState.EMPTY:
            return
        # Thickness, opposite-side normals and residual error can all be high
        # on a smooth narrow limb. Curvature gates those auxiliary signals so
        # they reinforce genuinely detailed geometry instead of refining a leg
        # merely because it is thin.
        detail_gate = node.curvature_score
        curvature_detail = max(
            node.curvature_score ** 2,
            min(1.0, node.curvature_variation_score * settings.curvature_variation_gain),
        )
        importance = (
            params.curvature_weight * curvature_detail
            + params.thickness_weight * node.thickness_score * detail_gate
            + params.normal_weight * node.normal_score
            + settings.geometry_error_weight * node.geometry_error_score * detail_gate
        )
        must_split = node.depth < settings.base_depth and node.state == NodeState.SURFACE
        # A thin but smooth leg does not warrant unconditional refinement.
        detail_split = importance > params.split_threshold
        fine_detail = node.curvature_variation_score > settings.fine_curvature_variation_threshold
        if node.depth >= settings.max_depth - 1 and not fine_detail:
            detail_split = False
        outside = (node.state == NodeState.SURFACE and
                   ((watertight and not node.center_inside
                     and node.surface_distance_ratio > settings.surface_distance_ratio) or
                    (not watertight and node.surface_distance_ratio > settings.open_surface_distance_ratio)))
        # For closed meshes an outside-center surface cell is omitted at the
        # chosen level. Refining every such boundary cell would turn smooth
        # bodies and legs into uniformly tiny voxels. Open meshes lack a
        # reliable inside test, so a distant surface cell is refined until its
        # center is close enough to actual geometry or the size limit is met.
        needs_surface_localization = outside and not watertight
        if (node.children and node.size / 2 + 1e-12 >= minimum
                and (must_split or detail_split or needs_surface_localization)):
            for child in node.children:
                visit(child)
            return
        if node.state != NodeState.EMPTY and not outside:
            x, y, z = node.center
            voxels.append({
                "x": round(x, 6), "y": round(y, 6), "z": round(z, 6),
                "size": round(node.size, 6), "depth": node.depth,
                "importance": round(importance, 4),
                "curvature": round(node.curvature_score, 4),
                "curvature_variation": round(node.curvature_variation_score, 4),
                "thickness": round(node.thickness_score, 4),
                "normal_variation": round(node.normal_score, 4),
                "geometry_error": round(node.geometry_error_score, 4),
            })

    visit(root)
    depths = [v['depth'] for v in voxels]
    return voxels, min(depths, default=0), max(depths, default=0)
