import { apiFetch, getApiKey, taskStreamUrl } from './api.js';
import { applyPartialStream, createStreamState } from './stream-ui.js';

window.agentConnectModules = {
  apiFetch,
  getApiKey,
  taskStreamUrl,
  applyPartialStream,
  createStreamState,
};
