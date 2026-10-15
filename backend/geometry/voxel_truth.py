"""Conservative 32^3 occupancy truth used by every adaptive merge decision."""
from dataclasses import dataclass

import numpy as np
import open3d as o3d
import point_cloud_utils as pcu
from scipy import ndimage

from config import settings


@dataclass
class VoxelTruth:
    surface: np.ndarray
    occupied: np.ndarray
    outside: np.ndarray
    component_count: int
    removed_floating_cells: int = 0


def build_voxel_truth(proxy, reference=None) -> VoxelTruth:
    resolution = settings.grid_resolution
    surface = np.zeros((resolution,) * 3, dtype=bool)
    vertices = np.asarray(proxy.vertices, dtype=np.float64)
    faces = np.asarray(proxy.faces, dtype=np.int32)
    if len(faces) <= 10_000:
        # Union three axis permutations. This removes a PCU degeneracy for
        # grid-aligned coplanar triangles while retaining its triangle voxelizer.
        for permutation in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
            inverse = np.argsort(permutation)
            indices = pcu.voxelize_triangle_mesh(
                np.ascontiguousarray(vertices[:, permutation]),
                np.ascontiguousarray(faces), 1.0 / resolution,
                np.zeros(3, dtype=np.float64),
            )
            indices = np.asarray(indices, dtype=np.int64)[:, inverse]
            if len(indices):
                indices = np.clip(indices, 0, resolution - 1)
                surface[tuple(indices.T)] = True
    # Open3D closes grid-aligned/coplanar gaps left by the PCU rasterizer. It is
    # also the safe path for large Windows meshes where PCU's Morton encoder can
    # terminate the process.
    triangle_mesh = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(vertices), o3d.utility.Vector3iVector(faces)
    )
    grid = o3d.geometry.VoxelGrid.create_from_triangle_mesh_within_bounds(
        triangle_mesh, 1.0 / resolution, np.zeros(3), np.ones(3)
    )
    indices = np.asarray([v.grid_index for v in grid.get_voxels()], dtype=np.int64)
    indices = np.clip(indices, 0, resolution - 1)
    surface[tuple(indices.T)] = True
    if not surface.any():
        raise ValueError("Mesh did not intersect the depth-5 occupancy grid")

    padded_surface = np.pad(surface, 1, constant_values=False)
    seed = np.zeros_like(padded_surface)
    seed[[0, -1], :, :] = True
    seed[:, [0, -1], :] = True
    seed[:, :, [0, -1]] = True
    outside_padded = ndimage.binary_propagation(
        seed, mask=~padded_surface, structure=ndimage.generate_binary_structure(3, 1)
    )
    outside = outside_padded[1:-1, 1:-1, 1:-1]
    occupied = ~outside
    if reference is not None:
        # Triangle/cell intersection is conservative and can promote a tiny
        # tangential contact into a full cube. At exposed boundary cells,
        # require the cell centre to remain within half a finest-cell edge of
        # the original (unrepaired) mesh. This removes the artificial top bar
        # between ears without eroding genuine interior volume.
        grid_indices = np.indices((resolution,) * 3).reshape(3, -1).T
        centers = np.ascontiguousarray((grid_indices + 0.5) / resolution, dtype=np.float64)
        distances, _, _ = pcu.signed_distance_to_mesh(
            centers,
            np.ascontiguousarray(reference.vertices, dtype=np.float64),
            np.ascontiguousarray(reference.faces, dtype=np.int32),
        )
        distances = distances.reshape((resolution,) * 3)
        exterior_tangent = surface & (distances > 0.55 / resolution)
        occupied[exterior_tangent] = False
        surface = occupied & ~ndimage.binary_erosion(
            occupied, structure=ndimage.generate_binary_structure(3, 1)
        )
    labels, components = ndimage.label(occupied, ndimage.generate_binary_structure(3, 1))
    removed = 0
    if components > 1:
        sizes = np.bincount(labels.ravel())
        largest = int(np.argmax(sizes[1:]) + 1)
        keep = labels == largest
        removed = int((occupied & ~keep).sum())
        occupied = keep
        surface &= keep
        components = 1
    outside = ~occupied
    return VoxelTruth(surface, occupied, outside, int(components), removed)
