"""Generate the five included, original geometry fixtures (no external assets)."""
from pathlib import Path
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]


def animal():
    from skimage.measure import marching_cubes
    # Smooth implicit union of body, head, snout, ears, four legs and a thin tail.
    axis = np.linspace(-1.5, 1.25, 96)
    x, y, z = np.meshgrid(axis, axis, axis, indexing='ij')
    parts = [
        ((0, 0, 0), (.62, .36, .32)),
        ((.52, .30, 0), (.29, .29, .26)),
        ((.76, .28, 0), (.22, .13, .14)),
        ((.49, .61, -.14), (.09, .26, .065)),
        ((.49, .61, .14), (.09, .26, .065)),
        ((-.96, .12, 0), (.43, .055, .055)),
    ]
    for lx in [-.39, .37]:
        for lz in [-.20, .20]:
            parts.append(((lx, -.38, lz), (.085, .34, .085)))
    field = np.full(x.shape, np.inf)
    for center, radii in parts:
        value = ((x-center[0])/radii[0])**2 + ((y-center[1])/radii[1])**2 + ((z-center[2])/radii[2])**2 - 1
        field = np.minimum(field, value)
    vertices, faces, _, _ = marching_cubes(field, level=0, spacing=(axis[1]-axis[0],)*3)
    mesh = trimesh.Trimesh(vertices=vertices + axis[0], faces=faces, process=True)
    mesh.fix_normals()
    return mesh


def generate():
    samples = ROOT / 'samples'
    samples.mkdir(exist_ok=True)
    box = trimesh.creation.box(extents=[.7, .7, .7])
    rod = trimesh.creation.box(extents=[.07, .07, .65])
    rod.apply_translation([0, 0, .665])
    models = {
        'cube': trimesh.creation.box(),
        'sphere': trimesh.creation.icosphere(subdivisions=2),
        'cube_thin_rod': trimesh.util.concatenate([box, rod]),
        'cone': trimesh.creation.cone(radius=.45, height=1, sections=32),
        'animal': animal(),
    }
    for name, mesh in models.items():
        mesh.export(samples / f'{name}.glb')
        print(name, len(mesh.faces), 'faces', flush=True)


if __name__ == '__main__':
    generate()
