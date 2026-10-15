import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

export async function getWorkIntelligenceBriefing() {
  const response = await fetch(`${API_BASE_URL}/api/v1/intelligence/briefing`, {
    credentials: 'include',
  });
  notifyIfUnauthorized(response);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof payload.detail === 'string'
      ? payload.detail
      : payload.detail?.message || 'Work intelligence is temporarily unavailable.');
  }
  return payload;
}
