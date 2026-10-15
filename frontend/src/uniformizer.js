const EPSILON = 1e-7;

function close(a, b) {
  return Math.abs(a - b) <= EPSILON * Math.max(1, Math.abs(a), Math.abs(b));
}

function bounds(voxels) {
  const result = [Infinity, Infinity, Infinity, -Infinity, -Infinity, -Infinity];
  for (const voxel of voxels) {
    const half = voxel.size / 2;
    result[0] = Math.min(result[0], voxel.x - half);
    result[1] = Math.min(result[1], voxel.y - half);
    result[2] = Math.min(result[2], voxel.z - half);
    result[3] = Math.max(result[3], voxel.x + half);
    result[4] = Math.max(result[4], voxel.y + half);
    result[5] = Math.max(result[5], voxel.z + half);
  }
  return result;
}

const cellKey = (x, y, z) => `${x},${y},${z}`;

export function uniformizeVoxels(adaptiveVoxels, colorData) {
  if (!adaptiveVoxels?.length) throw new Error('Uniformization failed: no adaptive voxels.');
  if (!colorData) throw new Error('Uniformization failed: voxel colors are not ready.');
  const minSize = Math.min(...adaptiveVoxels.map(voxel => voxel.size));
  if (!(minSize > 0)) throw new Error('Uniformization failed: invalid min_size.');

  const uniformVoxels = [], occupied = new Map();
  let expectedCells = 0, beforeVolume = 0;
  adaptiveVoxels.forEach((voxel, sourceIndex) => {
    const ratio = Math.round(voxel.size / minSize);
    if (ratio < 1 || !close(voxel.size, ratio * minSize)) throw new Error(`Uniformization failed: voxel ${sourceIndex} size is not an integer multiple of min_size.`);
    const center = [voxel.x, voxel.y, voxel.z];
    const lower = center.map(value => Math.round((value - voxel.size / 2) / minSize));
    for (let axis = 0; axis < 3; axis++) if (!close(lower[axis] * minSize, center[axis] - voxel.size / 2)) throw new Error(`Uniformization failed: voxel ${sourceIndex} is not aligned to the min_size grid.`);
    const sourceVoxelId = voxel.source_voxel_id ?? sourceIndex;
    expectedCells += ratio ** 3; beforeVolume += voxel.size ** 3;
    for (let ix = 0; ix < ratio; ix++) for (let iy = 0; iy < ratio; iy++) for (let iz = 0; iz < ratio; iz++) {
      const gx = lower[0] + ix, gy = lower[1] + iy, gz = lower[2] + iz, key = cellKey(gx, gy, gz);
      if (occupied.has(key)) throw new Error(`Uniformization failed: overlap at integer cell ${key}.`);
      occupied.set(key, sourceIndex);
      uniformVoxels.push({
        x:(gx + .5) * minSize, y:(gy + .5) * minSize, z:(gz + .5) * minSize,
        size:minSize, depth:Math.round(Math.log2(1 / minSize)), source_voxel_id:sourceVoxelId,
        source_voxel_index:sourceIndex, parent_ratio:ratio, child_grid:[ix, iy, iz],
      });
    }
  });
  if (occupied.size !== expectedCells || uniformVoxels.length !== expectedCells) throw new Error('Uniformization failed: gap detected in the child partition.');
  for (const child of uniformVoxels) {
    const key = cellKey(Math.round(child.x / minSize - .5), Math.round(child.y / minSize - .5), Math.round(child.z / minSize - .5));
    if (occupied.get(key) !== child.source_voxel_index) throw new Error(`Uniformization failed: gap in source voxel ${child.source_voxel_id}.`);
  }
  const afterVolume = uniformVoxels.length * minSize ** 3;
  if (!close(beforeVolume, afterVolume)) throw new Error('Uniformization failed: volume changed.');
  const beforeBounds = bounds(adaptiveVoxels), afterBounds = bounds(uniformVoxels);
  if (!beforeBounds.every((value, index) => close(value, afterBounds[index]))) throw new Error('Uniformization failed: bounding box changed.');
  return {voxels:uniformVoxels,minSize,validation:{volume_equal:true,bounding_box_equal:true,color_set_equal:null,no_overlap:true,no_gap:true,before_volume:beforeVolume,after_volume:afterVolume,before_bounds:beforeBounds,after_bounds:afterBounds}};
}
