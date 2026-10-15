"""Precomputed geometric fields. Voxel requests only coarsen cached data."""
import numpy as np
import point_cloud_utils as pcu
from scipy import ndimage

from config import settings
from geometry.curvature import vertex_curvature, robust_normalize
from octree.topology import protected_gap_mask, silhouette_gap_mask


class GeometryAnalysis:
    def __init__(self, meshes, truth):
        self.meshes = meshes
        self.mesh = meshes.original
        self.truth = truth
        self.warnings = []
        if truth.removed_floating_cells:
            self.warnings.append(
                f"Removed {truth.removed_floating_cells} disconnected depth-5 cells; only the main component is retained."
            )
        n = settings.grid_resolution
        grid = np.indices((n, n, n)).reshape(3, -1).T
        centers = np.ascontiguousarray((grid + 0.5) / n, dtype=np.float64)
        vertices = np.ascontiguousarray(meshes.original.vertices, dtype=np.float64)
        faces = np.ascontiguousarray(meshes.original.faces, dtype=np.int32)
        distances, face_ids, _ = pcu.signed_distance_to_mesh(
            centers, vertices, faces,
        )
        self.signed_distance = distances.reshape((n, n, n)) * n
        self.surface_error = np.abs(distances).reshape((n, n, n)) * n
        normals = np.asarray(meshes.original.face_normals)[np.asarray(face_ids, dtype=np.int64)]
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        self.cell_normals = (normals / np.maximum(lengths, 1e-12)).reshape((n, n, n, 3))
        self.part_feature_prior = meshes.face_feature_prior[np.asarray(face_ids, dtype=np.int64)].reshape((n, n, n))
        self.cell_part_ids = meshes.face_part_ids[np.asarray(face_ids, dtype=np.int64)].reshape((n, n, n))
        self.cell_component_ids = meshes.face_component_ids[np.asarray(face_ids, dtype=np.int64)].reshape((n, n, n))
        self.component_adjacency = self._component_adjacency()
        self.component_gap = protected_gap_mask(
            truth.occupied, self.cell_component_ids, self.component_adjacency
        )
        self.silhouette_gap = silhouette_gap_mask(truth.occupied)
        self.protected_gap = self.component_gap | self.silhouette_gap
        radius = ndimage.distance_transform_edt(truth.occupied)
        local_radius = ndimage.maximum_filter(radius, size=9, mode='nearest')
        self.thin_risk = np.clip(2.0 / np.maximum(local_radius, 1.0), 0.0, 1.0)
        self.vertex_curvature = vertex_curvature(meshes.analysis)
        self.saliency = self._build_saliency()
        self.heatmap_data = self._heatmap()

    def _component_adjacency(self):
        """Pairs of original components that genuinely touch on the truth grid."""
        surface = self.truth.surface
        adjacency = set()
        for component_id in np.unique(self.cell_component_ids[surface]):
            mask = surface & (self.cell_component_ids == component_id)
            neighbours = np.unique(
                self.cell_component_ids[ndimage.binary_dilation(mask, iterations=1) & surface]
            )
            for neighbour in neighbours:
                adjacency.add(tuple(sorted((int(component_id), int(neighbour)))))
        return adjacency

    def _build_saliency(self):
        """View-independent, multi-scale geometric feature score on the truth grid.

        Smooth, continuous curvature is intentionally weak.  Part junctions,
        abrupt normal changes, concavity and small contrasting components are
        strong: these correspond to eyes, muzzle, ears and limb attachments.
        """
        surface = self.truth.surface.astype(np.float64)
        means = []
        for size in (3, 7):
            count = ndimage.uniform_filter(surface, size=size, mode='nearest')
            mean = np.stack([
                ndimage.uniform_filter(self.cell_normals[..., axis] * surface, size=size, mode='nearest')
                / np.maximum(count, 1e-8)
                for axis in range(3)
            ], axis=-1)
            means.append(mean / np.maximum(np.linalg.norm(mean, axis=-1, keepdims=True), 1e-8))
        local_dot = np.abs(np.sum(self.cell_normals * means[0], axis=-1))
        scale_dot = np.abs(np.sum(means[0] * means[1], axis=-1))
        normal_edge = np.maximum(
            np.clip((1.0 - local_dot) / 0.12, 0.0, 1.0),
            np.clip((1.0 - scale_dot) / 0.18, 0.0, 1.0),
        )

        # Count distinct source parts in a one-cell surface neighbourhood.
        # This is a semantic-free junction detector: it reacts at ear/head,
        # muzzle/head and eye/head intersections, not on the smooth head back.
        surface_mask = surface.astype(bool)
        junction = np.zeros(surface.shape, dtype=np.float64)
        for part_id in np.unique(self.cell_part_ids[surface.astype(bool)]):
            part_surface = (self.cell_part_ids == part_id) & surface_mask
            other_surface = (self.cell_part_ids != part_id) & surface_mask
            contact = (
                ndimage.binary_dilation(part_surface, iterations=1)
                & ndimage.binary_dilation(other_surface, iterations=1)
            )
            if part_surface.any():
                priority = float(np.max(self.part_feature_prior[part_surface]))
                junction = np.maximum(junction, contact * priority)
        junction = ndimage.maximum_filter(junction, size=3)
        self.junction_score = junction

        # A Laplacian of signed distance highlights ridges, tips and concave
        # facial transitions.  The distance-to-surface residual is the local
        # cube fitting term.
        ridge = robust_normalize(np.abs(ndimage.laplace(self.signed_distance)))
        fit = np.clip(ndimage.maximum_filter(self.surface_error, size=3) / 1.5, 0.0, 1.0)
        min_axis_dot = np.min(np.abs(self.cell_normals), axis=-1)
        silhouette = np.clip((0.34 - min_axis_dot) / 0.34, 0.0, 1.0)

        self.normal_edge = normal_edge
        self.ridge_feature = ridge * np.maximum(normal_edge, 0.2)
        self.fit_feature = fit
        self.silhouette_feature = silhouette
        self.saliency = self.complexity_field(
            settings.curvature_weight, settings.normal_weight, settings.thickness_weight
        )
        return self.saliency

    def complexity_field(self, curvature_weight, normal_weight, thickness_weight):
        """Compose cached feature channels using live UI weights."""
        thin_gate = self.thin_risk * np.maximum(self.junction_score, self.normal_edge)
        raw = (
            0.42 * self.junction_score
            + 0.25 * self.part_feature_prior
            + 0.60 * float(normal_weight) * self.normal_edge
            + 0.25 * float(curvature_weight) * self.ridge_feature
            + 0.15 * float(curvature_weight) * self.fit_feature
            + 0.10 * float(thickness_weight) * thin_gate
            + 0.02 * self.silhouette_feature
        )
        saliency = np.clip(raw, 0.0, 1.0) * self.truth.surface
        # Spread a feature only to its immediate neighbourhood.  This creates
        # coherent small-brick patches instead of isolated one-cell noise.
        return ndimage.maximum_filter(saliency, size=3) * self.truth.occupied

    def _heatmap(self):
        mesh = self.meshes.analysis
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        n = settings.grid_resolution
        ids = np.clip((vertices * n).astype(int), 0, n - 1)
        thickness = self.thin_risk[tuple(ids.T)]
        saliency = self.saliency[tuple(ids.T)]
        junction = self.junction_score[tuple(ids.T)]
        return {
            "vertices": vertices.astype(np.float32).round(6).tolist(),
            "faces": np.asarray(mesh.faces, dtype=np.int32).tolist(),
            "curvature": robust_normalize(self.vertex_curvature).round(5).tolist(),
            "saliency": saliency.round(5).tolist(),
            "junction": junction.round(5).tolist(),
            "thickness": thickness.round(5).tolist(),
            "thickness_coverage": 1.0,
        }
