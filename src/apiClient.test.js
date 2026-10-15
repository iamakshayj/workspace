import { notifyIfUnauthorized, websocketBaseUrl } from './apiClient';

test('converts HTTP API origins to matching WebSocket origins', () => {
  expect(websocketBaseUrl('http://127.0.0.1:8000')).toBe('ws://127.0.0.1:8000');
  expect(websocketBaseUrl('https://flowforge.example')).toBe('wss://flowforge.example');
});

test('notifies the app when an authenticated API request expires', () => {
  const listener = jest.fn();
  window.addEventListener('flowforge:unauthorized', listener, { once: true });

  notifyIfUnauthorized({ status: 401 });

  expect(listener).toHaveBeenCalledTimes(1);
});
