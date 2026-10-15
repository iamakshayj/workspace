import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/work-graph${path}`, {
    credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  notifyIfUnauthorized(response);
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Work graph request failed');
  return payload;
}

export function getRelatedItems(type, id, { depth = 1, direction = 'both', relationshipTypes = [], limit = 100 } = {}) {
  const params = new URLSearchParams({ depth: String(depth), direction, limit: String(limit) });
  if (relationshipTypes.length) params.set('relationship_types', relationshipTypes.join(','));
  return request(`/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}/related?${params}`);
}

export const getObjectHistory = (type, id, limit = 50) => request(`/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}/history?limit=${limit}`);
export const createRelationship = (payload) => request('/relationships', { method: 'POST', body: JSON.stringify(payload) });
export const updateRelationship = (id, payload) => request(`/relationships/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
export const deleteRelationship = (id) => request(`/relationships/${id}`, { method: 'DELETE' });
