from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from api.routes import router

app = FastAPI(title="Adaptive Voxelizer API")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api")

# A release ZIP includes this build, so running Python alone serves the whole app.
dist = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
samples = Path(__file__).resolve().parents[1] / 'samples'
if samples.is_dir():
    app.mount('/samples', StaticFiles(directory=samples), name='samples')
if dist.is_dir():
    app.mount('/', StaticFiles(directory=dist, html=True), name='website')
