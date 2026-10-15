export function bindUploader(input, onFile, onError) {
  input.addEventListener('change', () => {
    const file = input.files?.[0]; input.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.glb')) { onError('请选择 .glb 文件。'); return; }
    if (file.size > 40 * 1024 * 1024) { onError('文件超过 40 MB，请简化模型后重试。'); return; }
    onFile(file);
  });
}
