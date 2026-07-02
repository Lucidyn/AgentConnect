const API_KEY_STORAGE = 'agent_connect_api_key';

export function getApiKey() {
  const el = document.getElementById('api-key-input');
  return (el && el.value.trim()) || localStorage.getItem(API_KEY_STORAGE) || '';
}

export async function apiFetch(url, options = {}) {
  const { silent = false, ...fetchOptions } = options;
  const headers = { ...(fetchOptions.headers || {}) };
  const key = getApiKey();
  if (key) headers['X-API-Key'] = key;
  if (fetchOptions.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(url, { ...fetchOptions, headers });
  if (!silent && window.showToast) {
    if (res.status === 401) {
      window.showToast('API Key 无效或未填写 — 请在右上角配置', 'error');
    } else if (!res.ok) {
      let detail = res.statusText;
      try {
        const err = await res.clone().json();
        detail = err.detail || err.error || JSON.stringify(err);
      } catch (e) {
        /* ignore */
      }
      window.showToast(`请求失败 (${res.status}): ${detail}`, 'error');
    }
  }
  return res;
}

export function taskStreamUrl(taskId) {
  const key = getApiKey();
  return key
    ? `/tasks/${taskId}/stream?api_key=${encodeURIComponent(key)}`
    : `/tasks/${taskId}/stream`;
}
