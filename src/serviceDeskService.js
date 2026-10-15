import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/service-desk${path}`, {
    credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  notifyIfUnauthorized(response);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : payload.detail?.message || 'Service desk request failed');
  return payload;
}

const json = (method, body) => ({ method, body: JSON.stringify(body) });
export const getServiceTickets = (params = {}) => request(`?${new URLSearchParams(Object.entries(params).filter(([, value]) => value != null && value !== '')).toString()}`);
export const createServiceTicket = (payload) => request('', json('POST', payload));
export const updateServiceTicket = (id, payload) => request(`/${id}`, json('PATCH', payload));
export const getServiceTicketComments = (id) => request(`/${id}/comments`);
export const addServiceTicketComment = (id, payload) => request(`/${id}/comments`, json('POST', payload));
export const getOnCallSchedules = () => request('/configuration/on-call');
export const createOnCallSchedule = (payload) => request('/configuration/on-call', json('POST', payload));
export const getGuestGrants = () => request('/configuration/guest-grants');
export const createGuestGrant = (payload) => request('/configuration/guest-grants', json('POST', payload));
export const revokeGuestGrant = (id) => request(`/configuration/guest-grants/${id}/revoke`, { method: 'POST' });
