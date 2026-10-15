export const COLOR_DEFAULTS = Object.freeze({ enabled: true, detail: 32, simplification: 0 });

export function bindColorControls(element, onChange) {
  element.innerHTML = `
    <div class="color-head"><div><span class="eyebrow">SURFACE APPEARANCE</span><h3>Texture / Color</h3></div>
      <label class="switch"><input id="color-enabled" type="checkbox" checked><span>Enable Texture</span></label></div>
    <div class="control"><div class="control-title"><label for="color-detail">Color Detail</label><output id="out-color-detail">32×32</output></div>
      <p>只改变每个 voxel 表面的颜色网格，不改变 voxel 数量或尺寸。</p>
      <select id="color-detail"><option value="2">2×2</option><option value="4">4×4</option><option value="8">8×8</option><option value="16">16×16</option><option value="32" selected>32×32</option><option value="64">64×64</option></select></div>
    <div class="control"><div class="control-title"><label for="color-simplification">Color Simplification</label><output id="out-color-simplification">0%</output></div>
      <p>合并相近颜色；只更新显示 atlas。</p><input id="color-simplification" type="range" min="0" max="100" step="1" value="0">
      <div class="range-labels"><span>Original</span><span>Simplified</span></div></div>
    <button id="reset-color" class="reset" type="button">↺ Reset Color</button>`;
  const enabled = element.querySelector('#color-enabled');
  const detail = element.querySelector('#color-detail');
  const simplification = element.querySelector('#color-simplification');
  const read = () => ({ enabled: enabled.checked, detail: Number(detail.value), simplification: Number(simplification.value) });
  const display = () => {
    element.querySelector('#out-color-detail').value = `${detail.value}×${detail.value}`;
    element.querySelector('#out-color-simplification').value = `${simplification.value}%`;
  };
  [enabled, detail, simplification].forEach(input => input.addEventListener('input', () => { display(); onChange(read()); }));
  element.querySelector('#reset-color').addEventListener('click', () => {
    enabled.checked = COLOR_DEFAULTS.enabled; detail.value = COLOR_DEFAULTS.detail; simplification.value = COLOR_DEFAULTS.simplification;
    display(); onChange(read());
  });
  display();
  return { read, enable(value) { [enabled, detail, simplification].forEach(input => { input.disabled = !value; }); element.querySelector('#reset-color').disabled = !value; } };
}
