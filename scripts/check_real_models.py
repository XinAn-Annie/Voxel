"""Focused checks for the supplied dog and fox GLBs."""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api.routes import VoxelRequest
from geometry.importance import GeometryAnalysis
from meshio.mesh_loader import load_mesh
from octree.builder import build_candidate_tree
from octree.pruning import prune
from config import settings


def analyze(path):
    mesh, transform = load_mesh(path.read_bytes())
    geometry = GeometryAnalysis(mesh)
    root, nodes = build_candidate_tree(geometry)
    request = VoxelRequest(model_id="local")
    voxels, _, _ = prune(root, request, transform["original_scale"], mesh.is_watertight)
    centers = np.asarray([[v[k] for k in ("x", "y", "z")] for v in voxels])
    sizes = np.asarray([v["size"] for v in voxels])
    closest = geometry.scene.compute_closest_points(
        __import__("open3d").core.Tensor(centers.astype(np.float32))
    )["points"].numpy()
    distance_ratio = np.linalg.norm(centers - closest, axis=1) / sizes
    assert np.min(sizes) * settings.target_model_size_mm >= settings.min_printed_voxel_mm - 1e-8
    if mesh.is_watertight:
        occupied = geometry.scene.compute_occupancy(
            __import__("open3d").core.Tensor(centers.astype(np.float32)), nsamples=5
        ).numpy()
        assert np.all((occupied > 0) | (distance_ratio <= .38 + 1e-5)), f"{path.name}: output contains distant outside voxel centers"
    else:
        assert np.max(distance_ratio) <= .15 + 1e-5
    return mesh, voxels, centers, sizes, distance_ratio, nodes, transform


def median(sizes, mask):
    return round(float(np.median(sizes[mask])), 6) if mask.any() else None


def main():
    dog_path = ROOT / "samples" / "animal.glb"
    if len(sys.argv) < 2:
        raise SystemExit("usage: python scripts/check_real_models.py <fox_simplified.glb>")
    fox_path = Path(sys.argv[1])
    _, dog, dc, ds, dd, dog_nodes, dog_transform = analyze(dog_path)
    dog_regions = {
        "body": (dc[:, 0] > .30) & (dc[:, 0] < .66) & (dc[:, 1] > .35) & (dc[:, 1] < .62),
        "legs": (dc[:, 1] < .35) & (dc[:, 0] > .28) & (dc[:, 0] < .76),
        "face_ears": (dc[:, 0] > .68) & ((dc[:, 1] > .58) | (dc[:, 0] > .78)),
    }
    dog_stats = {}
    for name, mask in dog_regions.items():
        dog_stats[name] = {"count": int(mask.sum()), "median": median(ds, mask)}
        for key in ("curvature", "thickness", "normal_variation", "geometry_error", "importance"):
            dog_stats[name][key] = round(float(np.median([v[key] for v, use in zip(dog, mask) if use])), 4) if mask.any() else None
    assert dog_stats["legs"]["median"] >= dog_stats["face_ears"]["median"]
    _, fox, fc, fs, fd, fox_nodes, fox_transform = analyze(fox_path)
    # The supplied fox has two ear vertex clusters above y=.39 m, separated by
    # an empty x interval (-.125 m, -.017 m) around z=.27 m. Map that measured
    # gap into normalized coordinates and ensure no displayed voxel is centered
    # in it. This catches the bridge visible in the original screenshot.
    gap = ((fc[:, 0] > .375) & (fc[:, 0] < .483) &
           (fc[:, 1] > .656) & (fc[:, 2] > .69) & (fc[:, 2] < .86))
    assert not gap.any(), f"fox: {int(gap.sum())} voxel centers bridge the measured ear gap"
    print({
        "dog": {"voxels": len(dog), "nodes": dog_nodes, "scale_m": dog_transform["original_scale"],
                "regions": dog_stats, "max_center_surface_ratio": round(float(dd.max()), 4)},
        "fox": {"voxels": len(fox), "nodes": fox_nodes, "scale_m": fox_transform["original_scale"],
                "min_cm": round(float(fs.min() * settings.target_model_size_mm / 10.0), 3),
                "ear_gap_centers": int(gap.sum()),
                "max_center_surface_ratio": round(float(fd.max()), 4)},
    })


if __name__ == "__main__":
    main()
