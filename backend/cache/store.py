from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from config import settings


@dataclass
class CachedModel:
    status: str = 'processing'
    stage: str = 'Queued'
    error: str = ''
    mesh: object = None
    meshes: object = None
    truth: object = None
    transform: dict = field(default_factory=dict)
    geometry: object = None
    octree: object = None
    candidate_nodes: int = 0
    analysis_ms: float = 0
    analysis_runs: int = 0


class ModelCache:
    def __init__(self):
        self.data = OrderedDict()
        self.lock = Lock()

    def reserve(self, key):
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key], False
            if len(self.data) >= settings.max_cached_models:
                eligible = next((k for k, v in self.data.items() if v.status != 'processing'), None)
                if eligible is None:
                    raise ValueError('Analysis queue is full. Wait for a model to finish.')
                self.data.pop(eligible)
            model = CachedModel()
            self.data[key] = model
            return model, True

    def get(self, key):
        with self.lock:
            model = self.data.get(key)
            if model is not None:
                self.data.move_to_end(key)
            return model


cache = ModelCache()
