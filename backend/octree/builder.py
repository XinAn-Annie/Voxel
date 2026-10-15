"""Triangle/AABB separating-axis intersections, followed by occupancy probes."""
import itertools
import numpy as np
import open3d as o3d

from config import settings
from geometry.normals import normal_variation
from octree.node import AdaptiveOctreeNode, NodeState

BITS = np.asarray(list(itertools.product((0, 1), repeat=3)), dtype=float)


def intersecting_faces(analysis, origin, size, parent_faces):
    """Exact triangle-box SAT. Triangle bounding boxes are only a broad phase."""
    lo = np.asarray(origin)
    hi = lo + size
    epsilon = settings.surface_epsilon
    mask = ((analysis.face_mins[parent_faces] <= hi + epsilon)
            & (analysis.face_maxs[parent_faces] >= lo - epsilon)).all(axis=1)
    ids = parent_faces[mask]
    if not len(ids):
        return ids
    tri = analysis.triangles[ids] - (lo + size / 2)
    edges = np.roll(tri, -1, axis=1) - tri
    normal = np.cross(edges[:, 0], edges[:, 1])
    axes = np.concatenate([normal[:, None, :],
                           np.cross(edges[:, :, None, :], np.eye(3)[None, None, :, :]).reshape(-1, 9, 3)], axis=1)
    projections = np.einsum('nvi,nai->nva', tri, axes)
    radius = size / 2 * np.abs(axes).sum(axis=2)
    separated = (projections.min(axis=1) > radius + epsilon) | (projections.max(axis=1) < -radius - epsilon)
    return ids[~separated.any(axis=1)]


def build_candidate_tree(analysis):
    surface_nodes, other_nodes = [], []
    count = 0

    def visit(origin, size, depth, parent_faces):
        nonlocal count
        count += 1
        if count > settings.max_candidate_nodes:
            raise ValueError("Candidate octree memory limit exceeded")
        faces = intersecting_faces(analysis, origin, size, parent_faces)
        state = NodeState.SURFACE if len(faces) else NodeState.EMPTY
        node = AdaptiveOctreeNode(tuple(origin), size, depth, state)
        if len(faces):
            node.normal_score = normal_variation(analysis.face_normals[faces])
            surface_nodes.append(node)
            if depth < settings.max_depth:
                half = size / 2
                node.children = [visit(np.asarray(origin) + bits * half, half, depth + 1, faces) for bits in BITS]
        else:
            other_nodes.append(node)
        return node

    root = visit(np.zeros(3), 1.0, 0, np.arange(len(analysis.mesh.faces)))
    if analysis.mesh.is_watertight and other_nodes:
        # Probe all 8 corners (slightly inset to avoid boundary ambiguity) plus
        # center. Exact SAT has already excluded a surface crossing the cell.
        origins = np.asarray([n.origin for n in other_nodes])
        sizes = np.asarray([n.size for n in other_nodes])
        probe_offsets = np.vstack([BITS * 0.999998 + 0.000001, [0.5, 0.5, 0.5]])
        probes = (origins[:, None, :] + sizes[:, None, None] * probe_offsets).astype(np.float32)
        inside = analysis.scene.compute_occupancy(o3d.core.Tensor(probes.reshape(-1, 3)), nsamples=3).numpy().reshape(-1, 9)
        for node, occupied in zip(other_nodes, inside):
            if occupied.sum() >= 5:
                node.state = NodeState.INTERIOR
    if analysis.mesh.is_watertight and surface_nodes:
        # The SAT test only says that a triangle touches a box. It does not
        # establish that the center of the displayed cube belongs to the mesh.
        centers = np.asarray([n.center for n in surface_nodes], dtype=np.float32)
        for start in range(0, len(surface_nodes), 8192):
            batch = surface_nodes[start:start + 8192]
            occupied = analysis.scene.compute_occupancy(
                o3d.core.Tensor(centers[start:start + len(batch)]), nsamples=5
            ).numpy()
            for node, value in zip(batch, occupied):
                node.center_inside = bool(value)
    analysis.assign_cell_scores(surface_nodes)
    return root, count
