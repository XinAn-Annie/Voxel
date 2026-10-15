import numpy as np
from config import settings


def robust_normalize(values):
    values = np.nan_to_num(np.asarray(values, dtype=np.float64), nan=0, posinf=0, neginf=0)
    low, high = np.percentile(values, [settings.percentile_low, settings.percentile_high])
    if high - low < 1e-12:
        return np.zeros_like(values)
    return np.clip((values - low) / (high - low), 0, 1)


def vertex_curvature(mesh):
    import igl

    result = igl.principal_curvature(
        np.asarray(mesh.vertices, dtype=np.float64), np.asarray(mesh.faces, dtype=np.int64),
        radius=settings.curvature_radius,
    )
    k1, k2 = result[2:4]
    return robust_normalize(np.abs(k1) + np.abs(k2))
