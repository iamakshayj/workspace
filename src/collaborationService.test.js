import { CollaborationClient } from './collaborationService';

class MockWebSocket {
  static OPEN = 1;

  constructor() {
    this.readyState = MockWebSocket.OPEN;
    this.listeners = {};
    this.send = jest.fn();
    this.close = jest.fn();
    MockWebSocket.instance = this;
  }

  addEventListener(type, listener) {
    this.listeners[type] = listener;
  }

  emit(type, payload = {}) {
    this.listeners[type]?.(payload);
  }
}

beforeEach(() => {
  global.WebSocket = MockWebSocket;
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('serializes document writes and advances the expected revision after an acknowledgement', async () => {
  const client = new CollaborationClient('project-1');
  client.connect();
  const socket = MockWebSocket.instance;
  socket.emit('message', { data: JSON.stringify({ type: 'snapshot', revision: 4 }) });

  expect(client.sendDocument({ title: 'First' }, 4)).toBe(true);
  expect(client.sendDocument({ title: 'Latest' }, 4)).toBe(true);
  expect(socket.send).toHaveBeenCalledTimes(1);
  expect(JSON.parse(socket.send.mock.calls[0][0])).toEqual(expect.objectContaining({
    expected_revision: 4,
    document: { title: 'First' },
  }));

  const drained = client.flushDocumentWrites();
  socket.emit('message', { data: JSON.stringify({ type: 'ack', revision: 5 }) });

  expect(socket.send).toHaveBeenCalledTimes(2);
  expect(JSON.parse(socket.send.mock.calls[1][0])).toEqual(expect.objectContaining({
    expected_revision: 5,
    document: { title: 'Latest' },
  }));
  socket.emit('message', { data: JSON.stringify({ type: 'ack', revision: 6 }) });
  await expect(drained).resolves.toBe(6);
});

test('drops queued writes when the server reports a revision conflict', async () => {
  const onEvent = jest.fn();
  const client = new CollaborationClient('project-1', { onEvent });
  client.connect();
  const socket = MockWebSocket.instance;
  socket.emit('message', { data: JSON.stringify({ type: 'snapshot', revision: 7 }) });
  client.sendDocument({ title: 'First' }, 7);
  client.sendDocument({ title: 'Queued' }, 7);
  const drained = client.flushDocumentWrites();

  socket.emit('message', {
    data: JSON.stringify({ type: 'error', code: 'CONFLICT', current_revision: 8 }),
  });

  expect(client.documentInFlight).toBe(false);
  expect(client.queuedDocument).toBeNull();
  expect(socket.send).toHaveBeenCalledTimes(1);
  expect(onEvent).toHaveBeenLastCalledWith(expect.objectContaining({ code: 'CONFLICT' }));
  await expect(drained).rejects.toEqual(expect.objectContaining({
    code: 'CONFLICT', details: { currentRevision: 8 },
  }));
});
