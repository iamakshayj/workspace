import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import AuthScreen from './AuthScreen';

test('signs into a provisioned account without public registration', async () => {
  const auth = { login: jest.fn(() => Promise.resolve()) };
  render(<AuthScreen auth={auth} />);

  expect(screen.queryByRole('button', { name: /create an account/i })).not.toBeInTheDocument();
  expect(screen.getByText(/contact your workspace administrator/i)).toBeInTheDocument();
  expect(screen.queryByText(/OpenAI|Argon2|HTTP-only|self-hosted|local-first/i)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: 'avery@example.com' } });
  fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'SecurePass123!' } });
  fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));

  await waitFor(() => expect(auth.login).toHaveBeenCalledWith('avery@example.com', 'SecurePass123!'));
});

test('continues through an MFA challenge when the account requires it', async () => {
  const challenge = Object.assign(new Error('Verification code required'), { status: 428 });
  const auth = { login: jest.fn().mockRejectedValueOnce(challenge).mockResolvedValueOnce() };
  render(<AuthScreen auth={auth} />);

  fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: 'owner@example.com' } });
  fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'SecurePass123!' } });
  fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));

  const verification = await screen.findByLabelText(/verification code/i);
  fireEvent.change(verification, { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: /verify and sign in/i }));

  await waitFor(() => expect(auth.login).toHaveBeenLastCalledWith(
    'owner@example.com', 'SecurePass123!', '123456',
  ));
});

test('offers the configured provider when password login requires SSO', async () => {
  const ssoRequired = Object.assign(new Error('Continue with Acme Identity.'), {
    status: 403,
    details: {
      code: 'sso_required',
      provider_id: 'provider-1',
      provider_name: 'Acme Identity',
      login_url: '/api/v1/auth/sso/provider-1/start',
    },
  });
  const auth = { login: jest.fn().mockRejectedValue(ssoRequired) };
  render(<AuthScreen auth={auth} />);

  fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: 'member@acme.example' } });
  fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'SecurePass123!' } });
  fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));

  expect(await screen.findByRole('button', { name: 'Continue with Acme Identity' })).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Continue with Acme Identity.');
});
