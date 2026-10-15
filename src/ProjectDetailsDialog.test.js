import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ProjectDetailsDialog from './ProjectDetailsDialog';

const currentUser = {
  id: 'user-1', display_name: 'Avery Admin', email: 'avery@example.com', role: 'admin',
};
const contacts = [{ user: {
  id: 'user-2', display_name: 'Taylor Viewer', email: 'taylor@example.com', role: 'basic', color: '#258A71',
} }];

test('saves project description, status, owner, and collaborators', async () => {
  const onSave = jest.fn(() => Promise.resolve());
  render(<ProjectDetailsDialog open onClose={jest.fn()} onSave={onSave} canManage
    currentUser={currentUser} contacts={contacts} ownerId="user-1"
    collaboratorIds={['user-1']} persisted />);

  fireEvent.change(screen.getByLabelText(/project description/i), {
    target: { value: 'Documents customer approval and escalation ownership.' },
  });
  fireEvent.change(screen.getByLabelText(/project status/i), { target: { value: 'draft' } });
  fireEvent.click(screen.getByRole('combobox', { name: /project collaborators/i }));
  fireEvent.change(screen.getByRole('searchbox', { name: /search project collaborators/i }), {
    target: { value: 'taylor@example.com' },
  });
  fireEvent.click(screen.getByRole('option', { name: /Taylor Viewer/i }));
  fireEvent.click(screen.getByRole('button', { name: /save details/i }));

  await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    description: 'Documents customer approval and escalation ownership.',
    status: 'draft',
    owner_id: 'user-1',
    collaborator_ids: ['user-1', 'user-2'],
  })));
});

test('saves enterprise planning metadata with normalized values', async () => {
  const onSave = jest.fn(() => Promise.resolve());
  render(<ProjectDetailsDialog open onClose={jest.fn()} onSave={onSave} canManage
    currentUser={currentUser} contacts={contacts} ownerId="user-1"
    collaboratorIds={['user-1']} persisted />);

  fireEvent.click(screen.getByRole('button', { name: 'Planning' }));
  fireEvent.change(screen.getByLabelText(/project key/i), { target: { value: 'ops 2026' } });
  fireEvent.change(screen.getByLabelText('Health'), { target: { value: 'at_risk' } });
  fireEvent.change(screen.getByLabelText('Progress'), { target: { value: '45' } });
  fireEvent.change(screen.getByLabelText(/project tags/i), { target: { value: 'automation, customer' } });
  fireEvent.click(screen.getByRole('button', { name: /save planning/i }));

  await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    profile: expect.objectContaining({
      key: 'OPS2026', health: 'at_risk', progress: 45, tags: ['automation', 'customer'],
    }),
  })));
});

test('keeps the selected owner in the collaborator team', () => {
  render(<ProjectDetailsDialog open onClose={jest.fn()} onSave={jest.fn()} canManage
    currentUser={currentUser} contacts={contacts} ownerId="user-1" collaboratorIds={['user-1']} />);

  fireEvent.click(screen.getByRole('combobox', { name: /project owner/i }));
  fireEvent.click(screen.getByRole('option', { name: /Taylor Viewer/i }));
  fireEvent.click(screen.getByRole('combobox', { name: /project collaborators/i }));

  expect(screen.getByRole('option', { name: /Taylor Viewer/i })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('option', { name: /Taylor Viewer/i })).toHaveAttribute('aria-disabled', 'true');
});
