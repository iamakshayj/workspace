import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import InviteAcceptScreen from './InviteAcceptScreen';

test('invited contact sets a password to activate the account', async () => {
  global.fetch = jest.fn(() => Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({
      display_name: 'Taylor Morgan', email: 'taylor@example.com', entity_name: 'Northwind Operations',
      role: 'basic', expires_at: '2026-09-02T00:00:00Z',
    }),
  }));
  const auth = { acceptInvite: jest.fn(() => Promise.resolve()) };
  render(<InviteAcceptScreen token="secure-invitation-token" auth={auth} />);

  expect(await screen.findByRole('heading', { name: /set up your account/i })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/create password/i), { target: { value: 'SecurePass123!' } });
  fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'SecurePass123!' } });
  fireEvent.click(screen.getByRole('button', { name: /create account & join/i }));

  await waitFor(() => expect(auth.acceptInvite).toHaveBeenCalledWith('secure-invitation-token', 'SecurePass123!'));
});
