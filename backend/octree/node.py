from dataclasses import dataclass, field
from enum import Enum


class NodeState(str, Enum):
    EMPTY = "EMPTY"
    INTERIOR = "INTERIOR"
    SURFACE = "SURFACE"


@dataclass(slots=True)
class AdaptiveOctreeNode:
    origin: tuple
    size: float
    depth: int
    state: NodeState
    curvature_score: float = 0.0
    curvature_variation_score: float = 0.0
    thickness_score: float = 0.0
    normal_score: float = 0.0
    geometry_error_score: float = 0.0
    surface_distance_ratio: float = 0.0
    center_inside: bool = False
    importance_score: float = 0.0
    children: list = field(default_factory=list)

    @property
    def is_leaf(self):
        return not self.children

    @property
    def center(self):
        return tuple(v + self.size / 2 for v in self.origin)
