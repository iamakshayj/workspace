import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

export class WorkApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'WorkApiError';
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/work${path}`, {
      ...options,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...options.headers },
    });
  } catch {
    throw new WorkApiError('Work management is temporarily unavailable.');
  }
  notifyIfUnauthorized(response);
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new WorkApiError(body.detail || 'The work request failed.', response.status);
  return body;
}

export const getWorkOverview = () => request('/overview');
export const updateWorkWorkflow = (payload) => request('/workflow', { method: 'PUT', body: JSON.stringify(payload) });
export const createWorkItem = (payload) => request('/items', { method: 'POST', body: JSON.stringify(payload) });
export const updateWorkItem = (itemId, payload) => request(`/items/${encodeURIComponent(itemId)}`, { method: 'PUT', body: JSON.stringify(payload) });
export const deleteWorkItem = (itemId) => request(`/items/${encodeURIComponent(itemId)}`, { method: 'DELETE' });
export const duplicateWorkItem = (itemId) => request(`/items/${encodeURIComponent(itemId)}/duplicate`, { method: 'POST' });
export const splitWorkItem = (itemId, parts) => request(`/items/${encodeURIComponent(itemId)}/split`, { method: 'POST', body: JSON.stringify({ parts }) });
export const mergeWorkItems = (itemId, sourceIds) => request(`/items/${encodeURIComponent(itemId)}/merge`, { method: 'POST', body: JSON.stringify({ source_ids: sourceIds }) });
export const followWorkItem = (itemId, following) => request(`/items/${encodeURIComponent(itemId)}/follow`, { method: 'PUT', body: JSON.stringify({ following }) });
export const bulkUpdateWorkItems = (payload) => request('/bulk/items', { method: 'PUT', body: JSON.stringify(payload) });
export const createWorkComment = (itemId, body, parentId = null, attachments = []) => request(`/items/${encodeURIComponent(itemId)}/comments`, { method: 'POST', body: JSON.stringify({ body, parent_id: parentId, attachments }) });
export const reactToWorkComment = (itemId, commentId, emoji) => request(`/items/${encodeURIComponent(itemId)}/comments/${encodeURIComponent(commentId)}/reaction`, { method: 'PUT', body: JSON.stringify({ emoji }) });
export const createWorkLink = (itemId, payload) => request(`/items/${encodeURIComponent(itemId)}/links`, { method: 'POST', body: JSON.stringify(payload) });
export const deleteWorkLink = (linkId) => request(`/links/${encodeURIComponent(linkId)}`, { method: 'DELETE' });
export const createSprint = (payload) => request('/sprints', { method: 'POST', body: JSON.stringify(payload) });
export const updateSprint = (sprintId, payload) => request(`/sprints/${encodeURIComponent(sprintId)}`, { method: 'PUT', body: JSON.stringify(payload) });
export const createRelease = (payload) => request('/releases', { method: 'POST', body: JSON.stringify(payload) });
export const updateRelease = (releaseId, payload) => request(`/releases/${encodeURIComponent(releaseId)}`, { method: 'PUT', body: JSON.stringify(payload) });
export const getProjectPlanning = (projectId) => request(`/projects/${encodeURIComponent(projectId)}/planning`);
export const updateNodePlanning = (projectId, nodeId, payload) => request(
  `/projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeId)}/planning`,
  { method: 'PUT', body: JSON.stringify(payload) },
);
export const createNodeWorkItem = (projectId, nodeId, payload) => request(
  `/projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeId)}/work-items`,
  { method: 'POST', body: JSON.stringify(payload) },
);
