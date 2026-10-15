import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

export async function askWorkspaceAssistant(messages, context = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/assistant/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, context }),
    });
  } catch {
    const error = new Error('Workspace AI is temporarily unavailable. Please try again shortly.');
    error.code = 'assistant_unavailable';
    throw error;
  }
  notifyIfUnauthorized(response);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.detail || 'Workspace AI could not answer that request.');
    error.code = payload.code || 'assistant_failed';
    throw error;
  }
  return payload;
}
