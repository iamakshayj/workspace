import { fireEvent, render, screen } from '@testing-library/react';
import ProjectPlan from './ProjectPlan';

const currentUser = {
  id: 'user-1', display_name: 'Avery Admin', role: 'admin', color: '#6D5CE8',
};
const contacts = [{ user: {
  id: 'user-2', display_name: 'Taylor Viewer', role: 'basic', color: '#258A71',
} }];
const nodes = [{ id: 'approval', data: { label: 'Approve request' } }];

test('creates an owned deliverable linked to a flowchart step', () => {
  const onCreateDeliverable = jest.fn();
  render(<ProjectPlan currentUser={currentUser} currentUserId="user-1" contacts={contacts}
    nodes={nodes} connected canManage onCreateDeliverable={onCreateDeliverable} />);

  fireEvent.change(screen.getByLabelText(/deliverable title/i), { target: { value: 'Policy ready' } });
  fireEvent.change(screen.getByLabelText(/deliverable description/i), { target: { value: 'Approved and published.' } });
  fireEvent.click(screen.getByRole('combobox', { name: /deliverable owner/i }));
  fireEvent.change(screen.getByRole('searchbox', { name: /search deliverable owner/i }), {
    target: { value: 'taylor' },
  });
  fireEvent.click(screen.getByRole('option', { name: /Taylor Viewer/i }));
  fireEvent.change(screen.getByLabelText(/deliverable target date/i), { target: { value: '2026-09-15' } });
  fireEvent.change(screen.getByLabelText(/deliverable workflow step/i), { target: { value: 'approval' } });
  fireEvent.click(screen.getByRole('button', { name: /add deliverable/i }));

  expect(onCreateDeliverable).toHaveBeenCalledWith({
    title: 'Policy ready',
    description: 'Approved and published.',
    owner_id: 'user-2',
    target_date: '2026-09-15',
    node_id: 'approval',
  });
  expect(screen.getByLabelText(/deliverable title/i)).toHaveValue('');
});

test('rolls linked task completion into the plan and updates deliverable status', () => {
  const onUpdateDeliverable = jest.fn();
  const deliverables = [{
    id: 'deliverable-1', title: 'Policy ready', description: 'Publish the policy.', status: 'in_progress',
    target_date: '2026-09-15', node_id: 'approval', owner: contacts[0].user,
  }];
  const tasks = [
    { id: 'task-1', title: 'Review draft', status: 'done', deliverable_id: 'deliverable-1', due_date: '2026-09-14' },
    { id: 'task-2', title: 'Publish draft', status: 'todo', deliverable_id: 'deliverable-1', due_date: '2026-09-15' },
  ];
  render(<ProjectPlan currentUser={currentUser} currentUserId="user-1" contacts={contacts}
    nodes={nodes} deliverables={deliverables} tasks={tasks} connected canManage
    onUpdateDeliverable={onUpdateDeliverable} />);

  expect(screen.getByLabelText('50% plan progress')).toBeInTheDocument();
  expect(screen.getAllByText('50%')).toHaveLength(2);
  expect(screen.getByText('2 tasks')).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText(/status for deliverable policy ready/i), { target: { value: 'done' } });
  expect(onUpdateDeliverable).toHaveBeenCalledWith('deliverable-1', 'done');
});
