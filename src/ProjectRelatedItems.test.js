import { fireEvent, render, screen } from '@testing-library/react';
import ProjectDetailsDialog from './ProjectDetailsDialog';
import { getObjectHistory, getRelatedItems } from './workGraphService';
import { getProjectGovernance } from './flowchartService';

jest.mock('./workGraphService');
jest.mock('./flowchartService', () => ({
  getProjectGovernance: jest.fn().mockResolvedValue({
    visibility: 'restricted', current_user_access: 'admin', approval_status: 'draft',
    current_revision: 1, access_entries: [], revisions: [], audit_events: [], approval: null,
  }),
  decideProjectApproval: jest.fn(), requestProjectApproval: jest.fn(),
  restoreProjectRevision: jest.fn(), updateProjectGovernance: jest.fn(),
}));

test('shows the permission-filtered graph directly from project details', async () => {
  getProjectGovernance.mockResolvedValue({
    visibility: 'restricted', current_user_access: 'admin', approval_status: 'draft',
    current_revision: 1, access_entries: [], revisions: [], audit_events: [], approval: null,
  });
  getRelatedItems.mockResolvedValue({
    nodes: [{ id: 'doc-1', type: 'document', title: 'Launch plan', status: 'published', depth: 1, url: '/knowledge?document=doc-1' }],
    edges: [{ id: 'edge-1' }], truncated: false,
  });
  getObjectHistory.mockResolvedValue({ events: [{ id: 'history-1', action: 'relationship.created', created_at: '2026-09-03T12:00:00Z' }] });
  const user = { id: 'user-1', display_name: 'Admin User', email: 'admin@example.com', role: 'admin' };
  render(<ProjectDetailsDialog open persisted projectId="project-1" canManage currentUser={user}
    ownerId={user.id} collaboratorIds={[user.id]} onClose={jest.fn()} onSave={jest.fn()} />);

  fireEvent.click(screen.getByRole('button', { name: 'Related items' }));
  expect(await screen.findByText('Launch plan')).toBeInTheDocument();
  expect(screen.getByText('relationship created')).toBeInTheDocument();
  expect(getRelatedItems).toHaveBeenCalledWith('project', 'project-1', expect.objectContaining({ depth: 1, direction: 'both' }));
});
