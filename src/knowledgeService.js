import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/knowledge${path}`, {
    credentials: 'include',
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  notifyIfUnauthorized(response);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    const error = new Error(typeof detail === 'string' ? detail : detail?.message || 'Knowledge request failed');
    error.status = response.status;
    error.details = typeof detail === 'object' ? detail : null;
    throw error;
  }
  return payload;
}

export const getKnowledgeOverview = ({ search = '', spaceId = '', includeArchived = false } = {}) => {
  const query = new URLSearchParams();
  if (search) query.set('search', search);
  if (spaceId) query.set('space_id', spaceId);
  if (includeArchived) query.set('include_archived', 'true');
  return request(`/overview?${query}`);
};
export const getKnowledgeDocument = (documentId) => request(`/documents/${documentId}`);
export const createKnowledgeSpace = (payload) => request('/spaces', { method: 'POST', body: JSON.stringify(payload) });
export const updateKnowledgeSpace = (spaceId, payload) => request(`/spaces/${spaceId}`, { method: 'PUT', body: JSON.stringify(payload) });
export const createKnowledgeDocument = (payload) => request('/documents', { method: 'POST', body: JSON.stringify(payload) });
export const updateKnowledgeDocument = (documentId, payload) => request(`/documents/${documentId}`, { method: 'PUT', body: JSON.stringify(payload) });
export const duplicateKnowledgeDocument = (documentId, payload = {}) => request(`/documents/${documentId}/duplicate`, { method: 'POST', body: JSON.stringify(payload) });
export const followKnowledgeDocument = (documentId, following) => request(`/documents/${documentId}/follow`, { method: 'PUT', body: JSON.stringify({ following }) });
export const getKnowledgeRevision = (documentId, revisionId) => request(`/documents/${documentId}/revisions/${revisionId}`);
export const updateKnowledgeAccess = (documentId, entries) => request(`/documents/${documentId}/access`, { method: 'PUT', body: JSON.stringify({ entries }) });
export const addKnowledgeComment = (documentId, body, parentId = null) => request(`/documents/${documentId}/comments`, { method: 'POST', body: JSON.stringify({ body, parent_id: parentId }) });
export const resolveKnowledgeComment = (documentId, commentId) => request(`/documents/${documentId}/comments/${commentId}/resolve`, { method: 'PUT' });
export const restoreKnowledgeRevision = (documentId, revisionId, expectedRevision) => request(`/documents/${documentId}/restore/${revisionId}`, { method: 'POST', body: JSON.stringify({ expected_revision: expectedRevision }) });
