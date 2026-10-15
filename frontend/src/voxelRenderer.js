import * as THREE from 'three';
import { FACE_AXES, simplifyColors } from './colorSampler.js';

export const DEPTH_COLORS = ['#edf1f5', '#89b8c8', '#459dac', '#4485bc', '#846ec0', '#c3718e', '#eaa757'];
const color = new THREE.Color();

function voxelGeometry() {
  const positions=[],normals=[],uvs=[],faces=[];
  const corners=[[0,0],[1,0],[1,1],[0,0],[1,1],[0,1]];
  FACE_AXES.forEach((face,id)=>corners.forEach(([u,v])=>{
    const p=new THREE.Vector3().copy(face.n).multiplyScalar(.5).addScaledVector(face.u,u-.5).addScaledVector(face.v,v-.5);
    positions.push(p.x,p.y,p.z); normals.push(face.n.x,face.n.y,face.n.z); uvs.push(u,v); faces.push(id);
  }));
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3)); geometry.setAttribute('normal',new THREE.Float32BufferAttribute(normals,3));
  geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2)); geometry.setAttribute('faceId',new THREE.Float32BufferAttribute(faces,1));
  return geometry;
}

function cellMaterial() {
  const pixel=new Uint8Array([255,255,255,255]);
  const placeholder=new THREE.DataTexture(pixel,1,1,THREE.RGBAFormat); placeholder.colorSpace=THREE.SRGBColorSpace; placeholder.needsUpdate=true;
  const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: .85, map:placeholder });
  // Screen-space edge shading makes adjacent true-size cubes readable without
  // shrinking voxels or creating a separate Mesh for each cell.
  material.onBeforeCompile = shader => {
    const pending=material.userData.pendingAtlas;
    shader.uniforms.voxelAtlasSize={value:new THREE.Vector2(pending?.width||1,pending?.height||1)}; shader.uniforms.voxelDetail={value:pending?.detail||1}; shader.uniforms.useVoxelAtlas={value:pending?1:0};
    shader.vertexShader = shader.vertexShader.replace('void main() {', 'attribute float faceId; attribute vec2 atlasOrigin; varying float vVoxelFace; varying vec2 vCellUv; varying vec2 vAtlasOrigin;\nvoid main() {\nvVoxelFace=faceId; vCellUv=uv; vAtlasOrigin=atlasOrigin;');
    shader.fragmentShader = shader.fragmentShader.replace('void main() {', 'uniform vec2 voxelAtlasSize; uniform float voxelDetail; uniform float useVoxelAtlas; varying float vVoxelFace; varying vec2 vCellUv; varying vec2 vAtlasOrigin;\nvoid main() {');
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
      if(useVoxelAtlas > 0.5) {
        float faceColumn=mod(floor(vVoxelFace+0.5),3.0); float faceRow=floor((vVoxelFace+0.5)/3.0);
        vec2 cell=floor(clamp(vCellUv,vec2(0.0),vec2(0.999999))*voxelDetail);
        vec2 atlasPixel=vAtlasOrigin+vec2(faceColumn,faceRow)*voxelDetail+cell;
        diffuseColor*=texture2D(map,(atlasPixel+0.5)/voxelAtlasSize);
      }`);
    shader.fragmentShader = shader.fragmentShader.replace('#include <color_fragment>', `#include <color_fragment>
      vec2 edgeDistance = min(vCellUv, 1.0 - vCellUv);
      vec2 edgeWidth = max(fwidth(vCellUv) * 1.2, vec2(0.001));
      vec2 edgeFade = smoothstep(vec2(0.0), edgeWidth, edgeDistance);
      diffuseColor.rgb *= mix(0.55, 1.0, min(edgeFade.x, edgeFade.y));`);
    material.userData.shader=shader;
  };
  material.customProgramCacheKey=()=> 'voxel-color-atlas-v1';
  return material;
}

export function makeVoxels(voxels) {
  const geometry=voxelGeometry();
  geometry.setAttribute('atlasOrigin',new THREE.InstancedBufferAttribute(new Float32Array(voxels.length*2),2));
  const mesh = new THREE.InstancedMesh(geometry, cellMaterial(), voxels.length);
  const matrix = new THREE.Matrix4();
  voxels.forEach((v,i) => {
    matrix.makeScale(v.size, v.size, v.size); matrix.setPosition(v.x, v.y, v.z);
    mesh.setMatrixAt(i, matrix);
  });
  mesh.userData.voxels = voxels;
  mesh.instanceMatrix.needsUpdate = true;
  mesh.computeBoundingSphere();
  colorVoxels(mesh, 'final');
  return mesh;
}

export function colorVoxels(mesh, mode) {
  const useAtlas=mode==='voxelColor'&&mesh.userData.colorAtlas;
  mesh.userData.voxels.forEach((v,i) => mesh.setColorAt(i, color.set(mode === 'depth' ? DEPTH_COLORS[v.depth % DEPTH_COLORS.length] : useAtlas?'#ffffff':'#a6b3bd')));
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  if(mesh.material.userData.shader)mesh.material.userData.shader.uniforms.useVoxelAtlas.value=useAtlas?1:0;
}

export function setVoxelColorAtlas(mesh, atlas, simplification=0) {
  mesh.userData.colorAtlas=atlas;
  mesh.material.userData.pendingAtlas=atlas;
  const data=simplifyColors(atlas.data,simplification);
  const texture=new THREE.DataTexture(data,atlas.width,atlas.height,THREE.RGBAFormat); texture.colorSpace=THREE.SRGBColorSpace;
  texture.magFilter=THREE.NearestFilter;texture.minFilter=THREE.NearestFilter;texture.generateMipmaps=false;texture.needsUpdate=true;
  const previous=mesh.material.map; mesh.material.map=texture; if(previous&&previous!==texture)previous.dispose();
  mesh.geometry.setAttribute('atlasOrigin',new THREE.InstancedBufferAttribute(atlas.origins,2));
  const shader=mesh.material.userData.shader;
  if(shader){shader.uniforms.voxelAtlasSize.value.set(atlas.width,atlas.height);shader.uniforms.voxelDetail.value=atlas.detail;shader.uniforms.useVoxelAtlas.value=1;}
}

function childAxisIndex(child, axis) {
  const source = axis.x ? child.child_grid[0] : axis.y ? child.child_grid[1] : child.child_grid[2];
  return axis.x + axis.y + axis.z > 0 ? source : child.parent_ratio - 1 - source;
}

export function makeUniformVoxels(voxels, adaptiveAtlas, adaptiveTexture) {
  if (!adaptiveAtlas || !adaptiveTexture) throw new Error('Uniformization failed: color atlas is unavailable.');
  const positions = new Float32Array(voxels.length * 36 * 3);
  const normals = new Float32Array(voxels.length * 36 * 3);
  const uvs = new Float32Array(voxels.length * 36 * 2);
  const sourceIds = new Uint32Array(voxels.length * 36), uniformIds = new Uint32Array(voxels.length * 36);
  const corners = [[0,0],[1,0],[1,1],[0,0],[1,1],[0,1]];
  let p = 0, t = 0;
  let uniformIndex=0;
  for (const voxel of voxels) {
    const parentOriginX = adaptiveAtlas.origins[voxel.source_voxel_index * 2];
    const parentOriginY = adaptiveAtlas.origins[voxel.source_voxel_index * 2 + 1];
    for (let faceId = 0; faceId < FACE_AXES.length; faceId++) {
      const face = FACE_AXES[faceId];
      const uIndex = childAxisIndex(voxel, face.u), vIndex = childAxisIndex(voxel, face.v);
      const faceX = parentOriginX + (faceId % 3) * adaptiveAtlas.detail;
      const faceY = parentOriginY + Math.floor(faceId / 3) * adaptiveAtlas.detail;
      const uPixel0=Math.floor(uIndex*adaptiveAtlas.detail/voxel.parent_ratio),uPixel1=Math.max(uPixel0,Math.ceil((uIndex+1)*adaptiveAtlas.detail/voxel.parent_ratio)-1);
      const vPixel0=Math.floor(vIndex*adaptiveAtlas.detail/voxel.parent_ratio),vPixel1=Math.max(vPixel0,Math.ceil((vIndex+1)*adaptiveAtlas.detail/voxel.parent_ratio)-1);
      const u0 = (faceX + uPixel0 + .5) / adaptiveAtlas.width, u1 = (faceX + uPixel1 + .5) / adaptiveAtlas.width;
      const v0 = (faceY + vPixel0 + .5) / adaptiveAtlas.height, v1 = (faceY + vPixel1 + .5) / adaptiveAtlas.height;
      for (const [u, v] of corners) {
        const vertexIndex=p/3;
        positions[p] = voxel.x + (face.n.x * .5 + face.u.x * (u - .5) + face.v.x * (v - .5)) * voxel.size; normals[p++] = face.n.x;
        positions[p] = voxel.y + (face.n.y * .5 + face.u.y * (u - .5) + face.v.y * (v - .5)) * voxel.size; normals[p++] = face.n.y;
        positions[p] = voxel.z + (face.n.z * .5 + face.u.z * (u - .5) + face.v.z * (v - .5)) * voxel.size; normals[p++] = face.n.z;
        uvs[t++] = u ? u1 : u0; uvs[t++] = v ? v1 : v0;
        sourceIds[vertexIndex]=voxel.source_voxel_index;uniformIds[vertexIndex]=uniformIndex;
      }
    }
    uniformIndex++;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geometry.setAttribute('source_voxel_id',new THREE.BufferAttribute(sourceIds,1));
  geometry.setAttribute('uniform_voxel_id',new THREE.BufferAttribute(uniformIds,1));
  geometry.computeBoundingBox(); geometry.computeBoundingSphere();
  const texture = adaptiveTexture.clone(); texture.needsUpdate = true;
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({color:0xffffff,roughness:.85,map:texture}));
  mesh.name = 'UniformVoxels';
  return mesh;
}

export function makeHeatmap(data) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(data.vertices.flat(), 3));
  geometry.setIndex(data.faces.flat());
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ vertexColors:true, roughness:1, side:THREE.DoubleSide }));
  mesh.userData.fields = data;
  colorHeatmap(mesh, 'curvature');
  return mesh;
}

export function colorHeatmap(mesh, field) {
  const values = mesh.userData.fields[field];
  const colors = new Float32Array(values.length * 3);
  values.forEach((value,i) => {
    if (value < 0) color.set('#aeb6be');
    else color.setHSL(.63 - Math.max(0,Math.min(1,value)) * .60, .72, .52);
    color.toArray(colors, i*3);
  });
  mesh.geometry.setAttribute('color', new THREE.BufferAttribute(colors,3));
}
