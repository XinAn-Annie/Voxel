import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { makeVoxels, makeUniformVoxels, colorVoxels, makeHeatmap, colorHeatmap, setVoxelColorAtlas } from './voxelRenderer.js';
import { prepareColorSource, disposeColorSource, sampleVoxelColors } from './colorSampler.js';
import { uniformizeVoxels } from './uniformizer.js';

function dispose(object) {
  if (!object) return;
  object.traverse(node => {
    node.geometry?.dispose();
    const materials = Array.isArray(node.material) ? node.material : [node.material];
    materials.filter(Boolean).forEach(material => { Object.values(material).filter(v => v?.isTexture).forEach(t => t.dispose()); material.dispose(); });
  });
}

export class Viewer {
  constructor(element) {
    this.element = element;
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color('#f5f7f9');
    this.camera = new THREE.PerspectiveCamera(40,1,.01,100);
    this.renderer = new THREE.WebGLRenderer({ antialias:true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    element.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera,this.renderer.domElement); this.controls.enableDamping = true;
    this.controls.minDistance = .15; this.controls.maxDistance = 12;
    this.scene.add(new THREE.HemisphereLight(0xffffff,0x8997a5,2));
    const light = new THREE.DirectionalLight(0xffffff,2.5); light.position.set(2,4,3); this.scene.add(light);
    this.grid = new THREE.GridHelper(2,20,0xb7c1cb,0xe1e6eb); this.grid.position.set(.5,-.01,.5); this.scene.add(this.grid);
    this.original = null; this.voxelMesh = null; this.uniformMesh = null; this.uniformTexture = null; this.heatmapMesh = null; this.colorSource=null; this.colorRevision=0;
    this.colorSettings={enabled:true,detail:32,simplification:0}; this.mode = 'original'; this.radius=.8;
    this.neutralMaterial=new THREE.MeshStandardMaterial({color:'#a3aeb9',roughness:.85,side:THREE.DoubleSide});
    new ResizeObserver(() => this.resize()).observe(element);
    this.resize(); this.frame(); this.animate();
  }
  resize() {
    const w=Math.max(1,this.element.clientWidth), h=Math.max(1,this.element.clientHeight);
    this.camera.aspect=w/h; this.camera.updateProjectionMatrix(); this.renderer.setSize(w,h);
  }
  animate = () => { this.controls.update(); this.renderer.render(this.scene,this.camera); requestAnimationFrame(this.animate); };
  clear() {
    this.colorRevision++; disposeColorSource(this.colorSource); this.colorSource=null;
    this.original?.traverse(node=>{if(node.isMesh&&node.userData.originalMaterial)node.material=node.userData.originalMaterial;});
    for (const key of ['original','voxelMesh','uniformMesh','heatmapMesh']) { if(this[key]) this.scene.remove(this[key]); dispose(this[key]); this[key]=null; }
  }
  async loadGlb(file, isCurrent) {
    const gltf = await new GLTFLoader().parseAsync(await file.arrayBuffer(),'');
    if (!isCurrent()) { dispose(gltf.scene); return; }
    const box = new THREE.Box3().setFromObject(gltf.scene);
    let meshCount=0; gltf.scene.traverse(node => { if(node.isMesh) meshCount++; });
    if (box.isEmpty() || !meshCount) { dispose(gltf.scene); throw new Error('GLB 中没有可显示的三角网格。'); }
    const center=box.getCenter(new THREE.Vector3()), size=box.getSize(new THREE.Vector3());
    const extent=Math.max(size.x,size.y,size.z);
    if (!Number.isFinite(extent) || extent<=0) { dispose(gltf.scene); throw new Error('模型尺寸无效。'); }
    gltf.scene.traverse(node => {
      if (!node.isMesh) return;
      const lacksNormals = !node.geometry.getAttribute('normal');
      if (lacksNormals) node.geometry.computeVertexNormals();
      node.userData.originalMaterial=node.material;
    });
    const wrapper=new THREE.Group(); wrapper.add(gltf.scene); wrapper.scale.setScalar(1/extent);
    wrapper.position.copy(center).multiplyScalar(-1/extent).addScalar(.5);
    this.original=wrapper; this.scene.add(wrapper); wrapper.updateMatrixWorld(true); this.colorSource=prepareColorSource(wrapper); this.radius=size.length()/extent/2;
    this.grid.position.y=.5-size.y/extent/2-.01;
    this.frame(); this.setTextureEnabled(this.colorSettings.enabled); this.setMode(this.mode);
  }
  frame() {
    const v=THREE.MathUtils.degToRad(this.camera.fov); const h=2*Math.atan(Math.tan(v/2)*this.camera.aspect);
    const distance=this.radius/Math.sin(Math.min(v,h)/2)*1.12;
    this.controls.target.set(.5,.5,.5);
    this.camera.position.copy(new THREE.Vector3(1,.72,1).normalize().multiplyScalar(distance).add(this.controls.target));
    this.controls.update();
  }
  setAnalysis(data) { dispose(this.heatmapMesh); if(this.heatmapMesh)this.scene.remove(this.heatmapMesh); this.heatmapMesh=makeHeatmap(data); this.scene.add(this.heatmapMesh); this.setMode(this.mode); }
  setVoxels(voxels) { this.clearUniform(); this.colorRevision++; dispose(this.voxelMesh); if(this.voxelMesh)this.scene.remove(this.voxelMesh); this.voxelMesh=makeVoxels(voxels); this.scene.add(this.voxelMesh); this.setMode(this.mode); this.refreshVoxelColors(); }
  clearUniform() { if(this.uniformMesh){this.scene.remove(this.uniformMesh);dispose(this.uniformMesh);this.uniformMesh=null;} this.uniformTexture=null; this.showAfterUniformization=false; }
  canUniformize() { return Boolean(this.voxelMesh?.userData.colorAtlas && this.voxelMesh.material?.map?.image?.data); }
  uniformize() {
    if(!this.canUniformize())throw new Error('Uniformization failed: voxel colors are not ready.');
    this.clearUniform();
    const result=uniformizeVoxels(this.voxelMesh.userData.voxels,this.voxelMesh.material.map.image.data);
    const sourceColorData=this.voxelMesh.material.map.image.data;
    this.uniformMesh=makeUniformVoxels(result.voxels,this.voxelMesh.userData.colorAtlas,this.voxelMesh.material.map);
    this.uniformTexture=this.uniformMesh.material.map;
    if(this.uniformTexture.image.data!==sourceColorData)throw new Error('Uniformization failed: color set changed.');
    result.validation.color_set_equal=true;
    this.scene.add(this.uniformMesh); this.showAfterUniformization=true; this.setMode('voxelColor');
    return result;
  }
  setUniformPreview(after) { if(after&&!this.uniformMesh)throw new Error('Uniformization has not been completed.'); this.showAfterUniformization=after; this.setMode('voxelColor'); }
  async exportUniformGlb() {
    if(!this.uniformMesh)throw new Error('Complete Uniformization before export.');
    const result=await new GLTFExporter().parseAsync(this.uniformMesh,{binary:true,onlyVisible:true});
    const url=URL.createObjectURL(new Blob([result],{type:'model/gltf-binary'}));
    const link=document.createElement('a'); link.href=url; link.download='uniform_voxel_model.glb'; link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  setTextureEnabled(enabled) {
    this.colorSettings.enabled=enabled;
    this.original?.traverse(node=>{if(node.isMesh)node.material=enabled?node.userData.originalMaterial:this.neutralMaterial;});
    if(this.voxelMesh)colorVoxels(this.voxelMesh,enabled?this.mode:'final');
    if(this.uniformMesh){this.uniformMesh.material.map=enabled?this.uniformTexture:null;this.uniformMesh.material.needsUpdate=true;}
  }
  setColorSettings(settings) {
    const detailChanged=settings.detail!==this.colorSettings.detail;
    this.colorSettings={...settings}; this.setTextureEnabled(settings.enabled);
    if(!this.voxelMesh)return false;
    if(detailChanged||!this.voxelMesh.userData.colorAtlas){this.refreshVoxelColors();return true;}
    setVoxelColorAtlas(this.voxelMesh,this.voxelMesh.userData.colorAtlas,settings.simplification); colorVoxels(this.voxelMesh,this.mode); return false;
  }
  async refreshVoxelColors() {
    if(!this.colorSource||!this.voxelMesh)return;
    const mesh=this.voxelMesh, revision=++this.colorRevision;
    try {
      const atlas=await sampleVoxelColors(this.colorSource,mesh.userData.voxels,this.colorSettings.detail,()=>revision===this.colorRevision&&mesh===this.voxelMesh);
      if(!atlas||revision!==this.colorRevision||mesh!==this.voxelMesh)return;
      setVoxelColorAtlas(mesh,atlas,this.colorSettings.simplification); colorVoxels(mesh,this.mode);
      this.onColorReady?.();
    } catch(error) { if(revision===this.colorRevision)this.onColorError?.(error); }
  }
  setGrid(visible) { this.grid.visible=visible; }
  setMode(mode) {
    this.mode=mode;
    if(this.original)this.original.visible=mode==='original';
    if(this.voxelMesh) { this.voxelMesh.visible=['voxelColor','depth'].includes(mode) && !(mode==='voxelColor'&&this.showAfterUniformization); if(this.voxelMesh.visible)colorVoxels(this.voxelMesh,this.colorSettings.enabled?mode:'final'); }
    if(this.uniformMesh)this.uniformMesh.visible=mode==='voxelColor'&&this.showAfterUniformization;
    if(this.heatmapMesh) { this.heatmapMesh.visible=['curvature','thickness'].includes(mode); if(this.heatmapMesh.visible)colorHeatmap(this.heatmapMesh,mode); }
  }
}
