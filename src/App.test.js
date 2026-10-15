import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App, { collaborativeDocument, readStoredArray } from './App';

let mockUser;

beforeEach(() => {
  window.history.replaceState({}, '', '/');
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('data-theme-preference');
  mockUser = {
    id: 'user-1', display_name: 'FlowForge User', email: 'local@flowforge.app',
    entity_id: 'entity-1', entity_name: 'Northwind Operations', role: 'admin',
  };
  global.fetch = jest.fn((url, options = {}) => {
    let body = [];
    if (url.endsWith('/health')) body = { status: 'ok', model: 'local-test-model', model_server_reachable: true };
    if (url.endsWith('/auth/me')) {
      const updates = options.body ? JSON.parse(options.body) : {};
      body = { ...mockUser, display_name: updates.display_name || mockUser.display_name, email: updates.email || mockUser.email };
    }
    if (url.endsWith('/graphql')) {
      const query = JSON.parse(options.body || '{}').query || '';
      if (query.includes('CommunicationOverview')) body = { data: {
        communication_contacts: [{
          user: { id: 'user-2', display_name: 'Taylor Morgan', email: 'taylor@example.com', role: 'basic', handle: 'taylor-user', color: '#258A71' },
          unread_count: 1, latest_message: 'Can you review this?', latest_message_at: '2026-08-26T01:00:00Z',
        }],
        notifications: [{
          id: 'notification-1', kind: 'mention', title: 'Taylor Morgan mentioned you', body: '@local-user Please review this note.',
          project_id: 'project-1', contact_id: null, read: false, created_at: '2026-08-26T01:00:00Z', actor: null,
        }],
      } };
      else if (query.includes('DirectMessages')) body = { data: { direct_messages: [] } };
      else if (query.includes('SendDirectMessage')) body = { data: { sendDirectMessage: {
        id: 'message-1', body: 'Can you review the approval step?', read: false, created_at: '2026-08-26T01:05:00Z',
        sender: { id: 'user-1', display_name: 'FlowForge User', email: 'local@flowforge.app', role: 'admin', handle: 'local-user', color: '#6D5CE8' },
        recipient: { id: 'user-2', display_name: 'Taylor Morgan', email: 'taylor@example.com', role: 'basic', handle: 'taylor-user', color: '#258A71' },
      } } };
      else if (query.includes('MarkDirectConversationRead')) body = { data: { markDirectConversationRead: true } };
      else if (query.includes('MarkNotificationRead')) body = { data: { markNotificationRead: true } };
      else if (query.includes('query ProjectPage')) body = { data: {
        projectPage: { items: [], next_cursor: null, total_count: 0 },
      } };
      else if (query.includes('query Project($id: ID!)')) body = { data: { project: {
        id: 'project-1', title: 'Approval workflow', description: 'Review and approve requests.', status: 'active',
        document_revision: 3,
        owner: { id: 'user-1', display_name: 'FlowForge User', email: 'local@flowforge.app', role: 'admin', color: '#6D5CE8' },
        collaborators: [{ id: 'user-1', display_name: 'FlowForge User', email: 'local@flowforge.app', role: 'admin', color: '#6D5CE8' }],
        source_text: 'Review the request.', created_at: '2026-08-26T00:00:00Z', updated_at: '2026-08-26T00:00:00Z',
        graph: {
          title: 'Approval workflow',
          nodes: [{ id: 'approval', label: 'Approval step', type: 'process', x: 80, y: 80, owner: null, description: null, color: null }],
          edges: [], questions: [], warnings: [],
        },
      } } };
      else if (query.includes('WorkspaceTeam')) body = { data: {
        workspace: { id: 'entity-1', name: 'Northwind Operations', member_count: 1 },
        workspace_members: [{ ...mockUser, created_at: '2026-08-26T00:00:00Z', is_current_user: true }],
        workspace_invitations: [],
      } };
      else if (query.includes('InviteWorkspaceMember')) body = { data: { inviteWorkspaceMember: {
        id: 'invite-1', display_name: 'Taylor Morgan', email: 'taylor@example.com', job_title: 'Operations',
        role: 'basic', status: 'pending', delivery_status: 'logged', expires_at: '2026-09-02T00:00:00Z',
        created_at: '2026-08-26T00:00:00Z', setup_url: 'http://127.0.0.1:3000/accept-invite?token=test',
      } } };
      else body = { data: { projects: [] } };
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
  });
  localStorage.clear();
});

afterEach(() => jest.restoreAllMocks());

async function createFlowchartFromLibrary() {
  fireEvent.click(screen.getByRole('button', { name: /^workflows$/i }));
  await screen.findByRole('heading', { name: /^workflows$/i });
  fireEvent.click(screen.getByRole('button', { name: /^create workflow$/i }));
}

test('renders the personal dashboard and opens the flowchart library from navigation', async () => {
  render(<App />);
  expect(screen.getByText('Workspace')).toBeInTheDocument();
  expect(await screen.findByRole('heading', { name: /good .*flowforge/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /assigned to me/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /^today$/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /workflow health/i })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /new workflow/i })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /notifications/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /messages/i })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /open account menu/i })).toBeInTheDocument();
  expect(within(screen.getByRole('navigation', { name: 'Primary navigation' })).getByRole('button', { name: 'Home' })).toHaveAttribute('aria-current', 'page');
  fireEvent.click(screen.getByRole('button', { name: /^workflows$/i }));
  expect(window.location.pathname).toBe('/workflows');
  expect(await screen.findByRole('heading', { name: /^workflows$/i })).toBeInTheDocument();
  expect(within(screen.getByRole('navigation', { name: 'Primary navigation' })).getByRole('button', { name: 'Workflows' })).toHaveAttribute('aria-current', 'page');
  expect(screen.getByRole('searchbox', { name: /search workflows/i })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /messages/i }));
  expect(await screen.findByText('@taylor-user')).toBeInTheDocument();
});

test('searches the project catalog through the paginated query', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });
  fireEvent.click(screen.getByRole('button', { name: /^workflows$/i }));
  const search = await screen.findByRole('searchbox', { name: /search workflows/i });
  fireEvent.change(search, { target: { value: 'approval' } });

  await waitFor(() => {
    const request = global.fetch.mock.calls
      .filter(([url]) => url.endsWith('/graphql'))
      .map(([, options]) => JSON.parse(options.body || '{}'))
      .find((payload) => payload.query?.includes('query ProjectPage') && payload.variables?.search === 'approval');
    expect(request).toBeTruthy();
    expect(request.variables).toEqual({ search: 'approval', after: null, first: 24 });
  });
});

test('ignores corrupted locally cached canvas data', () => {
  localStorage.setItem('broken', '{not valid JSON');
  localStorage.setItem('wrong-shape', '{"nodes":[]}');

  expect(readStoredArray('broken')).toEqual([]);
  expect(readStoredArray('wrong-shape')).toEqual([]);
});

test('syncs only graph fields through the collaboration socket', () => {
  const graph = { title: 'Approval', nodes: [], edges: [], questions: [], warnings: [] };

  expect(collaborativeDocument({
    title: 'Approval', source_text: 'Approve it.', graph,
    description: 'REST-owned metadata', owner_id: 'user-1', collaborator_ids: ['user-1'],
  })).toEqual({ title: 'Approval', source_text: 'Approve it.', graph });
});

test('sends a private message to an entity contact', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });
  fireEvent.click(screen.getByRole('button', { name: /messages/i }));
  fireEvent.click(await screen.findByRole('button', { name: /message Taylor Morgan/i }));
  await screen.findByText(/Say hello/i);
  fireEvent.change(await screen.findByLabelText(/message Taylor Morgan/i), {
    target: { value: 'Can you review the approval step?' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  expect(await screen.findByText('Can you review the approval step?')).toBeInTheDocument();
});

test('opens persisted notifications and editable profile settings', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });

  fireEvent.click(screen.getByRole('button', { name: /notifications/i }));
  const notificationPanel = screen.getByLabelText('Notifications panel');
  expect(within(notificationPanel).getByRole('heading', { name: 'Notifications' })).toBeInTheDocument();
  expect(await within(notificationPanel).findByText(/Taylor Morgan mentioned you/i)).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /open account menu/i }));
  fireEvent.click(screen.getByRole('button', { name: /profile.*name and email/i }));
  expect(screen.getByRole('dialog', { name: /profile & settings/i })).toBeInTheDocument();
  expect(screen.getByLabelText(/full name/i)).toHaveValue('FlowForge User');
  fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: 'Avery Builder' } });
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }));
  expect(await screen.findByText('Avery Builder')).toBeInTheDocument();
  expect(global.fetch).toHaveBeenCalledWith(expect.stringMatching(/\/auth\/me$/), expect.objectContaining({ method: 'PUT' }));
});

test('creates a new flowchart from the Flowcharts page', async () => {
  render(<App />);
  expect(await screen.findByText('Assistant ready')).toBeInTheDocument();
  await createFlowchartFromLibrary();
  expect(screen.queryByLabelText(/describe the process/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /^ai assistant$/i }));
  expect(screen.getByRole('button', { name: /generate workflow/i })).toBeDisabled();
  expect(screen.getByText(/structured, editable workflow/i)).toBeInTheDocument();
  expect(window.location.pathname).toBe('/editor');
});

test('opens and collapses the AI assistant from its toolbar symbol', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });
  await createFlowchartFromLibrary();

  const aiButton = screen.getByRole('button', { name: /^ai assistant$/i });
  expect(aiButton).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByLabelText(/describe the process/i)).not.toBeInTheDocument();

  fireEvent.click(aiButton);
  expect(aiButton).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getByLabelText(/describe the process/i)).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /close ai assistant/i }));
  expect(aiButton).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByLabelText(/describe the process/i)).not.toBeInTheDocument();
});

test('uses one editor toolbar for project details and project actions', async () => {
  window.history.replaceState({}, '', '/projects/project-1');
  render(<App />);
  await screen.findByText('Approval step');

  expect(screen.getByRole('button', { name: /^home$/i })).toBeInTheDocument();
  expect(within(screen.getByRole('navigation', { name: 'Primary navigation' })).getAllByRole('button')).toHaveLength(8);
  expect(within(screen.getByRole('navigation', { name: 'Primary navigation' })).getByRole('button', { name: 'Workflows' })).toHaveAttribute('aria-current', 'page');
  expect(screen.queryByRole('button', { name: /all workflows/i })).not.toBeInTheDocument();
  const toolbar = screen.getByRole('toolbar', { name: /workflow tools/i });
  expect(within(toolbar).getByRole('button', { name: /project details/i })).toBeInTheDocument();
  expect(within(toolbar).getByText('Assistant ready')).toBeInTheDocument();
  expect(within(toolbar).getByRole('button', { name: /collaborate/i })).toBeInTheDocument();
  expect(within(toolbar).getByRole('button', { name: /save project/i })).toBeInTheDocument();
  expect(within(toolbar).getByRole('button', { name: /export png/i })).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /project details/i })).toHaveLength(1);

  fireEvent.click(within(toolbar).getByRole('button', { name: /project details/i }));
  expect(screen.getByRole('dialog', { name: /project details/i })).toBeInTheDocument();
});

test('preserves the canvas and offers a reload when a save revision is stale', async () => {
  window.history.replaceState({}, '', '/projects/project-1');
  const baseFetch = global.fetch;
  global.fetch = jest.fn((url, options = {}) => {
    const query = url.endsWith('/graphql')
      ? JSON.parse(options.body || '{}').query || ''
      : '';
    if (query.includes('mutation UpdateProject')) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ errors: [{
          message: 'Reload before saving.',
          extensions: { code: 'CONFLICT', currentRevision: 4 },
        }] }),
      });
    }
    return baseFetch(url, options);
  });
  render(<App />);
  expect(await screen.findByText('Approval step')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /save project/i }));

  const conflict = await screen.findByRole('alert');
  expect(conflict).toHaveTextContent(/newer workflow changes are available/i);
  expect(screen.getByText('Approval step')).toBeInTheDocument();
  expect(within(conflict).getByRole('button', { name: /reload latest/i })).toBeInTheDocument();
});

test('admin can undo canvas changes and access clear canvas', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });
  await createFlowchartFromLibrary();

  const undoButton = screen.getByRole('button', { name: /undo last canvas change/i });
  expect(undoButton).toBeDisabled();
  expect(screen.getByRole('button', { name: /clear canvas/i })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /^＋ Add$/i }));
  fireEvent.click(screen.getByRole('button', { name: /add process step/i }));
  expect(screen.getByText('Process step')).toBeInTheDocument();
  expect(undoButton).toBeEnabled();

  fireEvent.click(undoButton);
  expect(screen.queryByText('Process step')).not.toBeInTheDocument();
  expect(screen.getByText(/your process will appear here/i)).toBeInTheDocument();
  expect(undoButton).toBeDisabled();
});

test('clear canvas requires confirmation and cancel preserves the diagram', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });
  await createFlowchartFromLibrary();
  fireEvent.click(screen.getByRole('button', { name: /^＋ Add$/i }));
  fireEvent.click(screen.getByRole('button', { name: /add process step/i }));

  fireEvent.click(screen.getByRole('button', { name: /^clear canvas$/i }));
  expect(screen.getByRole('alertdialog', { name: /clear this canvas/i })).toBeInTheDocument();
  expect(screen.getByText(/removes every step and connection/i)).toBeInTheDocument();
  expect(screen.getByText('Process step')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }));
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  expect(screen.getByText('Process step')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /^clear canvas$/i }));
  fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: /^clear canvas$/i }));
  expect(screen.queryByText('Process step')).not.toBeInTheDocument();
  expect(screen.getByText(/your process will appear here/i)).toBeInTheDocument();
});

test('adds a BPMN object and supports precise node sizing', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });
  await createFlowchartFromLibrary();

  fireEvent.click(screen.getByRole('button', { name: /^＋ Add$/i }));
  fireEvent.click(screen.getByRole('button', { name: /add timer event/i }));

  expect(screen.getByText('Timer event')).toBeInTheDocument();
  expect(screen.getByLabelText('Node width')).toHaveValue(104);
  expect(screen.getByLabelText('Node height')).toHaveValue(104);

  fireEvent.focus(screen.getByLabelText('Node width'));
  fireEvent.change(screen.getByLabelText('Node width'), { target: { value: '' } });
  expect(screen.getByLabelText('Node width')).toHaveValue(null);
  fireEvent.change(screen.getByLabelText('Node width'), { target: { value: '180' } });
  expect(screen.getByLabelText('Node width')).toHaveValue(180);
});

test('saves a dark appearance preference from account settings', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });
  fireEvent.click(screen.getByRole('button', { name: /open account menu/i }));
  fireEvent.click(screen.getByRole('button', { name: /settings.*notifications and workspace/i }));

  fireEvent.click(screen.getByRole('button', { name: /dark/i }));
  fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

  await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'));
  expect(localStorage.getItem('flowforge:theme')).toBe('dark');
});

test('admin can create a pending contact from entity settings', async () => {
  render(<App />);
  await screen.findByRole('heading', { name: /good .*flowforge/i });
  fireEvent.click(screen.getByRole('button', { name: /open account menu/i }));
  fireEvent.click(screen.getByRole('button', { name: /settings.*notifications and workspace/i }));
  fireEvent.click(screen.getByRole('button', { name: /entity & contacts/i }));

  expect(await screen.findByText(/active contacts/i)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/^full name$/i), { target: { value: 'Taylor Morgan' } });
  fireEvent.change(screen.getByLabelText(/^email address$/i), { target: { value: 'taylor@example.com' } });
  fireEvent.change(screen.getByLabelText(/job title/i), { target: { value: 'Operations' } });
  fireEvent.click(screen.getByRole('button', { name: /create contact & send invite/i }));

  expect(await screen.findByText(/invitation created for taylor@example.com/i)).toBeInTheDocument();
  expect(screen.getByText(/account setup link/i)).toBeInTheDocument();
});

test('basic users can view but cannot create flowcharts', async () => {
  mockUser = { ...mockUser, role: 'basic', display_name: 'Basic Viewer' };
  render(<App />);

  expect(await screen.findByRole('heading', { name: /good .*basic/i })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^create workflow$/i })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /^workflows$/i }));
  expect(await screen.findByText(/an entity admin can create/i)).toBeInTheDocument();
});

test('basic users never see undo or clear canvas controls', async () => {
  window.history.replaceState({}, '', '/projects/project-1');
  mockUser = { ...mockUser, role: 'basic', display_name: 'Basic Viewer' };
  render(<App />);

  expect(await screen.findByText('Approval step')).toBeInTheDocument();
  expect(screen.getByText('View only')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^ai assistant$/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /undo last canvas change/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /clear canvas/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^＋ Add$/i })).not.toBeInTheDocument();
});
