import { fireEvent, render, screen } from '@testing-library/react';
import { CollaborationPanel, PresenceStack } from './CollaborationControls';

const users = [
  { id: 'user-1', display_name: 'Avery Admin', role: 'admin', color: '#6D5CE8' },
  { id: 'user-2', display_name: 'Taylor Viewer', role: 'basic', color: '#258A71' },
];

test('shows active flowchart collaborators with profile avatars', () => {
  render(<PresenceStack users={users} status="connected" />);

  expect(screen.getByLabelText(/2 active on this workflow/i)).toBeInTheDocument();
  expect(screen.getByTitle(/Avery Admin · admin/i)).toHaveTextContent('AA');
  expect(screen.getByTitle(/Taylor Viewer · basic/i)).toHaveTextContent('TV');
  expect(screen.getByText('Live')).toBeInTheDocument();
});

test('creates an assigned flowchart task', () => {
  const onCreateTask = jest.fn();
  const contacts = [{ user: {
    id: 'user-2', display_name: 'Taylor Viewer', role: 'basic', handle: 'taylor-viewer', color: '#258A71',
  } }];
  const deliverables = [{ id: 'deliverable-1', title: 'Policy ready', status: 'planned' }];
  const nodes = [{ id: 'approval', data: { label: 'Approve request' } }];
  render(<CollaborationPanel open onClose={jest.fn()} currentUserId="user-1" currentUser={users[0]}
    connected canManage contacts={contacts} deliverables={deliverables} nodes={nodes} onCreateTask={onCreateTask} />);

  fireEvent.change(screen.getByLabelText(/task title/i), { target: { value: 'Review approval branch' } });
  fireEvent.change(screen.getByLabelText(/task details/i), { target: { value: 'Confirm the escalation path.' } });
  fireEvent.click(screen.getByRole('combobox', { name: /task assignee/i }));
  fireEvent.change(screen.getByRole('searchbox', { name: /search task assignee/i }), {
    target: { value: 'taylor' },
  });
  fireEvent.click(screen.getByRole('option', { name: /Taylor Viewer/i }));
  fireEvent.change(screen.getByLabelText(/task priority/i), { target: { value: 'high' } });
  fireEvent.change(screen.getByLabelText(/task due date/i), { target: { value: '2026-09-01' } });
  fireEvent.change(screen.getByLabelText(/task deliverable/i), { target: { value: 'deliverable-1' } });
  fireEvent.change(screen.getByLabelText(/task workflow step/i), { target: { value: 'approval' } });
  fireEvent.click(screen.getByRole('button', { name: /add task/i }));

  expect(onCreateTask).toHaveBeenCalledWith({
    title: 'Review approval branch',
    details: 'Confirm the escalation path.',
    assignee_id: 'user-2',
    priority: 'high',
    due_date: '2026-09-01',
    deliverable_id: 'deliverable-1',
    node_id: 'approval',
  });
  expect(screen.getByLabelText(/task title/i)).toHaveValue('');
});

test('adds a flowchart note with a contact mention and selected step', () => {
  const onSendNote = jest.fn();
  const contacts = [{ user: {
    id: 'user-2', display_name: 'Taylor Viewer', role: 'basic', handle: 'taylor-viewer', color: '#258A71',
  } }];
  const nodes = [{ id: 'approval', data: { label: 'Approve request' } }];
  render(<CollaborationPanel open onClose={jest.fn()} currentUserId="user-1" currentUser={users[0]}
    connected canManage contacts={contacts} nodes={nodes} selectedNodeId="approval"
    onSendNote={onSendNote} />);

  fireEvent.click(screen.getByRole('button', { name: /notes/i }));
  fireEvent.change(screen.getByLabelText(/add a workflow note/i), { target: { value: 'Please check this @tay' } });
  fireEvent.click(screen.getByRole('option', { name: /Taylor Viewer/i }));
  fireEvent.click(screen.getByRole('button', { name: /add note/i }));

  expect(onSendNote).toHaveBeenCalledWith(
    'Please check this @taylor-viewer',
    ['user-2'],
    'approval'
  );
});

test('keeps basic-user collaboration panels read-only', () => {
  const task = {
    id: 'task-1', title: 'Review draft', status: 'todo', priority: 'medium', creator: users[0],
  };
  const deliverable = {
    id: 'deliverable-1', title: 'Policy ready', status: 'planned', creator: users[0],
  };
  const note = {
    id: 'note-1', body: 'Check this branch', resolved: false,
    created_at: '2026-08-26T12:00:00Z', author: users[1],
  };
  render(<CollaborationPanel open onClose={jest.fn()} currentUserId="user-2" currentUser={users[1]}
    connected tasks={[task]} deliverables={[deliverable]} notes={[note]} />);

  expect(screen.getByLabelText(/status for review draft/i)).toBeDisabled();
  expect(screen.queryByLabelText(/task title/i)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /plan/i }));
  expect(screen.getByLabelText(/status for deliverable policy ready/i)).toBeDisabled();
  expect(screen.queryByLabelText(/deliverable title/i)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: /notes/i }));
  expect(screen.queryByLabelText(/add a workflow note/i)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /resolve/i })).not.toBeInTheDocument();
});
