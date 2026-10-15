import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

export class EntityApiError extends Error {
  constructor(message, code = 'request_failed') {
    super(message);
    this.name = 'EntityApiError';
    this.code = code;
  }
}

async function graphqlRequest(query, variables = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/graphql`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, variables }),
    });
  } catch {
    throw new EntityApiError('The workspace service is unavailable.', 'backend_unavailable');
  }
  const body = await response.json().catch(() => ({}));
  notifyIfUnauthorized(response);
  if (!response.ok || body.errors?.length) {
    const error = body.errors?.[0];
    throw new EntityApiError(
      error?.message || body.detail || 'The workspace request failed.',
      error?.extensions?.code || 'graphql_error'
    );
  }
  return body.data;
}

const WORKSPACE_FIELDS = `
  workspace { id name member_count: memberCount }
  workspace_members: workspaceMembers {
    id display_name: displayName email role created_at: createdAt is_current_user: isCurrentUser
  }
  workspace_invitations: workspaceInvitations {
    id display_name: displayName email job_title: jobTitle role status
    delivery_status: deliveryStatus expires_at: expiresAt created_at: createdAt
  }
`;

export function getWorkspaceTeam() {
  return graphqlRequest(`query WorkspaceTeam { ${WORKSPACE_FIELDS} }`);
}

export function inviteWorkspaceMember(contact) {
  return graphqlRequest(`mutation InviteWorkspaceMember($input: InviteMemberInput!) {
    inviteWorkspaceMember(input: $input) {
      id display_name: displayName email job_title: jobTitle role status
      delivery_status: deliveryStatus expires_at: expiresAt created_at: createdAt setup_url: setupUrl
    }
  }`, {
    input: {
      displayName: contact.display_name,
      email: contact.email,
      role: contact.role,
      jobTitle: contact.job_title || null,
    },
  }).then((data) => data.inviteWorkspaceMember);
}

export function updateWorkspaceMemberRole(userId, role) {
  return graphqlRequest(`mutation UpdateWorkspaceMemberRole($userId: ID!, $role: String!) {
    updateWorkspaceMemberRole(userId: $userId, role: $role) {
      id display_name: displayName email role created_at: createdAt is_current_user: isCurrentUser
    }
  }`, { userId, role }).then((data) => data.updateWorkspaceMemberRole);
}

export function cancelWorkspaceInvitation(invitationId) {
  return graphqlRequest(`mutation CancelWorkspaceInvitation($invitationId: ID!) {
    cancelWorkspaceInvitation(invitationId: $invitationId)
  }`, { invitationId }).then((data) => data.cancelWorkspaceInvitation);
}
