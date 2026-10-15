import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import KnowledgeManagement from './KnowledgeManagement';
import { getCommunicationOverview } from './communicationService';
import { getKnowledgeDocument, getKnowledgeOverview, updateKnowledgeDocument } from './knowledgeService';

jest.mock('./AccountControls', () => () => <div>Account</div>);
jest.mock('./communicationService', () => ({
  getCommunicationOverview: jest.fn().mockResolvedValue({ contacts: [] }),
}));
jest.mock('./knowledgeService', () => ({
  getKnowledgeOverview: jest.fn(), getKnowledgeDocument: jest.fn(), updateKnowledgeDocument: jest.fn(),
  createKnowledgeSpace: jest.fn(), createKnowledgeDocument: jest.fn(), updateKnowledgeAccess: jest.fn(),
  addKnowledgeComment: jest.fn(), resolveKnowledgeComment: jest.fn(), restoreKnowledgeRevision: jest.fn(),
  duplicateKnowledgeDocument: jest.fn(), followKnowledgeDocument: jest.fn(), getKnowledgeRevision: jest.fn(),
  updateKnowledgeSpace: jest.fn(),
}));

const user = { id: 'user-1', display_name: 'Demo Admin', email: 'admin@example.com', role: 'admin', handle: 'admin-user' };
const summary = {
  id: 'doc-1', space_id: 'space-1', space_name: 'Operations', title: 'Incident policy', summary: 'How incidents run',
  status: 'draft', visibility: 'workspace', classification: 'internal', template: 'policy', revision: 1,
  owner: user, updated_at: '2026-09-03T10:00:00Z', review_due_at: null, expires_at: null,
  parent_id: null, position: 1024, icon: '📘', labels: ['policy'],
};
const detail = {
  ...summary, body: '# Response\n\nEscalate quickly.', current_user_access: 'admin', can_edit: true,
  can_comment: true, can_manage: true, access: [], comments: [],
  following: true, watchers: [user],
  revisions: [{ id: 'rev-1', version: 1, change_summary: 'Document created', created_at: summary.updated_at, created_by: user }],
  outbound_links: [], backlinks: [],
};

beforeEach(() => {
  window.history.replaceState({}, '', '/knowledge');
  localStorage.removeItem('workspace:knowledge:favorites');
  getKnowledgeOverview.mockResolvedValue({
    spaces: [{ id: 'space-1', name: 'Operations', visibility: 'workspace', document_count: 1, current_user_access: 'admin' }],
    documents: [summary], templates: [{ id: 'blank', name: 'Blank page', description: '', body: '' }],
    counts: { documents: 1, needs_review: 0, expired: 0 },
  });
  getKnowledgeDocument.mockResolvedValue(detail);
  updateKnowledgeDocument.mockResolvedValue({ ...detail, title: 'Updated policy', revision: 2 });
  getCommunicationOverview.mockResolvedValue({ contacts: [] });
});

test('opens, previews, and version-saves a governed document', async () => {
  render(<KnowledgeManagement user={user} onNavigate={jest.fn()} />);
  expect(await screen.findByRole('heading', { name: 'Knowledge home' })).toBeInTheDocument();
  expect(await screen.findByRole('heading', { name: 'Start with a template' })).toBeInTheDocument();
  fireEvent.click(await screen.findByRole('button', { name: /incident policy/i }));
  expect(await screen.findByRole('button', { name: 'Edit' })).toBeInTheDocument();
  expect(screen.getByText('Escalate quickly.')).toBeInTheDocument();
  expect(screen.getByRole('navigation', { name: 'On this page' })).toHaveTextContent('Response');
  fireEvent.click(screen.getByRole('button', { name: 'Add to favorites' }));
  expect(screen.getByRole('button', { name: 'Remove from favorites' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
  fireEvent.change(screen.getByLabelText('Document title'), { target: { value: 'Updated policy' } });
  fireEvent.click(screen.getByTitle('Information panel'));
  fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
  expect(screen.getByText('Helpful context')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(updateKnowledgeDocument).toHaveBeenCalledWith('doc-1', expect.objectContaining({
    expected_revision: 1, title: 'Updated policy', labels: ['policy'], icon: '📘', parent_id: null,
  })));
});

test('renders child pages in the selected space tree', async () => {
  const child = { ...summary, id: 'doc-2', title: 'Escalation checklist', parent_id: 'doc-1', position: 1024 };
  getKnowledgeOverview.mockResolvedValueOnce({
    spaces: [{ id: 'space-1', name: 'Operations', visibility: 'workspace', document_count: 2, current_user_access: 'admin' }],
    documents: [summary, child], templates: [],
    counts: { documents: 2, needs_review: 0, expired: 0, drafts: 2, published: 0 },
  });
  render(<KnowledgeManagement user={user} onNavigate={jest.fn()} />);
  await screen.findByRole('heading', { name: 'Knowledge home' });
  const spaceButton = screen.getAllByRole('button').find((item) => item.textContent.includes('Operations') && !item.textContent.includes('Incident'));
  fireEvent.click(spaceButton);
  expect(await screen.findByRole('button', { name: /Escalation checklist/ })).toBeInTheDocument();
});
