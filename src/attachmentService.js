import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function attachmentRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, { credentials: 'include', ...options });
  notifyIfUnauthorized(response);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || 'The attachment request failed.');
  }
  if (response.status === 204) return null;
  return response.json();
}

export function listAttachments(projectId) {
  return attachmentRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/attachments`);
}

export function uploadAttachment(projectId, nodeId, file) {
  return attachmentRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/attachments/uploads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: file.name,
      node_id: nodeId || null,
      content_type: file.type || 'application/octet-stream',
      size_bytes: file.size,
    }),
  }).then(async ({ attachment, upload }) => {
    const uploadUrl = upload.url.startsWith('/') ? `${API_BASE_URL}${upload.url}` : upload.url;
    let response;
    if (upload.method === 'POST') {
      const body = new FormData();
      Object.entries(upload.fields || {}).forEach(([key, value]) => body.append(key, value));
      body.append('file', file);
      response = await fetch(uploadUrl, { method: 'POST', body });
    } else {
      response = await fetch(uploadUrl, {
        method: upload.method || 'PUT',
        headers: upload.headers || {},
        body: file,
      });
    }
    if (!response.ok) throw new Error('The attachment could not be transferred to storage.');
    return attachmentRequest(
      `/api/v1/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachment.id)}/complete`,
      { method: 'POST' }
    );
  });
}

export function deleteAttachment(projectId, attachmentId) {
  return attachmentRequest(`/api/v1/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`, {
    method: 'DELETE',
  });
}

export function attachmentDownloadUrl(projectId, attachmentId) {
  return `${API_BASE_URL}/api/v1/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`;
}
