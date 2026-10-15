import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

export const SCIM_BASE_URL = `${API_BASE_URL}/scim/v2`;

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/identity${path}`, {
    credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  notifyIfUnauthorized(response);
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : payload.detail?.message || 'Identity request failed');
  return payload;
}

export const listIdentityProviders = () => request('/providers');
export const createIdentityProvider = (payload) => request('/providers', { method: 'POST', body: JSON.stringify(payload) });
export const updateIdentityProvider = (id, payload) => request(`/providers/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
export const testIdentityProvider = (id) => request(`/providers/${id}/test`, { method: 'POST' });
export const createSamlProvider = (payload) => request('/saml/providers', { method: 'POST', body: JSON.stringify(payload) });
export const updateSamlProvider = (id, payload) => request(`/saml/providers/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
export const testSamlProvider = (id) => request(`/saml/providers/${id}/test`, { method: 'POST' });
export const inspectSamlMetadata = (metadataUrl) => request('/saml/metadata/inspect', { method: 'POST', body: JSON.stringify({ metadata_url: metadataUrl }) });
export const addSamlCertificate = (id, certificate) => request(`/saml/providers/${id}/certificates`, { method: 'POST', body: JSON.stringify({ x509_certificate: certificate }) });
export const changeSamlCertificate = (id, certificateId, action) => request(`/saml/providers/${id}/certificates/${certificateId}/${action}`, { method: 'POST' });
export const createDomainChallenge = (id, domain) => request(`/providers/${id}/domains`, { method: 'POST', body: JSON.stringify({ domain }) });
export const verifyIdentityDomain = (id, domain) => request(`/providers/${id}/domains/${encodeURIComponent(domain)}/verify`, { method: 'POST' });
export const listScimTokens = () => request('/scim/tokens');
export const createScimToken = (payload) => request('/scim/tokens', { method: 'POST', body: JSON.stringify(payload) });
export const revokeScimToken = (id) => request(`/scim/tokens/${id}`, { method: 'DELETE' });
