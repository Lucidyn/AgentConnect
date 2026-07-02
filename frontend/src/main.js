import { apiFetch, getApiKey, taskStreamUrl } from './api.js';
import { ComposeEditor } from './compose.js';
import { applyPartialStream, createStreamState } from './stream-ui.js';

window.ComposeEditor = ComposeEditor;
window.agentConnectModules = {
  apiFetch,
  getApiKey,
  taskStreamUrl,
  applyPartialStream,
  createStreamState,
};

function bootComposeEditor() {
  ComposeEditor.ensureInit();
  window.dispatchEvent(new CustomEvent('agentConnect:ready'));
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootComposeEditor);
} else {
  bootComposeEditor();
}
