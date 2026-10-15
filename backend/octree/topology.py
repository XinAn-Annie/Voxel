import numpy as np
from scipy import ndimage


CONNECTIVITY_6 = ndimage.generate_binary_structure(3, 1)


def component_count(mask):
    if not np.any(mask):
        return 0
    return int(ndimage.label(mask, CONNECTIVITY_6)[1])


def has_separated_source_components(component_ids, surface, adjacency):
    """True when a block spans source components that do not touch each other."""
    ids = [int(value) for value in np.unique(component_ids[surface])]
    for index, first in enumerate(ids):
        for second in ids[index + 1:]:
            if tuple(sorted((first, second))) not in adjacency:
                return True
    return False


def protected_gap_mask(occupied, component_ids, adjacency, radius=6):
    """Exterior cells bracketed by real shape along any axis.

    These are meaningful gaps between ears, limbs or other protrusions. A
    coarse parent may approximate an outside contour, but may never fill these
    channels and turn separated structures into one bridge.
    """
    occupied = np.asarray(occupied, dtype=bool)
    component_ids = np.asarray(component_ids, dtype=np.int32)
    protected = np.zeros_like(occupied)
    component_count_total = int(component_ids.max(initial=0)) + 1
    adjacent = np.zeros((component_count_total, component_count_total), dtype=bool)
    for first, second in adjacency:
        adjacent[first, second] = True
        adjacent[second, first] = True
    for axis in range(3):
        negative_candidates = []
        positive_candidates = []
        for distance in range(1, radius + 1):
            negative = np.zeros_like(occupied)
            positive = np.zeros_like(occupied)
            negative_ids = np.zeros_like(component_ids)
            positive_ids = np.zeros_like(component_ids)
            source = [slice(None)] * 3
            target = [slice(None)] * 3
            source[axis] = slice(0, -distance)
            target[axis] = slice(distance, None)
            negative[tuple(target)] = occupied[tuple(source)]
            negative_ids[tuple(target)] = component_ids[tuple(source)]
            source[axis] = slice(distance, None)
            target[axis] = slice(0, -distance)
            positive[tuple(target)] = occupied[tuple(source)]
            positive_ids[tuple(target)] = component_ids[tuple(source)]
            negative_candidates.append((negative, negative_ids))
            positive_candidates.append((positive, positive_ids))
        for negative, negative_ids in negative_candidates:
            for positive, positive_ids in positive_candidates:
                bracketed = (~occupied) & negative & positive
                if bracketed.any():
                    protected |= bracketed & ~adjacent[negative_ids, positive_ids]
    return protected


def silhouette_gap_mask(occupied, radius=6):
    """Concave gaps visible in any principal-axis silhouette.

    Unlike a generic silhouette constraint, only empty pixels bracketed by
    occupied pixels are protected. Convex head/body outlines may therefore
    stay coarse, while the notch between two ears cannot be covered by a
    large parent cube at another depth coordinate.
    """
    occupied = np.asarray(occupied, dtype=bool)
    protected = np.zeros_like(occupied)
    for view_axis in range(3):
        projection = occupied.any(axis=view_axis)
        gap_2d = np.zeros_like(projection)
        for axis in range(2):
            negative = np.zeros_like(projection)
            positive = np.zeros_like(projection)
            for distance in range(1, radius + 1):
                source = [slice(None)] * 2
                target = [slice(None)] * 2
                source[axis] = slice(0, -distance)
                target[axis] = slice(distance, None)
                negative[tuple(target)] |= projection[tuple(source)]
                source[axis] = slice(distance, None)
                target[axis] = slice(0, -distance)
                positive[tuple(target)] |= projection[tuple(source)]
            gap_2d |= (~projection) & negative & positive
        lifted = np.broadcast_to(np.expand_dims(gap_2d, axis=view_axis), occupied.shape)
        protected |= lifted & ~occupied
    return protected


def normal_spread_degrees(normals):
    if len(normals) < 2:
        return 0.0
    mean = normals.mean(axis=0)
    length = np.linalg.norm(mean)
    if length < 1e-12:
        return 180.0
    dots = np.clip(normals @ (mean / length), -1.0, 1.0)
    return float(np.degrees(np.arccos(dots.min())))


def outside_channel(mask):
    """Reject a merge if empty truth cells form a tunnel across its block."""
    empty = ~mask
    labels, count = ndimage.label(empty, CONNECTIVITY_6)
    for label in range(1, count + 1):
        part = labels == label
        if ((part[0].any() and part[-1].any()) or
                (part[:, 0].any() and part[:, -1].any()) or
                (part[:, :, 0].any() and part[:, :, -1].any())):
            return True
    return False


def rasterize(nodes, resolution=32):
    grid = np.zeros((resolution,) * 3, dtype=bool)
    for depth, x, y, z, *_ in nodes:
        width = resolution // (2 ** depth)
        lo = np.asarray((x, y, z)) * width
        hi = lo + width
        grid[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] = True
    return grid


def bridge_false_mask(output, truth):
    """Return approximation cells that locally join separate truth regions."""
    false_fill = output & ~truth
    labels, count = ndimage.label(false_fill, CONNECTIVITY_6)
    unsafe = np.zeros_like(false_fill)
    for label in range(1, count + 1):
        region = labels == label
        coordinates = np.argwhere(region)
        lo = np.maximum(coordinates.min(axis=0) - 1, 0)
        hi = np.minimum(coordinates.max(axis=0) + 2, truth.shape)
        slices = tuple(slice(int(lo[i]), int(hi[i])) for i in range(3))
        local_region = region[slices]
        local_truth = truth[slices]
        truth_labels, _ = ndimage.label(local_truth, CONNECTIVITY_6)
        contacts = ndimage.binary_dilation(local_region, structure=CONNECTIVITY_6) & local_truth
        touched = np.unique(truth_labels[contacts])
        touched = touched[touched != 0]
        if len(touched) > 1:
            unsafe |= region
    return unsafe
