import {
  createProjectArtifact, generateFlowchart, listProjects, saveProject, searchProjects,
  updateProjectGovernance,
} from './flowchartService';

afterEach(() => jest.restoreAllMocks());

test('creates and polls a durable flowchart generation job', async () => {
  const result = { title: 'Approval', nodes: [], edges: [], questions: [], warnings: [] };
  global.fetch = jest.fn()
    .mockResolvedValueOnce({ ok: true, status: 202, json: () => Promise.resolve({ id: 'job-1', status: 'queued' }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ id: 'job-1', status: 'succeeded', result }) });

  await expect(generateFlowchart('Start then approve', { pollInterval: 0 })).resolves.toEqual(result);
  expect(global.fetch.mock.calls[0][0]).toMatch(/flowcharts\/generation-jobs$/);
  expect(global.fetch.mock.calls[1][0]).toMatch(/flowcharts\/generation-jobs\/job-1$/);
});

test('creates and polls a durable evidence-package job', async () => {
  const artifact = {
    id: 'artifact-1', filename: 'approval-evidence.zip',
    download_url: '/api/v1/projects/project-1/artifacts/artifact-1/download',
  };
  global.fetch = jest.fn()
    .mockResolvedValueOnce({ ok: true, status: 202, json: () => Promise.resolve({ id: 'job-2', status: 'queued' }) })
    .mockResolvedValueOnce({
      ok: true, status: 200,
      json: () => Promise.resolve({ id: 'job-2', status: 'succeeded', artifact }),
    });

  await expect(createProjectArtifact('project-1', {
    kind: 'evidence_package', format: 'zip', pollInterval: 0,
  })).resolves.toEqual(artifact);
  expect(global.fetch.mock.calls[0][0]).toMatch(/projects\/project-1\/artifact-jobs$/);
  expect(JSON.parse(global.fetch.mock.calls[0][1].body)).toEqual({
    kind: 'evidence_package', format: 'zip',
  });
  expect(global.fetch.mock.calls[1][0]).toMatch(/artifact-jobs\/job-2$/);
});

test('lists projects through the GraphQL endpoint', async () => {
  global.fetch = jest.fn(() => Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ data: { projects: [{ id: 'project-1', title: 'Onboarding' }] } }),
  }));

  await expect(listProjects()).resolves.toEqual([{ id: 'project-1', title: 'Onboarding' }]);
  expect(global.fetch).toHaveBeenCalledWith(
    expect.stringMatching(/\/graphql$/),
    expect.objectContaining({ method: 'POST', credentials: 'include' })
  );
  const payload = JSON.parse(global.fetch.mock.calls[0][1].body);
  expect(payload.query).toContain('query Projects');
  expect(payload.query).toContain('node_count: nodeCount');
  expect(payload.query).toContain('deliverable_count: deliverableCount');
  expect(payload.query).toContain('plan_progress: planProgress');
});

test('maps the flowchart graph into typed GraphQL mutation input', async () => {
  global.fetch = jest.fn(() => Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ data: { createProject: { id: 'project-2' } } }),
  }));
  const project = {
    title: 'Approval',
    description: 'Approval policy and escalation map.',
    status: 'draft',
    owner_id: 'user-1',
    collaborator_ids: ['user-1', 'user-2'],
    source_text: 'Start then approve',
    graph: {
      title: 'Approval',
      nodes: [{
        id: 'start', label: 'Start', type: 'start', shape: 'ellipse', symbol: 'bpmn_start',
        width: 96, height: 96, x: 0, y: 0, owner: 'Operations', backup_owner: 'Finance',
        system: 'ERP', vendor: 'Acme', control_id: 'CTRL-1', policy_reference: 'POL-2',
        evidence_requirement: 'Approval log', segregation_rule: 'Requester cannot approve',
        risk_level: 'high', data_classification: 'confidential', sla_minutes: 30,
        review_date: '2026-12-01', required: true, layer: 'Controls', parent_id: 'lane-1',
      }],
      edges: [{ source: 'start', target: 'start', label: 'Retry', is_loop: true, bidirectional: false }],
      questions: [],
      warnings: [{ code: 'loop', message: 'Check retry', node_ids: ['start'] }],
    },
  };

  await expect(saveProject(null, project)).resolves.toEqual({ id: 'project-2' });
  const payload = JSON.parse(global.fetch.mock.calls[0][1].body);
  expect(payload.query).toContain('mutation CreateProject');
  expect(payload.variables.input.sourceText).toBe('Start then approve');
  expect(payload.variables.input).toEqual(expect.objectContaining({
    description: 'Approval policy and escalation map.',
    status: 'draft',
    ownerId: 'user-1',
    collaboratorIds: ['user-1', 'user-2'],
  }));
  expect(payload.variables.input.graph.edges[0]).toEqual(expect.objectContaining({ isLoop: true }));
  expect(payload.variables.input.graph.nodes[0]).toEqual(expect.objectContaining({
    shape: 'ellipse', symbol: 'bpmn_start', width: 96, height: 96,
    backupOwner: 'Finance', controlId: 'CTRL-1', policyReference: 'POL-2',
    evidenceRequirement: 'Approval log', segregationRule: 'Requester cannot approve',
    riskLevel: 'high', dataClassification: 'confidential', slaMinutes: 30,
    reviewDate: '2026-12-01', required: true, layer: 'Controls', parentId: 'lane-1',
  }));
  expect(payload.variables.input.graph.nodes[0]).not.toHaveProperty('backup_owner');
  expect(payload.variables.input.graph.edges[0]).not.toHaveProperty('is_loop');
  expect(payload.variables.input.graph.warnings[0]).toEqual(expect.objectContaining({ nodeIds: ['start'] }));
});

test('searches projects with a stable cursor page contract', async () => {
  const page = {
    items: [{ id: 'project-2', title: 'Approval' }],
    next_cursor: 'cursor-2',
    total_count: 27,
  };
  global.fetch = jest.fn(() => Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ data: { projectPage: page } }),
  }));

  await expect(searchProjects({ search: 'approval', after: 'cursor-1', first: 12 }))
    .resolves.toEqual(page);
  const payload = JSON.parse(global.fetch.mock.calls[0][1].body);
  expect(payload.query).toContain('query ProjectPage');
  expect(payload.variables).toEqual({ search: 'approval', after: 'cursor-1', first: 12 });
});

test('sends the current document revision and exposes save conflict details', async () => {
  global.fetch = jest.fn(() => Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ errors: [{
      message: 'Reload before saving.',
      extensions: { code: 'CONFLICT', currentRevision: 9 },
    }] }),
  }));
  const project = {
    title: 'Approval', document_revision: 8, source_text: '', graph: {
      title: 'Approval', nodes: [], edges: [], questions: [], warnings: [],
    },
  };

  await expect(saveProject('project-2', project)).rejects.toEqual(expect.objectContaining({
    code: 'CONFLICT', details: expect.objectContaining({ currentRevision: 9 }),
  }));
  const payload = JSON.parse(global.fetch.mock.calls[0][1].body);
  expect(payload.query).toContain('$expectedRevision: Int!');
  expect(payload.variables.expectedRevision).toBe(8);
});

test('maps project access roles into the governance mutation', async () => {
  const governance = {
    project_id: 'project-1', visibility: 'restricted', approval_status: 'draft',
    current_user_access: 'admin', current_revision: 2, access_entries: [],
    revisions: [], approval: null, audit_events: [],
  };
  global.fetch = jest.fn(() => Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ data: { updateProjectGovernance: governance } }),
  }));

  await expect(updateProjectGovernance('project-1', 'restricted', [
    { user_id: 'user-2', access_role: 'approver' },
  ])).resolves.toEqual(governance);

  const payload = JSON.parse(global.fetch.mock.calls[0][1].body);
  expect(payload.query).toContain('mutation UpdateProjectGovernance');
  expect(payload.variables).toEqual({
    projectId: 'project-1',
    visibility: 'restricted',
    accessEntries: [{ userId: 'user-2', accessRole: 'approver' }],
  });
});
