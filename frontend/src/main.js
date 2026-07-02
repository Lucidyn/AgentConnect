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
