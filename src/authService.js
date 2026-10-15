import { API_BASE_URL } from './apiClient';

export class AuthApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.name = 'AuthApiError';
    this.status = status;
    this.details = details;
  }
}

async function authRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/auth${path}`, {
      ...options,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...options.headers },
    });
  } catch {
    throw new AuthApiError('Sign-in is temporarily unavailable. Please try again in a moment.');
  }

  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail;
    throw new AuthApiError(typeof detail === 'string' ? detail : detail?.message || 'Authentication failed.', response.status, typeof detail === 'object' ? detail : null);
  }
  return body;
}

export async function getCurrentUser() {
  try {
    return await authRequest('/me');
  } catch (error) {
    if (error.status === 401) return null;
    throw error;
  }
}

export function loginAccount(email, password, mfaCode = '') {
  return authRequest('/login', { method: 'POST', body: JSON.stringify({ email, password, ...(mfaCode ? { mfa_code: mfaCode } : {}) }) });
}

export const discoverSso = (email) => authRequest('/sso/discover', {
  method: 'POST', body: JSON.stringify({ email }),
});

export const discoverFederatedLogout = () => authRequest('/sso/logout/discover');

export function getInvitation(token) {
  return authRequest(`/invitations/${encodeURIComponent(token)}`);
}

export function acceptInvitation(token, password) {
  return authRequest('/invitations/accept', {
    method: 'POST',
    body: JSON.stringify({ token, password }),
  });
}

export function updateAccount(displayName, email) {
  return authRequest('/me', {
    method: 'PUT',
    body: JSON.stringify({ display_name: displayName, email }),
  });
}

export function logoutAccount() {
  return authRequest('/logout', { method: 'POST' });
}

export const getSecuritySummary = () => authRequest('/security');
export const enrollMfa = (password) => authRequest('/mfa/enroll', { method: 'POST', body: JSON.stringify({ password }) });
export const confirmMfa = (code) => authRequest('/mfa/confirm', { method: 'POST', body: JSON.stringify({ code }) });
export const stepUpMfa = (code) => authRequest('/mfa/step-up', { method: 'POST', body: JSON.stringify({ code }) });
export const disableMfa = (password, code) => authRequest('/mfa/disable', { method: 'POST', body: JSON.stringify({ password, code }) });
export const revokeAuthSession = (sessionId) => authRequest(`/sessions/${sessionId}`, { method: 'DELETE' });
export const revokeOtherSessions = () => authRequest('/sessions/revoke-others', { method: 'POST' });
export const getAuthenticationPolicy = () => authRequest('/policy');
export const updateAuthenticationPolicy = (policy) => authRequest('/policy', { method: 'PUT', body: JSON.stringify(policy) });
