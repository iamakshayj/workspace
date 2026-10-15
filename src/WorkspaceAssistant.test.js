import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import WorkspaceAssistant, { parseWorkspaceAction } from './WorkspaceAssistant';
import { askWorkspaceAssistant } from './assistantService';

jest.mock('./assistantService', () => ({ askWorkspaceAssistant: jest.fn() }));

const user = { id: 'user-1', display_name: 'Avery Morgan', role: 'admin' };

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  askWorkspaceAssistant.mockResolvedValue({ answer: 'Start with the highest-impact outcome.', mode: 'advisory', action_performed: false });
});

test('prepares a dated meeting with a named contact without requiring the model', async () => {
  const onNavigate = jest.fn();
  render(<WorkspaceAssistant active="admin" currentUser={user} onNavigate={onNavigate} />);
  fireEvent.click(screen.getByRole('button', { name: 'Workspace AI' }));
  fireEvent.change(screen.getByLabelText('Ask Workspace AI'), { target: { value: 'schedule a call with Jordan Lee tmrw at 8 am' } });
  fireEvent.keyDown(screen.getByLabelText('Ask Workspace AI'), { key: 'Enter' });

  await waitFor(() => expect(onNavigate).toHaveBeenCalled());
  const path = onNavigate.mock.calls[0][0];
  const params = new URLSearchParams(path.split('?')[1]);
  expect(path).toMatch(/^\/calendar\?/);
  expect(params.get('attendee')).toBe('Jordan Lee');
  expect(params.get('time')).toBe('08:00');
  expect(params.get('duration')).toBe('30');
  expect(params.get('title')).toBe('Call with Jordan Lee');
  expect(askWorkspaceAssistant).not.toHaveBeenCalled();
});

test('opens a story draft without requiring the model', async () => {
  const onNavigate = jest.fn();
  render(<WorkspaceAssistant active="home" currentUser={user} onNavigate={onNavigate} />);
  fireEvent.click(screen.getByRole('button', { name: 'Workspace AI' }));
  fireEvent.change(screen.getByLabelText('Ask Workspace AI'), { target: { value: 'create a new story for me' } });
  fireEvent.keyDown(screen.getByLabelText('Ask Workspace AI'), { key: 'Enter' });

  await waitFor(() => expect(onNavigate).toHaveBeenCalled());
  const path = onNavigate.mock.calls[0][0];
  const params = new URLSearchParams(path.split('?')[1]);
  expect(path).toMatch(/^\/work\?/);
  expect(params.get('create')).toBe('1');
  expect(params.get('source')).toBe('assistant');
  expect(params.get('item_type')).toBe('story');
  expect(askWorkspaceAssistant).not.toHaveBeenCalled();
});

test('opens the active sprint board without requiring the model', async () => {
  const onNavigate = jest.fn();
  render(<WorkspaceAssistant active="home" currentUser={user} onNavigate={onNavigate} />);
  fireEvent.click(screen.getByRole('button', { name: 'Workspace AI' }));
  fireEvent.change(screen.getByLabelText('Ask Workspace AI'), { target: { value: 'go to sprint board' } });
  fireEvent.keyDown(screen.getByLabelText('Ask Workspace AI'), { key: 'Enter' });

  await waitFor(() => expect(onNavigate).toHaveBeenCalledWith('/work?tab=board&scope=active'));
  expect(askWorkspaceAssistant).not.toHaveBeenCalled();
});

test('understands common page names and misspellings without the model', () => {
  expect(parseWorkspaceAction('go to calender')).toEqual(expect.objectContaining({ type: 'navigate', path: '/calendar' }));
  expect(parseWorkspaceAction('show me the backlog')).toEqual(expect.objectContaining({ type: 'navigate', path: '/work?tab=backlog' }));
  expect(parseWorkspaceAction('open documents')).toEqual(expect.objectContaining({ type: 'navigate', path: '/knowledge' }));
  expect(parseWorkspaceAction('take me to approvals')).toEqual(expect.objectContaining({ type: 'navigate', path: '/operations?tab=approvals' }));
  expect(parseWorkspaceAction('switch to compliance evidence')).toEqual(expect.objectContaining({ type: 'navigate', path: '/admin?tab=compliance' }));
});

test('opens supported creation forms without the model', () => {
  expect(parseWorkspaceAction('schedule a meeting')).toEqual(expect.objectContaining({ type: 'route_draft', path: '/calendar?create=1&source=assistant' }));
  expect(parseWorkspaceAction('create a new document')).toEqual(expect.objectContaining({ type: 'route_draft', path: '/knowledge?create=1&source=assistant' }));
  expect(parseWorkspaceAction('create a dashboard')).toEqual(expect.objectContaining({ type: 'route_draft', path: '/operations?tab=dashboards&create=dashboards' }));
  expect(parseWorkspaceAction('create an approval request')).toEqual(expect.objectContaining({ type: 'route_draft', path: '/operations?tab=approvals&create=approval-request' }));
});

test('opens global interface panels without the model', async () => {
  const listener = jest.fn();
  window.addEventListener('workspace:open-communication', listener);
  render(<WorkspaceAssistant active="home" currentUser={user} onNavigate={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Workspace AI' }));
  fireEvent.change(screen.getByLabelText('Ask Workspace AI'), { target: { value: 'open messages' } });
  fireEvent.keyDown(screen.getByLabelText('Ask Workspace AI'), { key: 'Enter' });

  await waitFor(() => expect(listener).toHaveBeenCalled());
  expect(listener.mock.calls[0][0].detail).toEqual({ panel: 'messages' });
  expect(askWorkspaceAssistant).not.toHaveBeenCalled();
  window.removeEventListener('workspace:open-communication', listener);
});

test('answers general questions with current page context and keeps useful shortcuts', async () => {
  const onNavigate = jest.fn();
  render(<WorkspaceAssistant active="work" currentUser={user} onNavigate={onNavigate} />);
  fireEvent.click(screen.getByRole('button', { name: 'Workspace AI' }));
  expect(screen.getByRole('dialog', { name: 'Workspace AI assistant' })).toBeInTheDocument();
  expect(screen.getByText('Ask anything · Work context')).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText('Ask Workspace AI'), { target: { value: 'What should I prioritize?' } });
  fireEvent.keyDown(screen.getByLabelText('Ask Workspace AI'), { key: 'Enter' });
  expect(await screen.findByText('Start with the highest-impact outcome.')).toBeInTheDocument();
  expect(screen.getByText(/Advisory · no changes made/)).toBeInTheDocument();
  expect(askWorkspaceAssistant).toHaveBeenCalledWith(
    [{ role: 'user', content: 'What should I prioritize?' }],
    expect.objectContaining({ page: 'work', title: 'Work' }),
  );

  fireEvent.click(screen.getByRole('button', { name: /Meeting/ }));
  expect(onNavigate).toHaveBeenCalledWith('/calendar?create=1&source=assistant');
});

test('clears a saved conversation', async () => {
  localStorage.setItem('workspace:assistant:user-1', JSON.stringify([{ id: '1', role: 'assistant', content: 'Saved answer' }]));
  render(<WorkspaceAssistant active="home" currentUser={user} onNavigate={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Workspace AI' }));
  expect(screen.getByText('Saved answer')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Clear AI conversation' }));
  await waitFor(() => expect(screen.queryByText('Saved answer')).not.toBeInTheDocument());
});
