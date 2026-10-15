import io
from dataclasses import dataclass
import numpy as np
import point_cloud_utils as pcu
import trimesh
from config import settings


@dataclass
class LoadedMeshes:
    original: trimesh.Trimesh
    analysis: trimesh.Trimesh
    proxy: trimesh.Trimesh
    repair_error: float
    input_components: int
    face_feature_prior: np.ndarray
    face_part_ids: np.ndarray
    face_component_ids: np.ndarray


def _clean(mesh):
    finite_vertices = np.isfinite(mesh.vertices).all(axis=1)
    mesh.update_faces(finite_vertices[mesh.faces].all(axis=1))
    mesh.remove_unreferenced_vertices()
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.update_faces(mesh.unique_faces())
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals(multibody=True)
    return mesh


def _pcu_mesh(vertices, faces):
    return _clean(trimesh.Trimesh(np.asarray(vertices), np.asarray(faces), process=False))


def load_mesh(raw: bytes):
    loaded = trimesh.load(io.BytesIO(raw), file_type="glb", force="scene", process=False)
    parts = [_clean(m.copy()) for m in loaded.dump() if isinstance(m, trimesh.Trimesh) and len(m.faces)]
    if not parts:
        raise ValueError("GLB contains no triangle mesh")
    face_counts = np.asarray([len(part.faces) for part in parts], dtype=np.float64)
    luminance = []
    for part in parts:
        material = getattr(part.visual, 'material', None)
        color = getattr(material, 'baseColorFactor', None)
        rgb = np.asarray(color[:3] if color is not None else (128, 128, 128), dtype=np.float64)
        if rgb.max(initial=0) > 1.0:
            rgb /= 255.0
        luminance.append(float(rgb @ np.asarray((0.2126, 0.7152, 0.0722))))
    luminance = np.asarray(luminance)
    dominant = float(np.average(luminance, weights=np.maximum(face_counts, 1)))
    contrast = np.clip(np.abs(luminance - dominant) / 0.55, 0.0, 1.0)
    scene_extent = np.maximum((
        np.max(np.vstack([part.bounds[1] for part in parts]), axis=0)
        - np.min(np.vstack([part.bounds[0] for part in parts]), axis=0)
    ), 1e-9)
    relative_extent = np.asarray([
        np.linalg.norm((part.bounds[1] - part.bounds[0]) / scene_extent) / np.sqrt(3.0)
        for part in parts
    ])
    # Triangle count is a modelling/export detail. Spatial size and material
    # contrast are better generic signals for eyes, muzzle, ear insets, etc.
    part_prior = np.clip(0.68 * contrast + 0.32 * (1.0 - relative_extent), 0.0, 1.0)
    face_prior = np.concatenate([
        np.full(len(part.faces), part_prior[index], dtype=np.float64)
        for index, part in enumerate(parts)
    ])
    face_part_ids = np.concatenate([
        np.full(len(part.faces), index, dtype=np.int16)
        for index, part in enumerate(parts)
    ])
    mesh = _clean(trimesh.util.concatenate(parts))
    if len(face_prior) != len(mesh.faces):
        face_prior = np.zeros(len(mesh.faces), dtype=np.float64)
        face_part_ids = np.zeros(len(mesh.faces), dtype=np.int16)
    if len(mesh.faces) == 0 or not np.isfinite(mesh.vertices).all():
        raise ValueError("GLB has no valid finite faces")
    bounds = mesh.bounds.copy()
    center = bounds.mean(axis=0)
    scale = float(np.max(bounds[1] - bounds[0]))
    if scale < settings.min_voxel_size_m:
        raise ValueError("GLB model extent is under 1 cm; no valid voxel can be produced")
    offset = 0.5 - center / scale
    mesh.vertices = mesh.vertices / scale + offset
    mesh.fix_normals(multibody=True)
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int32)
    vertex_components, _, _, _ = pcu.connected_components(vertices, faces)
    input_components = len(np.unique(vertex_components))
    face_component_ids = np.asarray(vertex_components, dtype=np.int16)[faces[:, 0]]

    notes = []
    analysis = mesh.copy()
    if len(faces) > settings.analysis_target_faces:
        try:
            av, af, _, _ = pcu.decimate_triangle_mesh(
                vertices, faces, settings.analysis_target_faces, decimation_heuristic='shortest_edge'
            )
            if len(af):
                analysis = _pcu_mesh(av, af)
        except (TypeError, ValueError, RuntimeError):
            # Non-manifold decorative models can defeat edge-collapse. The
            # original remains valid input for the low-resolution truth grid.
            notes.append("Analysis decimation was skipped because the mesh is non-manifold.")

    repair_error = 0.0
    proxy = mesh.copy()
    if not mesh.is_watertight:
        pv, pf = pcu.make_mesh_watertight(
            np.asarray(analysis.vertices, dtype=np.float64),
            np.asarray(analysis.faces, dtype=np.int32),
            resolution=settings.watertight_resolution,
            seed=settings.random_seed,
        )
        proxy = _pcu_mesh(pv, pf)
        if len(proxy.faces) > settings.watertight_resolution:
            dv, df, _, _ = pcu.decimate_triangle_mesh(
                np.ascontiguousarray(proxy.vertices, dtype=np.float64),
                np.ascontiguousarray(proxy.faces, dtype=np.int32),
                settings.watertight_resolution,
                decimation_heuristic='shortest_edge',
            )
            proxy = _pcu_mesh(dv, df)
        sample = np.asarray(proxy.vertices)
        if len(sample) > settings.sample_count:
            rng = np.random.default_rng(settings.random_seed)
            sample = sample[rng.choice(len(sample), settings.sample_count, replace=False)]
        distances, _, _ = pcu.signed_distance_to_mesh(
            np.ascontiguousarray(sample, dtype=np.float64),
            np.ascontiguousarray(vertices, dtype=np.float64),
            np.ascontiguousarray(faces, dtype=np.int32),
        )
        repair_error = float(np.percentile(np.abs(distances), 99))
        limit = settings.max_repair_error_cells / settings.grid_resolution
        if repair_error > limit:
            raise ValueError(
                f"Watertight repair changed the surface by {repair_error:.5f}; limit is {limit:.5f}. "
                "Repair the source mesh before voxelization."
            )
        notes.append("A watertight analysis proxy was generated; the original surface remains the geometry reference.")
    transform = np.eye(4)
    transform[:3, :3] *= 1 / scale
    transform[:3, 3] = offset
    return LoadedMeshes(
        mesh, analysis, proxy, repair_error, int(input_components), face_prior,
        face_part_ids, face_component_ids
    ), {
        "original_center": center.tolist(),
        "original_scale": scale,
        "transform": transform.tolist(),
        "inverse_transform": np.linalg.inv(transform).tolist(),
        "warnings": notes,
        "source_watertight": bool(mesh.is_watertight),
        "proxy_watertight": bool(proxy.is_watertight),
        "repair_error": repair_error,
        "input_components": int(input_components),
    }
