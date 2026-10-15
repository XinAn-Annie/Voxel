import './style.css';
import { Viewer } from './viewer.js';
import { bindUploader } from './uploader.js';
import { bindControls, SLIDER_DEBOUNCE_MS } from './controls.js';
import { bindColorControls } from './colorControls.js';
import { DEPTH_COLORS } from './voxelRenderer.js';
import { api } from './api.js';

document.querySelector('#app').innerHTML = `
<header class="topbar"><div class="brand"><svg viewBox="0 0 32 36" aria-hidden="true"><path d="M16 2 30 10v16L16 34 2 26V10zM2 10l14 8 14-8M16 18v16"/></svg><div><strong>Adaptive Voxelizer</strong><small>GEOMETRY WORKSPACE · PHASE 01</small></div></div><div class="header-end"><span class="local-badge">LOCAL PROCESSING</span><label class="upload-button" for="upload">＋ Upload GLB</label><input id="upload" type="file" accept=".glb,model/gltf-binary" class="file-input"></div></header>
<main class="workspace"><section class="stage" aria-label="3D model workspace">
  <div class="stage-top"><div><span class="eyebrow">3D VIEWPORT</span><h1 id="model-name">Explore geometry, at every scale.</h1></div><button id="frame" class="icon-button" title="自动居中并调整视角" aria-label="Frame model">⌖</button></div>
  <div id="view-modes" class="view-modes" role="group" aria-label="View mode"><button data-mode="original" aria-pressed="true" class="active">Original Color</button><button data-mode="curvature" aria-pressed="false" disabled>Curvature</button><button data-mode="thickness" aria-pressed="false" disabled>Thickness</button><button data-mode="depth" aria-pressed="false" disabled>Octree Depth</button><button data-mode="voxelColor" aria-pressed="false" disabled>Voxel Color</button></div>
  <div id="viewer"></div>
  <div id="welcome"><div class="welcome-icon">◈</div><h2>From surfaces to structure.</h2><p>上传 GLB，观察几何特征如何决定体素大小。<br>也可以从右侧选择一个测试模型开始。</p><label class="secondary-upload" for="upload">选择 .glb 文件</label><small>最大 40 MB · 150,000 三角面</small></div>
  <div id="legend" class="legend" hidden></div>
  <div class="viewer-hint"><span>左键旋转 · 滚轮缩放 · 右键平移</span><label><input id="grid" type="checkbox" checked> Grid</label></div>
</section><aside class="panel"><div class="panel-head"><span class="eyebrow">ADAPTIVE OCTREE</span><h2>Parameters</h2><p>Let the geometry guide the detail.</p></div><div id="controls"></div><button id="reset" class="reset">↺ Reset parameters</button><div id="color-controls" class="color-controls"></div>
  <div class="uniform-actions"><span class="eyebrow">ADAPTIVE VOXEL → UNIFORM VOXEL</span><button id="uniformize" class="primary-action" disabled>Uniformize</button><div class="preview-switch"><button id="preview-before" disabled>Before Uniformization</button><button id="preview-after" disabled>After Uniformization</button></div><button id="export-glb" class="reset" disabled>Export GLB</button><p id="uniform-validation">Awaiting adaptive voxels and colors.</p></div>
  <div class="samples"><label for="sample">TRY A SAMPLE</label><div class="sample-select"><select id="sample"><option value="cube_thin_rod">Cube + Thin Rod</option><option value="cube">Cube</option><option value="sphere">Sphere</option><option value="cone">Cone</option><option value="animal">Animal / Character</option></select><button id="load-sample">Load</button></div><p>五个内置几何测试模型，与上传使用相同流程。</p></div>
  <div class="parameter-note">最小体素边长按打印成品计算。细节受保护时系统会自动放大成品，避免小于设定值；实际尺寸显示在底部。</div>
</aside></main>
<div class="statusbar"><span id="status-dot" class="status-dot"></span><span id="status" role="status" aria-live="polite">Ready to upload · 选择一个模型开始</span></div><div id="warnings" class="warnings" hidden></div>
<footer class="stats"><div><span>ADAPTIVE VOXEL COUNT</span><strong id="stat-count">—</strong></div><div><span>UNIFORM VOXEL COUNT</span><strong id="stat-uniform-count">—</strong></div><div><span>MIN SIZE</span><strong id="stat-size">—</strong></div><div><span>COMPUTE TIME</span><strong id="stat-time">—</strong><small id="stat-request">缓存裁剪时间</small><span id="stat-depth" hidden>—</span></div></footer>`;

const $ = selector => document.querySelector(selector);
let viewer;
try { viewer = new Viewer($('#viewer')); }
catch { $('#status').textContent = '无法创建 3D 视图，请使用支持 WebGL 2 的浏览器。'; throw new Error('WebGL initialization failed'); }
let modelId=null, uploadRevision=0, updateRevision=0, uploadController, updateController, timer;
let uniformResult=null;
function resetUniformization() {
  uniformResult=null; viewer.clearUniform();
  $('#stat-uniform-count').textContent='—'; $('#uniform-validation').textContent='Awaiting Uniformization.';
  $('#uniformize').disabled=true; $('#preview-before').disabled=true; $('#preview-after').disabled=true; $('#export-glb').disabled=true;
}
const controls = bindControls($('#controls'), () => {
  clearTimeout(timer); updateRevision++; updateController?.abort();
  if(modelId)timer=setTimeout(updateVoxels, SLIDER_DEBOUNCE_MS);
});
controls.enable(false);
const colorControls=bindColorControls($('#color-controls'),settings=>{resetUniformization();const pending=viewer.setColorSettings(settings);status(pending?'Updating color preview… · 正在更新颜色':'Ready · 颜色参数只更新显示',pending?'busy':'ready');if(!pending&&viewer.canUniformize())$('#uniformize').disabled=false;});
colorControls.enable(false);
viewer.onColorReady=()=>{$('#uniformize').disabled=false;status('Ready · 颜色更新未重新执行 Geometry Voxelization');};
viewer.onColorError=error=>status(error.message,'error');

function status(message, state='ready') { $('#status').textContent=message; $('#status-dot').className=`status-dot ${state}`; }
function setMode(mode) {
  viewer.setMode(mode);
  document.querySelectorAll('[data-mode]').forEach(button => { const active=button.dataset.mode===mode; button.classList.toggle('active',active); button.setAttribute('aria-pressed',String(active)); });
  const legend=$('#legend'); legend.hidden=!['curvature','thickness','depth'].includes(mode);
  if(mode==='depth')legend.innerHTML=`<b>Octree Depth</b><div class="depth-scale">${DEPTH_COLORS.slice(1).map((c,i)=>`<span><i style="background:${c}"></i>${i+1}</span>`).join('')}</div>`;
  if(['curvature','thickness'].includes(mode))legend.innerHTML=`<b>${mode==='curvature'?'Curvature':'Thickness'}</b><div class="heat-scale"></div><div class="scale-labels"><span>${mode==='curvature'?'低曲率':'厚'}</span><span>${mode==='curvature'?'高曲率':'薄'}</span></div>${mode==='thickness'?'<small>灰色 = 无可用厚度估计</small>':''}`;
}

async function updateVoxels() {
  if(!modelId)return;
  const id=modelId, modelRevision=uploadRevision, revision=++updateRevision;
  updateController?.abort(); updateController=new AbortController();
  const start=performance.now(); status('Updating voxels… · 正在更新体素','busy');
  try {
    const result=await api.voxelize(id,controls.read(),updateController.signal);
    if(revision!==updateRevision || modelRevision!==uploadRevision)return;
    resetUniformization(); viewer.setVoxels(result.voxels);
    $('#stat-count').textContent=result.stats.voxel_count.toLocaleString();
    $('#stat-size').textContent=`${result.stats.min_size_cm.toFixed(2)} cm`;
    $('#stat-depth').textContent=`${result.stats.min_depth}–${result.stats.max_depth}`;
    $('#stat-time').textContent=`${result.stats.compute_ms} ms`;
    await new Promise(resolve=>requestAnimationFrame(resolve));
    if(revision!==updateRevision || modelRevision!==uploadRevision)return;
    $('#stat-request').textContent=`请求与显示 ${Math.round(performance.now()-start)} ms`;
    status('Ready · 参数更新使用缓存，无需重新分析模型');
  } catch(error) { if(error.name!=='AbortError' && revision===updateRevision)status(error.message,'error'); }
}

async function loadFile(file) {
  const revision=++uploadRevision;
  uploadController?.abort(); updateController?.abort(); clearTimeout(timer); updateRevision++;
  uploadController=new AbortController(); const signal=uploadController.signal;
  modelId=null; controls.enable(false); colorControls.enable(false); viewer.clear(); setMode('original');
  $('#welcome').hidden=true; $('#warnings').hidden=true; $('#model-name').textContent=file.name;
  document.querySelectorAll('[data-mode]').forEach(button=>{button.disabled=button.dataset.mode!=='original';});
  ['count','uniform-count','size','depth','time'].forEach(key=>{$(`#stat-${key}`).textContent='—';}); $('#stat-request').textContent='缓存裁剪时间'; resetUniformization();
  status('Loading original model… · 读取模型','busy');
  try {
    const [, uploaded]=await Promise.all([viewer.loadGlb(file,()=>revision===uploadRevision),api.upload(file,signal)]);
    if(revision!==uploadRevision)return;
    let result;
    do {
      result=await api.status(uploaded.model_id,signal);
      if(revision!==uploadRevision)return;
      status(`${result.stage}…`,'busy');
      if(result.status!=='ready')await new Promise(resolve=>setTimeout(resolve,350));
    } while(result.status!=='ready');
    const fields=await api.analysis(uploaded.model_id,signal);
    if(revision!==uploadRevision)return;
    viewer.setAnalysis(fields); modelId=uploaded.model_id;
    if(result.warnings.length) { $('#warnings').textContent=result.warnings.join(' '); $('#warnings').hidden=false; }
    document.querySelectorAll('[data-mode]').forEach(button=>{button.disabled=false;});
    controls.enable(true); colorControls.enable(true); viewer.setColorSettings(colorControls.read()); setMode('voxelColor'); await updateVoxels();
  } catch(error) { if(error.name!=='AbortError' && revision===uploadRevision)status(error.message,'error'); }
}

bindUploader($('#upload'),loadFile,message=>status(message,'error'));
$('#reset').addEventListener('click',()=>controls.reset());
$('#frame').addEventListener('click',()=>viewer.frame());
$('#grid').addEventListener('change',event=>viewer.setGrid(event.target.checked));
$('#view-modes').addEventListener('click',event=>{const button=event.target.closest('[data-mode]');if(button&&!button.disabled)setMode(button.dataset.mode);});
$('#uniformize').addEventListener('click',async()=>{
  const button=$('#uniformize');button.disabled=true;status('Uniformizing existing adaptive voxels…','busy');await new Promise(resolve=>requestAnimationFrame(resolve));
  try {
    uniformResult=viewer.uniformize(); setMode('voxelColor');
    $('#stat-uniform-count').textContent=uniformResult.voxels.length.toLocaleString();
    $('#preview-before').disabled=false;$('#preview-after').disabled=false;$('#export-glb').disabled=false;
    $('#preview-before').classList.remove('active');$('#preview-after').classList.add('active');
    $('#uniform-validation').textContent='Validated: volume, bounding box, color set, overlap and gap.';
    status('Uniformization complete · validation passed');
  } catch(error) { status(error.message,'error'); $('#uniform-validation').textContent=error.message; button.disabled=false; }
});
$('#preview-before').addEventListener('click',()=>{viewer.setUniformPreview(false);setMode('voxelColor');$('#preview-before').classList.add('active');$('#preview-after').classList.remove('active');});
$('#preview-after').addEventListener('click',()=>{viewer.setUniformPreview(true);setMode('voxelColor');$('#preview-after').classList.add('active');$('#preview-before').classList.remove('active');});
$('#export-glb').addEventListener('click',async()=>{const button=$('#export-glb');button.disabled=true;status('Exporting uniform_voxel_model.glb…','busy');try{await viewer.exportUniformGlb();status('Export complete · uniform_voxel_model.glb');}catch(error){status(error.message,'error');}finally{button.disabled=!uniformResult;}});
$('#load-sample').addEventListener('click',async()=>{
  const button=$('#load-sample');button.disabled=true;
  const name=$('#sample').value;
  try {
    const response=await fetch(`/samples/${name}.glb`);
    if(!response.ok)throw new Error('测试模型缺失，请检查 samples 文件夹。');
    await loadFile(new File([await response.blob()],`${name}.glb`,{type:'model/gltf-binary'}));
  } catch(error) { status(error.message,'error'); }
  finally { button.disabled=false; }
});
