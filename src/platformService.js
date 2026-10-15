import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/platform${path}`, {
    credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  notifyIfUnauthorized(response);
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(typeof detail === 'string' ? detail : detail?.message || 'Platform request failed');
  }
  return payload;
}

const json = (method, payload) => ({ method, body: JSON.stringify(payload) });

export const getPlatformOverview = () => request('/overview');
export const createPolicy = (payload) => request('/policies', json('POST', payload));
export const updatePolicy = (id, payload) => request(`/policies/${id}`, json('PUT', payload));
export const deletePolicy = (id) => request(`/policies/${id}`, { method: 'DELETE' });
export const simulatePolicy = (payload) => request('/policies/simulate', json('POST', payload));
export const createDataPolicy = (payload) => request('/data-policies', json('POST', payload));
export const updateDataPolicy = (id, payload) => request(`/data-policies/${id}`, json('PUT', payload));
export const simulateDlp = (payload) => request('/data-policies/simulate', json('POST', payload));
export const createLegalHold = (payload) => request('/legal-holds', json('POST', payload));
export const releaseLegalHold = (id) => request(`/legal-holds/${id}/release`, { method: 'POST' });
export const createEncryptionKey = (payload) => request('/encryption-keys', json('POST', payload));
export const verifyEncryptionKey = (id) => request(`/encryption-keys/${id}/verify`, { method: 'POST' });
export const createIntegration = (payload) => request('/integrations', json('POST', payload));
export const syncIntegration = (id) => request(`/integrations/${id}/sync`, { method: 'POST' });
export const disconnectIntegration = (id) => request(`/integrations/${id}/disconnect`, { method: 'POST' });
export const createWebhook = (payload) => request('/webhooks', json('POST', payload));
export const disableWebhook = (id) => request(`/webhooks/${id}/disable`, { method: 'POST' });
export const testWebhook = (id, eventType = 'workspace.test') => request(`/webhooks/${id}/test`, json('POST', { event_type: eventType }));
export const createApiToken = (payload) => request('/api-tokens', json('POST', payload));
export const revokeApiToken = (id) => request(`/api-tokens/${id}/revoke`, { method: 'POST' });
export const requestSupportAccess = (payload) => request('/support-access', json('POST', payload));
export const decideSupportAccess = (id, payload) => request(`/support-access/${id}`, json('PUT', payload));
export const saveEntitlement = (feature, payload) => request(`/entitlements/${encodeURIComponent(feature)}`, json('PUT', payload));
export const recordOperationalEvent = (payload) => request('/operational-events', json('POST', payload));
export const resolveOperationalEvent = (id) => request(`/operational-events/${id}/resolve`, { method: 'POST' });
export const saveServiceObjective = (service, payload) => request(`/service-objectives/${encodeURIComponent(service)}/${encodeURIComponent(payload.metric)}`, json('PUT', payload));
export const getComplianceEvidence = () => request('/compliance/evidence');
export const SIEM_EXPORT_URL = `${API_BASE_URL}/api/v1/platform/compliance/siem-export`;
