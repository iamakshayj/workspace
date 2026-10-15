import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import ChangeProposalPanel from './ChangeProposalPanel';
import * as service from './changeProposalService';

jest.mock('./changeProposalService');

const proposal = {
  id: 'proposal-1', title: 'Connect delivery work', rationale: 'Verified delivery scope', status: 'pending',
  updated_at: '2026-09-13T12:00:00Z', created_by: { id: 'user-1', display_name: 'Avery Morgan' },
  reviewed_by: null, evidence: [], can_review: true, can_apply: false, can_rollback: false,
  preview: { changes: [{ action: 'create', relationship_type: 'supports', source: { title: 'Launch' }, target: { title: 'REL-4' } }] },
};

beforeEach(() => {
  service.getChangeProposals.mockResolvedValue({ items: [proposal] });
  service.createChangeProposal.mockResolvedValue(proposal);
  service.decideChangeProposal.mockResolvedValue({ ...proposal, status: 'approved' });
});

afterEach(() => jest.resetAllMocks());

test('previews reviewed changes and submits without mutating the graph', async () => {
  render(<ChangeProposalPanel projects={[{ id: 'project-1', title: 'Launch' }]} workItems={[{ id: 'work-17', key: 'REL-17', summary: 'Rollout evidence' }]} />);
  expect(await screen.findByText('Connect delivery work')).toBeInTheDocument();
  expect(screen.getByText('supports')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '+ Propose change' }));
  fireEvent.change(screen.getByLabelText('Proposal title'), { target: { value: 'Attach rollout evidence' } });
  fireEvent.change(screen.getByLabelText('Target type'), { target: { value: 'work_item' } });
  fireEvent.change(screen.getByLabelText('Target'), { target: { value: 'work-17' } });
  expect(screen.getByText(/does not modify the graph/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Submit for review' }));
  await waitFor(() => expect(service.createChangeProposal).toHaveBeenCalledWith(expect.objectContaining({
    title: 'Attach rollout evidence',
    operations: [expect.objectContaining({ action: 'create', source_id: 'project-1', target_id: 'work-17' })],
  })));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
  expect(screen.getByRole('heading', { name: 'Approve this proposal?' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Approve this proposal' }));
  await waitFor(() => expect(service.decideChangeProposal).toHaveBeenCalledWith('proposal-1', 'approved'));
});
