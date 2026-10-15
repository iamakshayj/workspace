import { API_BASE_URL, notifyIfUnauthorized } from './apiClient';

export class FlowchartApiError extends Error {
  constructor(message, code = 'request_failed', details = {}) {
    super(message);
    this.name = 'FlowchartApiError';
    this.code = code;
    this.details = details;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...options.headers },
    });
  } catch (error) {
    throw new FlowchartApiError(
      'Workspace is temporarily unavailable. Please try again in a moment.',
      'backend_unavailable'
    );
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    notifyIfUnauthorized(response);
    throw new FlowchartApiError(
      body.detail || 'The workflow request failed.',
      body.code || 'request_failed'
    );
  }
  return body;
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
    throw new FlowchartApiError(
      'Workspace is temporarily unavailable. Please try again in a moment.',
      'backend_unavailable'
    );
  }

  const body = await response.json().catch(() => ({}));
  notifyIfUnauthorized(response);
  if (!response.ok || body.errors?.length) {
    const error = body.errors?.[0];
    throw new FlowchartApiError(
      error?.message || body.detail || 'The GraphQL request failed.',
      error?.extensions?.code || 'graphql_error',
      error?.extensions || {}
    );
  }
  return body.data;
}

const PROJECT_FIELDS = `
  id
  title
  description
  status
  visibility
  approval_status: approvalStatus
  current_user_access: currentUserAccess
  revision_number: revisionNumber
  document_revision: documentRevision
  owner { id display_name: displayName email role color }
  collaborators { id display_name: displayName email role color }
  profile {
    key sponsor_id: sponsorId department team program priority health
    start_date: startDate target_date: targetDate progress classification tags template
  }
  source_text: sourceText
  created_at: createdAt
  updated_at: updatedAt
  graph {
    title
    nodes {
      id label type owner description color shape symbol width height x y
      backup_owner: backupOwner
      system vendor
      control_id: controlId
      policy_reference: policyReference
      evidence_requirement: evidenceRequirement
      segregation_rule: segregationRule
      risk_level: riskLevel
      data_classification: dataClassification
      sla_minutes: slaMinutes
      review_date: reviewDate
      required layer
      parent_id: parentId
    }
    edges { source target label is_loop: isLoop bidirectional }
    questions
    warnings { code message node_ids: nodeIds }
  }
`;

function toProjectInput(project) {
  return {
    title: project.title,
    description: project.description || '',
    status: project.status || 'active',
    ownerId: project.owner_id || null,
    collaboratorIds: project.collaborator_ids || [],
    profile: project.profile || {},
    sourceText: project.source_text,
    graph: {
      ...project.graph,
      nodes: project.graph.nodes.map((node) => ({
        id: node.id,
        label: node.label,
        type: node.type,
        owner: node.owner,
        description: node.description,
        color: node.color,
        shape: node.shape,
        symbol: node.symbol,
        width: node.width,
        height: node.height,
        x: node.x,
        y: node.y,
        backupOwner: node.backup_owner,
        system: node.system,
        vendor: node.vendor,
        controlId: node.control_id,
        policyReference: node.policy_reference,
        evidenceRequirement: node.evidence_requirement,
        segregationRule: node.segregation_rule,
        riskLevel: node.risk_level,
        dataClassification: node.data_classification,
        slaMinutes: node.sla_minutes,
        reviewDate: node.review_date,
        required: node.required,
        layer: node.layer,
        parentId: node.parent_id,
      })),
      edges: project.graph.edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        label: edge.label,
        isLoop: edge.is_loop,
        bidirectional: edge.bidirectional,
      })),
      warnings: project.graph.warnings.map((warning) => ({
        code: warning.code,
        message: warning.message,
        nodeIds: warning.node_ids || [],
      })),
    },
  };
}

export function getHealth() {
  return request('/health');
}

export async function generateFlowchart(text, { pollInterval = 750 } = {}) {
  let job = await request('/api/v1/flowcharts/generation-jobs', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
  while (job.status === 'queued' || job.status === 'running') {
    await new Promise((resolve) => window.setTimeout(resolve, pollInterval));
    job = await request(`/api/v1/flowcharts/generation-jobs/${encodeURIComponent(job.id)}`);
  }
  if (job.status === 'succeeded' && job.result) return job.result;
  throw new FlowchartApiError(
    job.error_message || 'Workflow generation failed.',
    job.error_code || 'generation_failed'
  );
}

export async function createProjectArtifact(
  projectId,
  { kind = 'export', format = 'svg', pollInterval = 500 } = {}
) {
  let job = await request(`/api/v1/projects/${encodeURIComponent(projectId)}/artifact-jobs`, {
    method: 'POST',
    body: JSON.stringify({ kind, format }),
  });
  while (job.status === 'queued' || job.status === 'running') {
    await new Promise((resolve) => window.setTimeout(resolve, pollInterval));
    job = await request(
      `/api/v1/projects/${encodeURIComponent(projectId)}/artifact-jobs/${encodeURIComponent(job.id)}`
    );
  }
  if (job.status === 'succeeded' && job.artifact) return job.artifact;
  throw new FlowchartApiError(
    job.error_message || 'The project file could not be prepared.',
    job.error_code || 'artifact_failed'
  );
}

export function saveProject(projectId, project) {
  if (projectId) {
    return graphqlRequest(`mutation UpdateProject(
      $id: ID!, $input: ProjectInput!, $expectedRevision: Int!
    ) {
      updateProject(id: $id, input: $input, expectedRevision: $expectedRevision) {
        ${PROJECT_FIELDS}
      }
    }`, {
      id: projectId,
      input: toProjectInput(project),
      expectedRevision: project.document_revision ?? 0,
    }).then((data) => data.updateProject);
  }
  return graphqlRequest(`mutation CreateProject($input: ProjectInput!) {
    createProject(input: $input) { ${PROJECT_FIELDS} }
  }`, { input: toProjectInput(project) }).then((data) => data.createProject);
}

const PROJECT_SUMMARY_FIELDS = `
  id title description status visibility
  approval_status: approvalStatus
  current_user_access: currentUserAccess
  profile {
    key sponsor_id: sponsorId department team program priority health
    start_date: startDate target_date: targetDate progress classification tags template
  }
  owner { id display_name: displayName email role color }
  collaborators { id display_name: displayName email role color }
  collaborator_count: collaboratorCount
  deliverable_count: deliverableCount
  completed_deliverable_count: completedDeliverableCount
  task_count: taskCount
  completed_task_count: completedTaskCount
  plan_progress: planProgress
  created_at: createdAt
  updated_at: updatedAt
  node_count: nodeCount
  edge_count: edgeCount
`;

export function searchProjects({ search = '', after = null, first = 24 } = {}) {
  return graphqlRequest(`query ProjectPage(
    $search: String!, $after: String, $first: Int!
  ) {
    projectPage(search: $search, after: $after, first: $first) {
      items { ${PROJECT_SUMMARY_FIELDS} }
      next_cursor: nextCursor
      total_count: totalCount
    }
  }`, { search, after, first }).then((data) => data.projectPage);
}

export function listProjects() {
  return graphqlRequest(`query Projects {
    projects {
      id
      title
      description
      status
      visibility
      approval_status: approvalStatus
      current_user_access: currentUserAccess
      profile {
        key sponsor_id: sponsorId department team program priority health
        start_date: startDate target_date: targetDate progress classification tags template
      }
      owner { id display_name: displayName email role color }
      collaborators { id display_name: displayName email role color }
      collaborator_count: collaboratorCount
      deliverable_count: deliverableCount
      completed_deliverable_count: completedDeliverableCount
      task_count: taskCount
      completed_task_count: completedTaskCount
      plan_progress: planProgress
      created_at: createdAt
      updated_at: updatedAt
      node_count: nodeCount
      edge_count: edgeCount
    }
  }`).then((data) => data.projects);
}

export function getProject(projectId) {
  return graphqlRequest(`query Project($id: ID!) {
    project(id: $id) { ${PROJECT_FIELDS} }
  }`, { id: projectId }).then((data) => data.project);
}

export function deleteProject(projectId) {
  return graphqlRequest(`mutation DeleteProject($id: ID!) {
    deleteProject(id: $id)
  }`, { id: projectId }).then((data) => data.deleteProject);
}

const GOVERNANCE_FIELDS = `
  project_id: projectId
  visibility
  approval_status: approvalStatus
  current_user_access: currentUserAccess
  current_revision: currentRevision
  access_entries: accessEntries {
    access_role: accessRole
    user { id display_name: displayName email role color }
  }
  revisions {
    id version change_summary: changeSummary created_at: createdAt title status node_count: nodeCount edge_count: edgeCount
    created_by: createdBy { id display_name: displayName email role color }
  }
  approval {
    id revision_id: revisionId revision_version: revisionVersion status
    request_note: requestNote decision_note: decisionNote
    requested_at: requestedAt decided_at: decidedAt
    requested_by: requestedBy { id display_name: displayName email role color }
    reviewer { id display_name: displayName email role color }
  }
  audit_events: auditEvents {
    id action details created_at: createdAt
    actor { id display_name: displayName email role color }
  }
`;

export function getProjectGovernance(projectId) {
  return graphqlRequest(`query ProjectGovernance($projectId: ID!) {
    projectGovernance(projectId: $projectId) { ${GOVERNANCE_FIELDS} }
  }`, { projectId }).then((data) => data.projectGovernance);
}

export function updateProjectGovernance(projectId, visibility, accessEntries) {
  return graphqlRequest(`mutation UpdateProjectGovernance(
    $projectId: ID!, $visibility: String!, $accessEntries: [ProjectAccessInput!]!
  ) {
    updateProjectGovernance(
      projectId: $projectId, visibility: $visibility, accessEntries: $accessEntries
    ) { ${GOVERNANCE_FIELDS} }
  }`, {
    projectId,
    visibility,
    accessEntries: accessEntries.map((entry) => ({
      userId: entry.user_id || entry.user?.id,
      accessRole: entry.access_role,
    })),
  }).then((data) => data.updateProjectGovernance);
}

export function requestProjectApproval(projectId, note = '') {
  return graphqlRequest(`mutation RequestProjectApproval($projectId: ID!, $note: String!) {
    requestProjectApproval(projectId: $projectId, note: $note) { ${GOVERNANCE_FIELDS} }
  }`, { projectId, note }).then((data) => data.requestProjectApproval);
}

export function decideProjectApproval(projectId, decision, note = '') {
  return graphqlRequest(`mutation DecideProjectApproval(
    $projectId: ID!, $decision: String!, $note: String!
  ) {
    decideProjectApproval(projectId: $projectId, decision: $decision, note: $note) {
      ${GOVERNANCE_FIELDS}
    }
  }`, { projectId, decision, note }).then((data) => data.decideProjectApproval);
}

export function restoreProjectRevision(projectId, revisionId) {
  return graphqlRequest(`mutation RestoreProjectRevision($projectId: ID!, $revisionId: ID!) {
    restoreProjectRevision(projectId: $projectId, revisionId: $revisionId) {
      ${PROJECT_FIELDS}
    }
  }`, { projectId, revisionId }).then((data) => data.restoreProjectRevision);
}
