export const DEFAULTS = Object.freeze({ min_voxel_size_cm: 1, geometry_detail: 40, curvature_weight: .4, thickness_weight: .1 });
export const SLIDER_DEBOUNCE_MS = 200;

export function bindControls(element, onChange) {
  const definitions = [
    ['min_voxel_size_cm', 'Minimum Voxel Size', 1, 10, .5, '设置打印后的最小体素边长；必要时自动放大成品尺寸', '1 cm', '10 cm'],
    ['geometry_detail', 'Geometry Detail', 0, 100, 1, '提高细节，使表面更容易继续细分', 'Low Detail', 'High Detail'],
    ['curvature_weight', 'Curvature Priority', 0, 1, .05, '提高尖角与弯曲区域的重要程度', '0', '1'],
    ['thickness_weight', 'Thin Feature Priority', 0, 1, .05, '薄度只作为辅助特征；平滑四肢不因薄而强制细分', '0', '1'],
  ];
  element.innerHTML = definitions.map(([key,label,min,max,step,hint,lo,hi]) => `
    <div class="control"><div class="control-title"><label for="${key}">${label}</label><output for="${key}" id="out-${key}"></output></div>
    <p>${hint}</p><input id="${key}" type="range" min="${min}" max="${max}" step="${step}" value="${DEFAULTS[key]}">
    <div class="range-labels"><span>${lo}</span><span>${hi}</span></div></div>`).join('');
  const inputs = definitions.map(([key]) => element.querySelector(`#${key}`));
  const display = () => inputs.forEach(input => {
    element.querySelector(`#out-${input.id}`).value = input.id === 'geometry_detail' ? `${input.value}%` : input.id === 'min_voxel_size_cm' ? `${input.value} cm` : Number(input.value).toFixed(2);
  });
  const read = () => {
    const values = Object.fromEntries(inputs.map(input => [input.id, Number(input.value)]));
    const detail = values.geometry_detail / 100;
    return { min_voxel_size_cm: values.min_voxel_size_cm, detail_level: detail, split_threshold: .90 - .77 * Math.pow(detail, 1.6), curvature_weight: values.curvature_weight, thickness_weight: values.thickness_weight, normal_weight: .25 };
  };
  inputs.forEach(input => input.addEventListener('input', () => { display(); onChange(read()); }));
  display();
  return {
    read,
    reset() { inputs.forEach(input => { input.value = DEFAULTS[input.id]; }); display(); onChange(read()); },
    enable(enabled) { inputs.forEach(input => { input.disabled = !enabled; }); },
  };
}
