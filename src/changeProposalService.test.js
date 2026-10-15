import { applyChangeProposal, createChangeProposal, getChangeProposals } from './changeProposalService';

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [] }) });
});

afterEach(() => jest.restoreAllMocks());

test('uses cookie-authenticated governed change endpoints', async () => {
  await getChangeProposals('pending');
  expect(global.fetch).toHaveBeenLastCalledWith(
    expect.stringMatching(/\/api\/v1\/change-proposals\?status=pending$/),
    expect.objectContaining({ credentials: 'include' }),
  );
  await createChangeProposal({ title: 'A proposal' });
  expect(global.fetch).toHaveBeenLastCalledWith(
    expect.stringMatching(/\/api\/v1\/change-proposals$/),
    expect.objectContaining({ method: 'POST', body: JSON.stringify({ title: 'A proposal' }) }),
  );
  await applyChangeProposal('proposal-1');
  expect(global.fetch).toHaveBeenLastCalledWith(
    expect.stringMatching(/\/api\/v1\/change-proposals\/proposal-1\/apply$/),
    expect.objectContaining({ method: 'POST' }),
  );
});
