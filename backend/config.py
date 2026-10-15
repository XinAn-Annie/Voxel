from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 40 * 1024 * 1024
    # Depth 5 is the absolute octree limit for printable output.
    max_depth: int = 5
    base_depth: int = 2
    grid_resolution: int = 32
    analysis_target_faces: int = 80_000
    watertight_resolution: int = 40_000
    max_repair_error_cells: float = 0.5
    max_false_fill_ratio: float = 0.0
    max_normal_angle_deg: float = 30.0
    target_depth5_ratio: float = 0.10
    curvature_refine_edge: float = 0.15
    curvature_refine_faces: int = 40_000
    curvature_radius: int = 3
    percentile_low: int = 5
    percentile_high: int = 95
    sample_count: int = 10_000
    random_seed: int = 7
    ray_epsilon: float = 0.00001
    surface_epsilon: float = 1e-9
    thickness_neighbors: int = 8
    thickness_safe_ratio: float = 0.5
    thickness_ratio_span: float = 1.0
    min_voxel_size: float = 0.0
    # Print constraints are expressed in the final assembled model, not in
    # whatever unit/scale happened to be present in the source GLB.
    target_model_size_mm: float = 320.0
    min_printed_voxel_mm: float = 10.0
    # Kept for compatibility with older callers; it is no longer used to
    # decide the printable minimum because GLB source scale is not print size.
    min_voxel_size_m: float = 0.01
    split_threshold: float = 0.65
    curvature_weight: float = 0.40
    thickness_weight: float = 0.10
    normal_weight: float = 0.25
    geometry_error_weight: float = 0.25
    surface_distance_ratio: float = 0.38
    open_surface_distance_ratio: float = 0.15
    fine_curvature_variation_threshold: float = 0.12
    curvature_variation_gain: float = 1.5
    max_cached_models: int = 3
    analysis_workers: int = 1


settings = Settings()
