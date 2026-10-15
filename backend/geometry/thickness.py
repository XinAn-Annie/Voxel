"""Area-weighted surface sampling and inward ray thickness, calculated once."""
import numpy as np
import open3d as o3d
from scipy.spatial import cKDTree
import trimesh

from config import settings


def surface_thickness(mesh, scene):
    points, face_ids = trimesh.sample.sample_surface(
        mesh, settings.sample_count, seed=settings.random_seed
    )
    normals = np.asarray(mesh.face_normals[face_ids], dtype=np.float32)
    origins = points.astype(np.float32) - normals * settings.ray_epsilon
    rays = np.hstack([origins, -normals]).astype(np.float32)
    hits = scene.cast_rays(o3d.core.Tensor(rays))['t_hit'].numpy()
    valid = np.isfinite(hits) & (hits > settings.ray_epsilon)
    # An unobserved opposite surface is unknown, not an invented thickness.
    thickness = np.where(valid, hits + settings.ray_epsilon, np.inf)
    return points, normals, thickness, cKDTree(points), valid
