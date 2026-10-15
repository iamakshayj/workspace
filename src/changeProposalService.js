import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/change-proposals${path}`, {
    credentials: 'include',
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  notifyIfUnauthorized(response);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Governed change request failed');
  return payload;
}

export const getChangeProposals = (status = '') => request(status ? `?status=${encodeURIComponent(status)}` : '');
export const createChangeProposal = (payload) => request('', { method: 'POST', body: JSON.stringify(payload) });
export const decideChangeProposal = (id, decision, note = '') => request(`/${id}/decision`, {
  method: 'POST', body: JSON.stringify({ decision, note }),
});
export const applyChangeProposal = (id) => request(`/${id}/apply`, { method: 'POST' });
export const rollbackChangeProposal = (id) => request(`/${id}/rollback`, { method: 'POST' });
