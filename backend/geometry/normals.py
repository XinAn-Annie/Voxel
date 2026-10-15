import numpy as np


def normal_variation(normals):
    if len(normals) < 2:
        return 0.0
    mean = np.mean(normals, axis=0)
    norm = np.linalg.norm(mean)
    if norm < 1e-8:
        return 1.0
    mean /= norm
    angles = np.arccos(np.clip(np.asarray(normals) @ mean, -1, 1))
    return float(np.clip(np.mean(angles) / (np.pi / 2), 0, 1))
