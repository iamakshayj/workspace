import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import GuestPortal from './GuestPortal';

const payload = {
  guest: { name: 'Taylor Guest', email: 'taylor@example.com' }, permissions: ['view', 'comment', 'approve'],
  expires_at: '2026-10-22T12:00:00Z',
  resource: { id: 'ticket-1', type: 'ticket', title: 'Review incident', description: 'Please confirm the resolution.', status: 'resolved' },
  activity: [],
};

beforeEach(() => { global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => payload }); });
afterEach(() => { jest.restoreAllMocks(); });

test('lets an external guest view and comment without workspace authentication', async () => {
  render(<GuestPortal token="guest-token" />);
  expect(await screen.findByRole('heading', { name: 'Review incident' })).toBeInTheDocument();
  expect(screen.getByText('Taylor Guest')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Comment'), { target: { value: 'Confirmed, thank you.' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send comment' }));
  await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/guest/guest-token/actions'), expect.objectContaining({ method: 'POST' })));
});
