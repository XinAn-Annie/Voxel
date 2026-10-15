import * as THREE from 'three';
import { computeBoundsTree, disposeBoundsTree, getTriangleHitPointInfo } from 'three-mesh-bvh';

THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;

export const FACE_AXES = [
  { n:[1,0,0], u:[0,0,-1], v:[0,1,0] }, { n:[-1,0,0], u:[0,0,1], v:[0,1,0] },
  { n:[0,1,0], u:[1,0,0], v:[0,0,-1] }, { n:[0,-1,0], u:[1,0,0], v:[0,0,1] },
  { n:[0,0,1], u:[1,0,0], v:[0,1,0] }, { n:[0,0,-1], u:[-1,0,0], v:[0,1,0] },
].map(f => ({ n:new THREE.Vector3(...f.n), u:new THREE.Vector3(...f.u), v:new THREE.Vector3(...f.v) }));

const DEFAULT = new THREE.Color('#a6b3bd');
const localPoint = new THREE.Vector3(), worldPoint = new THREE.Vector3(), samplePoint = new THREE.Vector3(), mappedSamplePoint = new THREE.Vector3(), hitWorld = new THREE.Vector3();
const rayOrigin = new THREE.Vector3(), rayDirection = new THREE.Vector3(), toSurface = new THREE.Vector3(), surfaceNormal = new THREE.Vector3();
const worldRay = new THREE.Ray(), localRay = new THREE.Ray();
const color = new THREE.Color(), uv = new THREE.Vector2();
const FALLBACK_NORMAL_ALIGNMENT_MIN = 0.35;
const FALLBACK_DIRECTION_ALIGNMENT_MIN = 0.5;

function imageSampler(texture, cache) {
  if (cache.has(texture.uuid)) return cache.get(texture.uuid);
  const image = texture.image;
  let sampler = null;
  try {
    if (image?.data && image.width && image.height && image.data.length >= image.width * image.height * 4) {
      sampler = { data:image.data, width:image.width, height:image.height };
    } else if (image?.width > 0 && image?.height > 0) {
      const scale = Math.min(1, 1024 / Math.max(image.width, image.height));
      const width = Math.max(1, Math.round(image.width * scale)), height = Math.max(1, Math.round(image.height * scale));
      const canvas = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(width,height) : document.createElement('canvas');
      canvas.width=width; canvas.height=height;
      const context=canvas.getContext('2d',{willReadFrequently:true}); context.drawImage(image,0,0,width,height);
      sampler={data:context.getImageData(0,0,width,height).data,width,height};
    }
  } catch { sampler=null; }
  cache.set(texture.uuid,sampler); return sampler;
}

function sampleTexture(texture, sampler) {
  texture.transformUv(uv);
  const x=Math.min(sampler.width-1,Math.max(0,Math.floor(uv.x*sampler.width)));
  const y=Math.min(sampler.height-1,Math.max(0,Math.floor(uv.y*sampler.height)));
  const i=(y*sampler.width+x)*4;
  return [sampler.data[i],sampler.data[i+1],sampler.data[i+2]];
}

function linearColorBytes(source) {
  color.copy(source || DEFAULT).convertLinearToSRGB();
  return [Math.round(color.r*255),Math.round(color.g*255),Math.round(color.b*255)];
}

export function prepareColorSource(root) {
  const meshes=[], imageCache=new Map(); root.updateMatrixWorld(true);
  root.traverse(mesh => {
    if (!mesh.isMesh || !mesh.geometry?.getAttribute('position')) return;
    if (!mesh.geometry.index) {
      const count=mesh.geometry.getAttribute('position').count;
      mesh.geometry.setIndex(Array.from({length:count},(_,i)=>i));
    }
    mesh.geometry.computeBoundsTree({targetLeafSize:12});
    const materials=Array.isArray(mesh.material)?mesh.material:[mesh.material];
    const worldBounds=new THREE.Box3().setFromObject(mesh);
    meshes.push({
      mesh, materials, worldBounds,
      inverseWorld:mesh.matrixWorld.clone().invert(),
      normalMatrix:new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld),
      orientationSign:Math.sign(mesh.matrixWorld.determinant()) || 1,
    });
  });
  return {root,meshes,imageCache};
}

export function disposeColorSource(source) {
  source?.meshes.forEach(({mesh}) => mesh.geometry.disposeBoundsTree?.());
}

function hitInfo(entry, localHit) {
  const info=getTriangleHitPointInfo(localHit.point,entry.mesh.geometry,localHit.faceIndex);
  surfaceNormal.copy(info.face.normal).applyMatrix3(entry.normalMatrix).multiplyScalar(entry.orientationSign).normalize();
  return {entry,info,normalDot:surfaceNormal.dot(currentFaceNormal)};
}

const currentFaceNormal=new THREE.Vector3();

// Mapping-from-objects path: start outside this voxel face and project inward
// along its normal. The closest acceptable ray hit wins; no nearest-triangle
// query is performed before this directional projection.
function raycastSurface(source, point, face, maxDistance) {
  currentFaceNormal.copy(face.n);
  rayOrigin.copy(point).addScaledVector(face.n,maxDistance);
  rayDirection.copy(face.n).negate();
  worldRay.set(rayOrigin,rayDirection);
  let best=null,bestRayDistance=Infinity;
  for (const entry of source.meshes) {
    if(!worldRay.intersectsBox(entry.worldBounds))continue;
    localRay.copy(worldRay).applyMatrix4(entry.inverseWorld);
    const hit=entry.mesh.geometry.boundsTree.raycastFirst(localRay,THREE.DoubleSide);
    if(!hit)continue;
    hitWorld.copy(hit.point).applyMatrix4(entry.mesh.matrixWorld);
    const pointDistance=hitWorld.distanceTo(point),rayDistance=hitWorld.distanceTo(rayOrigin);
    if(pointDistance>maxDistance||rayDistance>maxDistance*2||rayDistance>=bestRayDistance)continue;
    const result=hitInfo(entry,hit);
    bestRayDistance=rayDistance;
    best=result;
  }
  // Do not skip through the first directional hit to a farther component.
  // The ray itself establishes the corresponding visible source surface.
  return best;
}

// Only used when projection misses. Distance, surface-normal alignment and
// point-to-surface direction are all bounded to prevent sampling another limb
// or the reverse side of the model.
function nearestSurfaceFallback(source,point,face,maxDistance) {
  currentFaceNormal.copy(face.n);
  let best=null,bestDistance=Infinity;
  for(const entry of source.meshes) {
    if(entry.worldBounds.distanceToPoint(point)>maxDistance)continue;
    localPoint.copy(point).applyMatrix4(entry.inverseWorld);
    const hit=entry.mesh.geometry.boundsTree.closestPointToPoint(localPoint,{});
    if(!hit)continue;
    hitWorld.copy(hit.point).applyMatrix4(entry.mesh.matrixWorld);
    const distance=hitWorld.distanceTo(point);
    if(distance>maxDistance||distance>=bestDistance)continue;
    const result=hitInfo(entry,hit);
    if(Math.abs(result.normalDot)<FALLBACK_NORMAL_ALIGNMENT_MIN)continue;
    if(distance>1e-7&&Math.abs(toSurface.copy(hitWorld).sub(point).normalize().dot(face.n))<FALLBACK_DIRECTION_ALIGNMENT_MIN)continue;
    bestDistance=distance;
    best=result;
  }
  return best;
}

function surfaceColor(source, point, face, rayDistance, fallbackDistance) {
  const surface=raycastSurface(source,point,face,rayDistance) || nearestSurfaceFallback(source,point,face,fallbackDistance);
  if(!surface)return null;
  const {entry,info}=surface, geometry=entry.mesh.geometry;
  const material=entry.materials[info.face.materialIndex] || entry.materials[0];
  if(material?.map && info.uv) {
    const sampler=imageSampler(material.map,source.imageCache);
    if(sampler) { uv.copy(info.uv); return sampleTexture(material.map,sampler); }
  }
  const vertexColors=geometry.getAttribute('color');
  if(vertexColors) {
    const {a,b,c}=info.face, q=info.barycoord;
    color.setRGB(
      vertexColors.getX(a)*q.x+vertexColors.getX(b)*q.y+vertexColors.getX(c)*q.z,
      vertexColors.getY(a)*q.x+vertexColors.getY(b)*q.y+vertexColors.getY(c)*q.z,
      vertexColors.getZ(a)*q.x+vertexColors.getZ(b)*q.y+vertexColors.getZ(c)*q.z,
    );
    return linearColorBytes(color);
  }
  return linearColorBytes(material?.color || DEFAULT);
}

function occupancy(voxels) {
  const maxDepth=Math.max(0,...voxels.map(v=>v.depth)), resolution=2**maxDepth;
  const cells=new Int32Array(resolution**3); cells.fill(-1);
  voxels.forEach((v,index)=>{
    const width=Math.max(1,Math.round(v.size*resolution));
    const ox=Math.round((v.x-v.size/2)*resolution), oy=Math.round((v.y-v.size/2)*resolution), oz=Math.round((v.z-v.size/2)*resolution);
    for(let x=ox;x<ox+width;x++)for(let y=oy;y<oy+width;y++)for(let z=oz;z<oz+width;z++)cells[(x*resolution+y)*resolution+z]=index;
  });
  return {resolution,cells};
}

function exposed(grid, point, normal) {
  const q=worldPoint.copy(point).addScaledVector(normal,1/(grid.resolution*4));
  const x=Math.floor(q.x*grid.resolution),y=Math.floor(q.y*grid.resolution),z=Math.floor(q.z*grid.resolution);
  if(x<0||y<0||z<0||x>=grid.resolution||y>=grid.resolution||z>=grid.resolution)return true;
  return grid.cells[(x*grid.resolution+y)*grid.resolution+z]<0;
}

function atlasPixel(width,baseX,baseY,detail,face,x,y) {
  return ((baseY+Math.floor(face/3)*detail+y)*width+baseX+(face%3)*detail+x)*4;
}

function writeRgb(data,p,rgb) {
  data[p]=rgb[0];data[p+1]=rgb[1];data[p+2]=rgb[2];data[p+3]=255;
}

function mappingBounds(source,voxels) {
  const sourceBox=new THREE.Box3().setFromObject(source.root),voxelBox=new THREE.Box3();
  for(const voxel of voxels) {
    const half=voxel.size/2;
    voxelBox.expandByPoint(new THREE.Vector3(voxel.x-half,voxel.y-half,voxel.z-half));
    voxelBox.expandByPoint(new THREE.Vector3(voxel.x+half,voxel.y+half,voxel.z+half));
  }
  const sourceSize=sourceBox.getSize(new THREE.Vector3()),voxelSize=voxelBox.getSize(new THREE.Vector3());
  const sourceCenter=sourceBox.getCenter(new THREE.Vector3());
  const safeScale=(voxelExtent,sourceExtent)=>sourceExtent>1e-9?voxelExtent/sourceExtent:1;
  const scale=new THREE.Vector3(
    safeScale(voxelSize.x,sourceSize.x),
    safeScale(voxelSize.y,sourceSize.y),
    safeScale(voxelSize.z,sourceSize.z),
  );
  return {sourceSize,voxelSize,sourceCenter,scale};
}

function mapToSourceSpace(point,mapping) {
  return mappedSamplePoint.copy(point).sub(mapping.sourceCenter).divide(mapping.scale).add(mapping.sourceCenter);
}

function faceScale(face,scale) {
  return Math.abs(face.n.x)*scale.x+Math.abs(face.n.y)*scale.y+Math.abs(face.n.z)*scale.z;
}

function fillFaceFromMappedSamples(data,width,baseX,baseY,detail,face,state,stateBase,queue) {
  let head=0,tail=0;
  for(let index=0;index<detail*detail;index++)if(state[stateBase+index]===2)queue[tail++]=index;
  if(!tail)return false;
  const spread=(sourcePixel,next,nx,ny)=>{
    if(state[stateBase+next]!==1)return;
    const targetPixel=atlasPixel(width,baseX,baseY,detail,face,nx,ny);
    data[targetPixel]=data[sourcePixel];data[targetPixel+1]=data[sourcePixel+1];data[targetPixel+2]=data[sourcePixel+2];data[targetPixel+3]=255;
    state[stateBase+next]=2;queue[tail++]=next;
  };
  while(head<tail) {
    const current=queue[head++],x=current%detail,y=Math.floor(current/detail);
    const sourcePixel=atlasPixel(width,baseX,baseY,detail,face,x,y);
    if(x>0)spread(sourcePixel,current-1,x-1,y);
    if(x<detail-1)spread(sourcePixel,current+1,x+1,y);
    if(y>0)spread(sourcePixel,current-detail,x,y-1);
    if(y<detail-1)spread(sourcePixel,current+detail,x,y+1);
  }
  return true;
}

function sourceFallbackColor(source) {
  for(const entry of source.meshes)for(const material of entry.materials)if(material?.color)return linearColorBytes(material.color);
  return [255,255,255];
}

export async function sampleVoxelColors(source, voxels, detail, isCurrent=()=>true) {
  const maxTextureSize=8192, tileWidth=detail*3, tileHeight=detail*2;
  const columns=Math.max(1,Math.min(Math.floor(maxTextureSize/tileWidth),Math.ceil(Math.sqrt(Math.max(1,voxels.length)*tileHeight/tileWidth))));
  const rows=Math.max(1,Math.ceil(voxels.length/columns)), width=columns*tileWidth, height=rows*tileHeight;
  if(width>maxTextureSize||height>maxTextureSize)throw new Error('Color Detail 过高，颜色 atlas 超出显卡限制。');
  const data=new Uint8Array(width*height*4), origins=new Float32Array(voxels.length*2), grid=occupancy(voxels);
  const mapping=mappingBounds(source,voxels),samplesPerFace=detail*detail;
  // 0 = hidden/internal, 1 = exposed but unmapped, 2 = mapped/dilated.
  const state=new Uint8Array(voxels.length*6*samplesPerFace);
  const faceColors=new Float32Array(voxels.length*6*4);
  const defaultRgb=linearColorBytes(DEFAULT);
  let unmappedBeforeDilation=0;
  for(let i=0;i<voxels.length;i++) {
    if(!isCurrent())return null;
    const voxel=voxels[i], baseX=(i%columns)*tileWidth,baseY=Math.floor(i/columns)*tileHeight;
    origins[i*2]=baseX; origins[i*2+1]=baseY;
    const rayDistance=Math.min(.25,Math.max(voxel.size*1.5,.025));
    const fallbackDistance=Math.min(.08,Math.max(voxel.size*.35,.008));
    for(let f=0;f<6;f++) {
      const face=FACE_AXES[f],axisScale=Math.max(1e-9,faceScale(face,mapping.scale));
      const stateBase=(i*6+f)*samplesPerFace,faceColorBase=(i*6+f)*4;
      for(let y=0;y<detail;y++)for(let x=0;x<detail;x++) {
        const du=(x+.5)/detail-.5,dv=(y+.5)/detail-.5,index=y*detail+x;
        const point=samplePoint.set(voxel.x,voxel.y,voxel.z).addScaledVector(face.n,voxel.size/2).addScaledVector(face.u,du*voxel.size).addScaledVector(face.v,dv*voxel.size);
        const isExposed=exposed(grid,point,face.n);
        const mappedPoint=isExposed?mapToSourceSpace(point,mapping):point;
        const rgb=isExposed?surfaceColor(source,mappedPoint,face,rayDistance/axisScale,fallbackDistance/Math.max(1e-9,Math.min(mapping.scale.x,mapping.scale.y,mapping.scale.z))):null;
        if(isExposed)state[stateBase+index]=rgb?2:1;
        if(isExposed&&!rgb)unmappedBeforeDilation++;
        if(rgb) {
          faceColors[faceColorBase]+=rgb[0];faceColors[faceColorBase+1]+=rgb[1];faceColors[faceColorBase+2]+=rgb[2];faceColors[faceColorBase+3]++;
        }
        writeRgb(data,atlasPixel(width,baseX,baseY,detail,f,x,y),rgb || defaultRgb);
      }
    }
    const yieldEvery=Math.max(1,Math.floor(1536/(detail*detail)));
    if(i%yieldEvery===yieldEvery-1)await new Promise(resolve=>requestAnimationFrame(resolve));
  }

  // First dilate inside each voxel face. This preserves the same continuous
  // face and exactly the same normal before considering any neighboring face.
  const queue=new Int32Array(samplesPerFace),seedsByFace=Array.from({length:6},()=>[]),allSeeds=[];
  for(let i=0;i<voxels.length;i++)for(let f=0;f<6;f++) {
    const baseX=(i%columns)*tileWidth,baseY=Math.floor(i/columns)*tileHeight;
    const stateBase=(i*6+f)*samplesPerFace,faceColorBase=(i*6+f)*4,count=faceColors[faceColorBase+3];
    if(!count)continue;
    fillFaceFromMappedSamples(data,width,baseX,baseY,detail,f,state,stateBase,queue);
    const rgb=[faceColors[faceColorBase]/count,faceColors[faceColorBase+1]/count,faceColors[faceColorBase+2]/count];
    // Disconnected uncovered islands on the same face use that face's own
    // representative color rather than crossing to another body part.
    for(let index=0;index<samplesPerFace;index++)if(state[stateBase+index]===1) {
      writeRgb(data,atlasPixel(width,baseX,baseY,detail,f,index%detail,Math.floor(index/detail)),rgb);state[stateBase+index]=2;
    }
    const seed={voxel:i,rgb};seedsByFace[f].push(seed);allSeeds.push(seed);
  }

  // Entirely unmapped exposed faces borrow from the nearest mapped face with
  // the same normal. Only if none exists do we use the nearest mapped face of
  // any orientation; the final material/white fallback guarantees coverage.
  const fallbackRgb=sourceFallbackColor(source);
  for(let i=0;i<voxels.length;i++)for(let f=0;f<6;f++) {
    const stateBase=(i*6+f)*samplesPerFace;
    let needsColor=false;
    for(let index=0;index<samplesPerFace;index++)if(state[stateBase+index]===1){needsColor=true;break;}
    if(!needsColor)continue;
    const candidates=seedsByFace[f].length?seedsByFace[f]:allSeeds;
    let nearest=null,nearestDistance=Infinity;
    for(const candidate of candidates) {
      const a=voxels[i],b=voxels[candidate.voxel],distance=(a.x-b.x)**2+(a.y-b.y)**2+(a.z-b.z)**2;
      if(distance<nearestDistance){nearestDistance=distance;nearest=candidate;}
    }
    const rgb=nearest?.rgb || fallbackRgb,baseX=(i%columns)*tileWidth,baseY=Math.floor(i/columns)*tileHeight;
    for(let index=0;index<samplesPerFace;index++)if(state[stateBase+index]===1) {
      writeRgb(data,atlasPixel(width,baseX,baseY,detail,f,index%detail,Math.floor(index/detail)),rgb);state[stateBase+index]=2;
    }
  }
  let unmappedAfterDilation=0;
  for(const value of state)if(value===1)unmappedAfterDilation++;
  const formatVector=value=>`X=${value.x.toFixed(6)}, Y=${value.y.toFixed(6)}, Z=${value.z.toFixed(6)}`;
  console.info(`[Texture Mapping Debug] source bbox size: ${formatVector(mapping.sourceSize)}`);
  console.info(`[Texture Mapping Debug] voxel bbox size: ${formatVector(mapping.voxelSize)}`);
  console.info(`[Texture Mapping Debug] texture scale XYZ: ${formatVector(mapping.scale)}`);
  console.info(`[Texture Mapping Debug] unmapped samples before dilation: ${unmappedBeforeDilation}`);
  console.info(`[Texture Mapping Debug] unmapped samples after dilation: ${unmappedAfterDilation}`);
  return {data,width,height,origins,detail};
}

export function simplifyColors(source, amount) {
  const result=new Uint8Array(source), strength=Math.max(0,Math.min(100,amount))/100;
  if(!strength)return result;
  const step=1+Math.round(strength*63);
  for(let i=0;i<result.length;i+=4)for(let c=0;c<3;c++)result[i+c]=Math.min(255,Math.round(result[i+c]/step)*step);
  return result;
}
