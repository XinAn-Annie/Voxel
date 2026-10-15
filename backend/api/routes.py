import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cache.store import cache
from config import settings
from meshio.mesh_loader import load_mesh
from geometry.importance import GeometryAnalysis
from geometry.voxel_truth import build_voxel_truth
from octree.feature_planner import plan_features
from octree.validation import serialize, validate

router = APIRouter()
executor = ThreadPoolExecutor(max_workers=settings.analysis_workers, thread_name_prefix='geometry')


class VoxelRequest(BaseModel):
    model_id: str
    min_voxel_size: float = Field(default=settings.min_voxel_size, ge=0, le=0.10)
    min_voxel_size_cm: float = Field(default=1.0, ge=1.0, le=10.0)
    # These values describe the intended printed object. They are deliberately
    # independent from the original GLB coordinate scale.
    target_model_size_mm: float = Field(default=settings.target_model_size_mm, gt=0, le=5000)
    min_printed_voxel_mm: float = Field(default=settings.min_printed_voxel_mm, ge=10.0, le=100.0)
    split_threshold: float = Field(default=settings.split_threshold, ge=0, le=1)
    detail_level: float | None = Field(default=None, ge=0, le=1)
    curvature_weight: float = Field(default=settings.curvature_weight, ge=0, le=1)
    thickness_weight: float = Field(default=settings.thickness_weight, ge=0, le=1)
    normal_weight: float = Field(default=settings.normal_weight, ge=0, le=1)


def process_model(model, raw):
    start = time.perf_counter()
    try:
        model.stage = 'Cleaning and normalizing mesh'
        model.meshes, model.transform = load_mesh(raw)
        model.mesh = model.meshes.original
        model.stage = 'Building watertight depth-5 occupancy truth'
        model.truth = build_voxel_truth(model.meshes.proxy, model.meshes.original)
        model.stage = 'Computing SDF, normals, local error and EDT thickness'
        model.geometry = GeometryAnalysis(model.meshes, model.truth)
        model.candidate_nodes = int(model.truth.occupied.sum())
        model.analysis_ms = round((time.perf_counter() - start) * 1000, 1)
        model.analysis_runs += 1
        model.stage = 'Ready'
        model.status = 'ready'
    except Exception as exc:
        model.error = str(exc)
        model.stage = 'Analysis failed'
        model.status = 'error'


def get_model(model_id, ready=False):
    model = cache.get(model_id)
    if model is None:
        raise HTTPException(404, 'Model expired from cache. Upload it again.')
    if model.status == 'error':
        raise HTTPException(422, model.error)
    if ready and model.status != 'ready':
        raise HTTPException(409, 'Model is still processing.')
    return model


@router.get('/health')
def health():
    return {'status': 'ok', 'max_depth': settings.max_depth, 'cache_capacity': settings.max_cached_models}


@router.post('/upload', status_code=202)
async def upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith('.glb'):
        raise HTTPException(400, 'Only .glb files are supported')
    raw = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(413, 'GLB exceeds 40 MB')
    if raw[:4] != b'glTF':
        raise HTTPException(400, 'Invalid GLB header')
    model_id = hashlib.sha256(raw).hexdigest()[:20]
    try:
        model, created = cache.reserve(model_id)
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from exc
    if created:
        executor.submit(process_model, model, raw)
    return {'model_id': model_id, 'status': model.status}


@router.get('/models/{model_id}')
def model_status(model_id: str):
    model = get_model(model_id)
    return {
        'model_id': model_id, 'status': model.status, 'stage': model.stage,
        'warnings': model.transform.get('warnings', []) + (model.geometry.warnings if model.geometry else []),
        'transform': model.transform, 'candidate_nodes': model.candidate_nodes,
        'analysis_ms': model.analysis_ms, 'analysis_runs': model.analysis_runs,
    }


@router.get('/models/{model_id}/analysis')
def analysis(model_id: str):
    return JSONResponse(get_model(model_id, ready=True).geometry.heatmap_data)


def _effective_max_depth(target_model_size_mm: float, min_printed_voxel_mm: float) -> int:
    """Largest useful depth whose nominal cell edge remains above the print minimum."""
    depth = 0
    while (depth < settings.max_depth and
           target_model_size_mm / (2 ** (depth + 1)) >= min_printed_voxel_mm):
        depth += 1
    return depth


@router.post('/voxelize')
def voxelize(request: VoxelRequest):
    model = get_model(request.model_id, ready=True)
    start = time.perf_counter()
    # The normalized mesh occupies a unit box. Map the requested printed
    # dimensions onto that box; do not use the source GLB's original_scale as
    # a proxy for the final paper-model dimensions.
    printed_minimum_mm = max(
        settings.min_printed_voxel_mm,
        request.min_printed_voxel_mm,
        request.min_voxel_size_cm * 10.0,
    )
    allowed_max_depth = _effective_max_depth(request.target_model_size_mm, printed_minimum_mm)
    try:
        nodes = plan_features(model.geometry, request, allowed_max_depth)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    voxels = serialize(nodes)
    validation = validate(nodes, model.truth, model.geometry)
    depths = [v['depth'] for v in voxels]
    feature_count = sum(v.get('layer') == 'feature' for v in voxels)
    min_depth, max_depth = min(depths, default=0), max(depths, default=0)
    min_size = min((v['size'] for v in voxels), default=0)
    effective_model_size_mm = max(
        request.target_model_size_mm,
        printed_minimum_mm * (2 ** max_depth),
    )
    return JSONResponse({'voxels': voxels, 'stats': {
        'voxel_count': len(voxels), 'min_depth': min_depth, 'max_depth': max_depth,
        'structure_voxel_count': len(voxels) - feature_count,
        'feature_voxel_count': feature_count,
        'min_size': min_size,
        'min_size_mm': round(min_size * effective_model_size_mm, 3),
        'min_size_cm': round(min_size * effective_model_size_mm / 10.0, 3),
        'target_model_size_mm': effective_model_size_mm,
        'requested_model_size_mm': request.target_model_size_mm,
        'print_scale_adjusted': effective_model_size_mm > request.target_model_size_mm,
        'min_printed_voxel_mm': printed_minimum_mm,
        'effective_max_depth': allowed_max_depth,
        'compute_ms': round((time.perf_counter() - start) * 1000, 1),
        'analysis_runs': model.analysis_runs,
        **validation,
    }})
