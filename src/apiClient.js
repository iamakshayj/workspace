const DEFAULT_API_BASE_URL = process.env.NODE_ENV === 'production'
  ? window.location.origin
  : 'http://127.0.0.1:8000';

export const API_BASE_URL = (process.env.REACT_APP_API_BASE_URL || DEFAULT_API_BASE_URL)
  .replace(/\/+$/, '');

export function websocketBaseUrl(baseUrl = API_BASE_URL) {
  return baseUrl.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
}

export function notifyIfUnauthorized(response) {
  if (response.status === 401) {
    window.dispatchEvent(new Event('flowforge:unauthorized'));
  }
}
