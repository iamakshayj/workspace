import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/search${path}`, {
    credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  notifyIfUnauthorized(response);
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Search request failed');
  return payload;
}

export function searchWorkspace({ query = '', mode = 'keyword', types = [], statuses = [], projectId = '', ownerId = '', offset = 0, limit = 40, remember = true } = {}) {
  const params = new URLSearchParams({ q: query, mode, offset: String(offset), limit: String(limit), remember: String(remember) });
  if (types.length) params.set('types', types.join(','));
  if (statuses.length) params.set('statuses', statuses.join(','));
  if (projectId) params.set('project_id', projectId);
  if (ownerId) params.set('owner_id', ownerId);
  return request(`?${params}`);
}

export const getRecentSearches = () => request('/recent');
export const clearRecentSearches = () => request('/recent', { method: 'DELETE' });
export const getSavedSearches = () => request('/saved');
export const createSavedSearch = (payload) => request('/saved', { method: 'POST', body: JSON.stringify(payload) });
export const updateSavedSearch = (id, payload) => request(`/saved/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
export const deleteSavedSearch = (id) => request(`/saved/${id}`, { method: 'DELETE' });
