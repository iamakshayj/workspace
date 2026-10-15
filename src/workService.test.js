import {
  createNodeWorkItem, createWorkItem, getProjectPlanning, getWorkOverview,
  updateNodePlanning, updateWorkItem, updateWorkWorkflow,
} from './workService';

beforeEach(() => {
  global.fetch = jest.fn();
});

afterEach(() => jest.restoreAllMocks());

test('loads the tenant work overview with the authenticated session', async () => {
  fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [], sprints: [] }) });
  await expect(getWorkOverview()).resolves.toEqual({ items: [], sprints: [] });
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/v1/work/overview'), expect.objectContaining({ credentials: 'include' }));
});

test('creates and revision-updates work items', async () => {
  fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: 'item-1' }) });
  await createWorkItem({ summary: 'Map onboarding' });
  await updateWorkItem('item-1', { expected_revision: 2, status: 'review' });
  expect(fetch.mock.calls[0][1]).toEqual(expect.objectContaining({ method: 'POST', body: JSON.stringify({ summary: 'Map onboarding' }) }));
  expect(fetch.mock.calls[1][1]).toEqual(expect.objectContaining({ method: 'PUT', body: JSON.stringify({ expected_revision: 2, status: 'review' }) }));
});

test('loads and updates flowchart node delivery planning', async () => {
  fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ nodes: {} }) });
  await getProjectPlanning('project one');
  await updateNodePlanning('project one', 'node/1', { expected_revision: 2, sprint_id: 'sprint-1' });
  await createNodeWorkItem('project one', 'node/1', { summary: 'Deliver step', item_type: 'story' });
  expect(fetch.mock.calls[0][0]).toContain('/projects/project%20one/planning');
  expect(fetch.mock.calls[1][0]).toContain('/projects/project%20one/nodes/node%2F1/planning');
  expect(fetch.mock.calls[1][1]).toEqual(expect.objectContaining({ method: 'PUT' }));
  expect(fetch.mock.calls[2][0]).toContain('/projects/project%20one/nodes/node%2F1/work-items');
  expect(fetch.mock.calls[2][1]).toEqual(expect.objectContaining({ method: 'POST' }));
});

test('updates the workspace workflow', async () => {
  fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ columns: [], item_types: [] }) });
  const payload = { columns: [{ id: 'todo' }, { id: 'done' }], item_types: [{ id: 'task' }] };
  await updateWorkWorkflow(payload);
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/v1/work/workflow'), expect.objectContaining({
    method: 'PUT', body: JSON.stringify(payload), credentials: 'include',
  }));
});
