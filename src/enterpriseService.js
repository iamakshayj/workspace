import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/enterprise${path}`, {
    credentials: 'include', ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  notifyIfUnauthorized(response);
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : payload.detail?.message || 'Enterprise request failed');
  return payload;
}

export const getEnterpriseOverview = () => request('/overview');
export const getOrganizationTimeline = (params = {}) => request(`/timeline?${new URLSearchParams(Object.entries(params).filter(([, value]) => value))}`);
export const getDependencyMap = (projectId = '') => request(`/dependencies${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`);
export const getProjectOverview = (projectId) => request(`/projects/${projectId}/overview`);
export const createOrganizationUnit = (payload) => request('/units', { method: 'POST', body: JSON.stringify(payload) });
export const updatePersonProfile = (id, payload) => request(`/people/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
export const createObjectRelationship = (payload) => request('/relationships', { method: 'POST', body: JSON.stringify(payload) });
export const deleteObjectRelationship = (id) => request(`/relationships/${id}`, { method: 'DELETE' });
export const createProjectRisk = (id, payload) => request(`/projects/${id}/risks`, { method: 'POST', body: JSON.stringify(payload) });
export const createProjectDecision = (id, payload) => request(`/projects/${id}/decisions`, { method: 'POST', body: JSON.stringify(payload) });
export const updateProjectSettings = (id, payload) => request(`/projects/${id}/settings`, { method: 'PUT', body: JSON.stringify(payload) });
export const updateProjectGroupAccess = (id, payload) => request(`/projects/${id}/group-access`, { method: 'PUT', body: JSON.stringify(payload) });
export const updateNotificationPreference = (payload) => request('/notification-preferences', { method: 'PUT', body: JSON.stringify(payload) });
export const snoozeNotification = (id, until) => request(`/notifications/${id}/snooze`, { method: 'PUT', body: JSON.stringify({ until }) });
export const saveWorkspaceView = (payload) => request('/views', { method: 'POST', body: JSON.stringify(payload) });
export const saveWorkspaceDashboard = (payload) => request('/dashboards', { method: 'POST', body: JSON.stringify(payload) });
export const createWorkspaceFile = (payload) => request('/files', { method: 'POST', body: JSON.stringify(payload) });
export const createApprovalDefinition = (payload) => request('/approval-definitions', { method: 'POST', body: JSON.stringify(payload) });
export const requestEnterpriseApproval = (payload) => request('/approvals', { method: 'POST', body: JSON.stringify(payload) });
export const requestProjectAccess = (payload) => request('/access-requests', { method: 'POST', body: JSON.stringify(payload) });
export const decideEnterpriseApproval = (id, payload) => request(`/approvals/${id}/decision`, { method: 'PUT', body: JSON.stringify(payload) });
export const saveMeetingIntelligence = (id, payload) => request(`/meetings/${id}/intelligence`, { method: 'PUT', body: JSON.stringify(payload) });
export const appendMeetingCallArtifacts = (id, payload) => request(`/meetings/${id}/call-artifacts`, { method: 'POST', body: JSON.stringify(payload) });
export const extractMeetingFollowups = (id) => request(`/meetings/${id}/extract-followups`, { method: 'POST' });
export const saveCalendarWorkspaceSettings = (payload) => request('/calendar/settings', { method: 'PUT', body: JSON.stringify(payload) });
export const verifyAuditChain = () => request('/audit/verify');
export const saveAuditSettings = (payload) => request('/audit/settings', { method: 'PUT', body: JSON.stringify(payload) });
export const runEnterpriseReport = (payload) => request('/reports/run', { method: 'POST', body: JSON.stringify(payload) });
export const auditExportUrl = `${API_BASE_URL}/api/v1/enterprise/audit/export`;
