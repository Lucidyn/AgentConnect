export function createStreamState() {
  return { text: '', agent: '' };
}

export function applyPartialStream(state, data, renderMarkdown, escapeHtml) {
  if (!data.partial_result) return;
  state.text = data.partial_result;
  state.agent = data.streaming_agent || '';
  const el = document.getElementById('task-result');
  if (!el) return;
  const body = el.querySelector('.result-body');
  if (!body) return;
  const label = state.agent ? `${state.agent} 正在输出…` : '正在输出…';
  body.innerHTML = `<div style="color:var(--muted);margin-bottom:0.5rem">${escapeHtml(label)}</div>${renderMarkdown(state.text)}`;
}
