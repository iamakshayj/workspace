import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import WorkManagement from './WorkManagement';
import { bulkUpdateWorkItems, createWorkItem, getWorkOverview, updateWorkWorkflow } from './workService';

jest.mock('./AccountControls', () => () => <div>Account</div>);
jest.mock('./workService', () => ({
  createRelease: jest.fn(), createSprint: jest.fn(), createWorkComment: jest.fn(),
  createWorkItem: jest.fn(), createWorkLink: jest.fn(), deleteWorkItem: jest.fn(),
  duplicateWorkItem: jest.fn(), followWorkItem: jest.fn(), bulkUpdateWorkItems: jest.fn(),
  getWorkOverview: jest.fn(), updateRelease: jest.fn(), updateSprint: jest.fn(), updateWorkItem: jest.fn(), updateWorkWorkflow: jest.fn(),
}));

const user = {
  id: 'user-1', display_name: 'Demo Admin', email: 'admin@example.com',
  entity_name: 'Northwind', role: 'admin', color: '#6657D9',
};
const baseItem = {
  description: '', acceptance_criteria: '', priority: 'medium', assignee: user,
  reporter: user, sprint_id: 'sprint-1', release_id: null, project_id: 'project-1',
  node_id: 'node-1', story_points: 3, estimate_minutes: null, labels: [],
  start_date: null, due_date: null, rank: 1024, revision: 0,
  comments: [], activity: [], links: [], created_at: '2026-08-29T00:00:00Z', updated_at: '2026-08-29T00:00:00Z',
};
const epic = { ...baseItem, id: 'epic-1', key: 'NW-1', sequence_number: 1, item_type: 'epic', summary: 'Approval experience', status: 'in_progress', parent_id: null, story_points: 8 };
const story = { ...baseItem, id: 'story-1', key: 'NW-2', sequence_number: 2, item_type: 'story', summary: 'Validate approval request', status: 'selected', parent_id: 'epic-1', story_points: 5 };
const subtask = { ...baseItem, id: 'subtask-1', key: 'NW-3', sequence_number: 3, item_type: 'subtask', summary: 'Add required-field checks', status: 'done', parent_id: 'story-1', story_points: 2 };
const overview = {
  current_user_role: 'admin', members: [user], items: [epic, story, subtask],
  sprints: [{ id: 'sprint-1', name: 'Sprint 1', status: 'active', goal: 'Ship approvals', capacity_points: 20 }],
  releases: [], projects: [{ id: 'project-1', title: 'Approval flow', nodes: [{ id: 'node-1', label: 'Validate request' }] }],
  workflow: {
    columns: [
      { id: 'backlog', label: 'Backlog', hint: 'Ideas', color: '#8792A3', category: 'queue', progress: 0, wip_limit: null },
      { id: 'selected', label: 'Ready', hint: 'Ready', color: '#4B84D8', category: 'queue', progress: 10, wip_limit: null },
      { id: 'in_progress', label: 'In progress', hint: 'Working', color: '#E09A34', category: 'active', progress: 40, wip_limit: 8 },
      { id: 'in_qa', label: 'In QA', hint: 'Testing', color: '#7A62D5', category: 'qa', progress: 80, wip_limit: 1 },
      { id: 'done', label: 'Done', hint: 'Delivered', color: '#2A9A70', category: 'done', progress: 100, wip_limit: null },
    ],
    item_types: [
      { id: 'epic', label: 'Epic', icon: '⚡', parent_types: [], child_type: 'story' },
      { id: 'story', label: 'Story', icon: '▤', parent_types: ['epic'], child_type: 'subtask' },
      { id: 'subtask', label: 'Subtask', icon: '↳', parent_types: ['story'], child_type: null },
      { id: 'task', label: 'Task', icon: '✓', parent_types: [], child_type: 'subtask' },
    ],
  },
};

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  window.history.replaceState({}, '', '/work?tab=stories');
  getWorkOverview.mockResolvedValue(overview);
  createWorkItem.mockResolvedValue({ ...subtask, id: 'subtask-2', key: 'NW-4' });
  updateWorkWorkflow.mockResolvedValue(overview.workflow);
});

test('shows QA stages and lets an administrator customize the workflow', async () => {
  window.history.replaceState({}, '', '/work?tab=board');
  render(<WorkManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByText('In QA')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Customize/ }));
  expect(screen.getByRole('heading', { name: 'Customize workflow' })).toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox', { name: 'Stage 4 name' }), { target: { value: 'Quality verification' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save workflow' }));

  await waitFor(() => expect(updateWorkWorkflow).toHaveBeenCalledWith(expect.objectContaining({
    columns: expect.arrayContaining([expect.objectContaining({ id: 'in_qa', label: 'Quality verification', category: 'qa' })]),
  })));
});

test('shows epic, story, and subtask hierarchy with flowchart links', async () => {
  const onNavigate = jest.fn();
  const { container } = render(<WorkManagement user={user} onNavigate={onNavigate} />);

  expect((await screen.findAllByRole('heading', { name: 'Stories & subtasks' })).length).toBeGreaterThan(0);
  expect(within(screen.getByRole('navigation', { name: 'Primary navigation' })).queryByRole('button', { name: 'Create work' })).not.toBeInTheDocument();
  expect(within(container.querySelector('.work-toolbar')).getByRole('button', { name: 'Create work' })).toBeInTheDocument();
  expect(await screen.findByText('Approval experience')).toBeInTheDocument();
  expect(screen.getByText('Validate approval request')).toBeInTheDocument();
  expect(screen.getByText('Add required-field checks')).toBeInTheDocument();
  expect(screen.getByText('workflow links')).toBeInTheDocument();
  expect(screen.getAllByText('Validate request').length).toBeGreaterThan(0);

  fireEvent.click(screen.getAllByRole('button', { name: /Approval flow/i })[0]);
  expect(onNavigate).toHaveBeenCalledWith('/projects/project-1?node=node-1');
});

test('creates a subtask that inherits its story and flowchart context', async () => {
  render(<WorkManagement user={user} onNavigate={jest.fn()} />);

  await screen.findByText('Validate approval request');
  fireEvent.click(screen.getByRole('button', { name: '＋ Subtask' }));

  expect(screen.getByRole('heading', { name: 'Add subtask to NW-2' })).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Type' })).toHaveValue('subtask');
  expect(screen.getByRole('combobox', { name: 'Parent work item' })).toHaveValue('story-1');
  fireEvent.change(screen.getByRole('textbox', { name: 'Summary' }), { target: { value: 'Implement validation states' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save work item' }));

  await waitFor(() => expect(createWorkItem).toHaveBeenCalledWith(expect.objectContaining({
    summary: 'Implement validation states', item_type: 'subtask', parent_id: 'story-1',
    sprint_id: 'sprint-1', project_id: 'project-1', node_id: 'node-1',
  })));
});

test('shows the active sprint by default and can expand to the workspace board', async () => {
  const unplanned = { ...baseItem, id: 'unplanned-1', key: 'NW-9', item_type: 'task', summary: 'Future unplanned work', status: 'backlog', sprint_id: null, parent_id: null };
  getWorkOverview.mockResolvedValue({ ...overview, items: [...overview.items, unplanned] });
  window.history.replaceState({}, '', '/work?tab=board');
  render(<WorkManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'Sprint 1' })).toBeInTheDocument();
  expect(screen.queryByText('Future unplanned work')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Active sprint ×' }));
  expect(screen.getByRole('heading', { name: 'Workspace board' })).toBeInTheDocument();
  expect(screen.getByText('Future unplanned work')).toBeInTheDocument();
});

test('opens an assistant-requested story form and responds to same-page sprint navigation', async () => {
  window.history.replaceState({}, '', '/work?create=1&source=assistant&item_type=story&request=1');
  const { rerender } = render(<WorkManagement user={user} onNavigate={jest.fn()} navigationKey={window.location.search} />);

  expect(await screen.findByRole('heading', { name: 'Create story' })).toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Type' })).toHaveValue('story');

  window.history.replaceState({}, '', '/work?tab=board&scope=active');
  rerender(<WorkManagement user={user} onNavigate={jest.fn()} navigationKey={window.location.search} />);

  expect(await screen.findByRole('heading', { name: 'Sprint 1' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Create story' })).not.toBeInTheDocument();
});

test('schedules a work session directly from a work item', async () => {
  const onNavigate = jest.fn();
  render(<WorkManagement user={user} onNavigate={onNavigate} />);

  await screen.findByText('Approval experience');
  fireEvent.click(screen.getByRole('button', { name: /NW-1.*Approval experience/i }));
  fireEvent.click(screen.getByRole('button', { name: /schedule work/i }));

  expect(onNavigate).toHaveBeenCalledWith(expect.stringMatching(/^\/calendar\?create=1&title=NW-1/));
});

test('filters the issue navigator with smart query syntax and bulk updates selected work', async () => {
  window.history.replaceState({}, '', '/work?tab=issues');
  bulkUpdateWorkItems.mockResolvedValue([{ ...story, status: 'in_qa', revision: 1 }]);
  const { container } = render(<WorkManagement user={user} onNavigate={jest.fn()} />);

  await screen.findByRole('heading', { name: 'Search, triage, and update work' });
  fireEvent.change(screen.getByRole('textbox', { name: 'Issue query' }), { target: { value: 'type:story assignee:me' } });
  expect(screen.getByText('Validate approval request')).toBeInTheDocument();
  expect(screen.queryByText('Approval experience')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('checkbox', { name: 'Select NW-2' }));
  const bulkBar = container.querySelector('.issue-bulk-bar');
  fireEvent.change(within(bulkBar).getByRole('combobox', { name: 'Bulk value' }), { target: { value: 'in_qa' } });
  fireEvent.click(within(bulkBar).getByRole('button', { name: 'Apply' }));

  await waitFor(() => expect(bulkUpdateWorkItems).toHaveBeenCalledWith({ item_ids: ['story-1'], status: 'in_qa' }));
});

test('shows cross-project blockers in the dependency control view', async () => {
  window.history.replaceState({}, '', '/work?tab=dependencies');
  const link = { id: 'link-1', source_id: 'epic-1', target_id: 'story-1', link_type: 'blocks' };
  getWorkOverview.mockResolvedValue({ ...overview, items: [{ ...epic, links: [link] }, { ...story, links: [link] }, subtask] });
  render(<WorkManagement user={user} onNavigate={jest.fn()} />);

  expect(await screen.findByRole('heading', { name: 'Cross-project delivery paths' })).toBeInTheDocument();
  expect(screen.getByText('Blocking links').nextSibling).toHaveTextContent('1');
  expect(screen.getByText('Approval experience')).toBeInTheDocument();
  expect(screen.getByText('Validate approval request')).toBeInTheDocument();
});

test('batches large bulk updates into backend-safe groups', async () => {
  window.history.replaceState({}, '', '/work?tab=issues');
  const manyItems = Array.from({ length: 101 }, (_, index) => ({
    ...baseItem, id: `many-${index}`, key: `NW-${index + 10}`, sequence_number: index + 10,
    item_type: 'task', summary: `Bulk item ${index + 1}`, status: 'backlog', sprint_id: null,
    project_id: null, node_id: null, parent_id: null, rank: (index + 1) * 1024,
  }));
  getWorkOverview.mockResolvedValue({ ...overview, items: manyItems });
  bulkUpdateWorkItems.mockImplementation(({ item_ids: itemIds }) => Promise.resolve(itemIds.map((id) => ({ id, status: 'selected' }))));
  const { container } = render(<WorkManagement user={user} onNavigate={jest.fn()} />);

  await screen.findByText('Bulk item 1');
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select all matching issues' }));
  const bulkBar = container.querySelector('.issue-bulk-bar');
  fireEvent.change(within(bulkBar).getByRole('combobox', { name: 'Bulk value' }), { target: { value: 'selected' } });
  fireEvent.click(within(bulkBar).getByRole('button', { name: 'Apply' }));

  await waitFor(() => expect(bulkUpdateWorkItems).toHaveBeenCalledTimes(2));
  expect(bulkUpdateWorkItems.mock.calls[0][0].item_ids).toHaveLength(100);
  expect(bulkUpdateWorkItems.mock.calls[1][0].item_ids).toHaveLength(1);
});
