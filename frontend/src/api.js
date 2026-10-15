async function request(path, options = {}) {
  let response;
  try { response = await fetch(`/api${path}`, options); }
  catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('无法连接后端。请确认本地服务已启动。');
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败 (${response.status})`);
  }
  return response.json();
}

export const api = {
  upload(file, signal) {
    const form = new FormData(); form.append('file', file);
    return request('/upload', { method: 'POST', body: form, signal });
  },
  status(id, signal) { return request(`/models/${id}`, { signal }); },
  analysis(id, signal) { return request(`/models/${id}/analysis`, { signal }); },
  voxelize(id, params, signal) {
    return request('/voxelize', { method: 'POST', signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model_id: id, ...params }) });
  },
};
