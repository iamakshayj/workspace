import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import VideoCallPanel from './VideoCallPanel';

const user = {
  id: 'user-1', display_name: 'Demo Admin', color: '#6D5CE8',
};
const call = {
  callId: 'call-1', title: 'Delivery sync', media: 'video', ring: false,
  context: { kind: 'calendar', id: 'event-1' },
};

test('keeps the app accessible with mini, collapsed, and expanded call-window modes', () => {
  const backgroundAction = jest.fn();
  const onClose = jest.fn();
  render(<main><button onClick={backgroundAction}>Open work board</button>
    <VideoCallPanel currentUser={user} call={call} onClose={onClose} />
  </main>);

  const panel = screen.getByRole('dialog', { name: 'Delivery sync call' });
  expect(panel).toHaveClass('mini');
  expect(panel).toHaveAttribute('aria-modal', 'false');
  expect(screen.getByRole('button', { name: 'Join now' })).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Open work board' }));
  expect(backgroundAction).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole('button', { name: 'Expand call window' }));
  expect(panel).toHaveClass('expanded');
  fireEvent.click(screen.getByRole('button', { name: 'Return call to mini window' }));
  expect(panel).toHaveClass('mini');

  fireEvent.click(screen.getByRole('button', { name: 'Collapse call window' }));
  expect(panel).toHaveClass('collapsed');
  expect(screen.queryByRole('button', { name: 'Join now' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Restore call window' }));
  expect(panel).toHaveClass('mini');

  fireEvent.click(screen.getByRole('button', { name: 'Close call panel' }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('offers camera and microphone selection before joining', async () => {
  const original = navigator.mediaDevices;
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
    enumerateDevices: jest.fn().mockResolvedValue([
      { kind: 'audioinput', deviceId: 'mic-1', label: 'Desk microphone' },
      { kind: 'videoinput', deviceId: 'camera-1', label: 'Front camera' },
    ]),
  } });
  render(<VideoCallPanel currentUser={user} call={call} onClose={jest.fn()} />);

  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Microphone' })).toHaveValue('mic-1'));
  expect(screen.getByRole('combobox', { name: 'Camera' })).toHaveValue('camera-1');
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: original });
});
