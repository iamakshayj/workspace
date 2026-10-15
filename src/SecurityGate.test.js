import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import SecurityGate from './SecurityGate';
import { confirmMfa, enrollMfa, stepUpMfa } from './authService';

jest.mock('./authService', () => ({
  confirmMfa: jest.fn(),
  enrollMfa: jest.fn(),
  stepUpMfa: jest.fn(),
}));

beforeEach(() => jest.clearAllMocks());

test('requires enrollment and recovery-code acknowledgement before entering the workspace', async () => {
  enrollMfa.mockResolvedValue({ secret: 'JBSWY3DPEHPK3PXP' });
  confirmMfa.mockResolvedValue({ recovery_codes: ['ABCDE-FGHIJ', 'KLMNP-QRSTU'] });
  const refresh = jest.fn().mockResolvedValue();
  render(<SecurityGate user={{ security_status: 'setup_required' }} onRefresh={refresh} onLogout={jest.fn()} />);

  fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: 'SecurePass123!' } });
  fireEvent.click(screen.getByRole('button', { name: /start setup/i }));
  expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText(/verification code/i), { target: { value: '123456' } });
  fireEvent.click(screen.getByRole('button', { name: /enable mfa/i }));
  expect(await screen.findByText('ABCDE-FGHIJ')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /i saved them/i }));

  await waitFor(() => expect(refresh).toHaveBeenCalled());
});

test('steps up an existing password-only session', async () => {
  stepUpMfa.mockResolvedValue({ security_status: 'compliant' });
  const refresh = jest.fn().mockResolvedValue();
  render(<SecurityGate user={{ security_status: 'verification_required' }} onRefresh={refresh} onLogout={jest.fn()} />);

  fireEvent.change(screen.getByLabelText(/authenticator or recovery code/i), { target: { value: '654321' } });
  fireEvent.click(screen.getByRole('button', { name: /verify and continue/i }));

  await waitFor(() => {
    expect(stepUpMfa).toHaveBeenCalledWith('654321');
    expect(refresh).toHaveBeenCalled();
  });
});
