import { websocketBaseUrl } from './apiClient';

export class CollaborationClient {
  constructor(projectId, handlers = {}) {
    this.projectId = projectId;
    this.handlers = handlers;
    this.socket = null;
    this.closed = false;
    this.retryCount = 0;
    this.retryTimer = null;
    this.documentRevision = null;
    this.documentInFlight = false;
    this.queuedDocument = null;
    this.documentDrainWaiters = [];
  }

  connect() {
    if (this.closed) return;
    this.handlers.onStatus?.('connecting');
    const socket = new WebSocket(
      `${websocketBaseUrl()}/api/v1/collaboration/projects/${encodeURIComponent(this.projectId)}`
    );
    this.socket = socket;
    socket.addEventListener('open', () => {
      this.retryCount = 0;
      this.handlers.onStatus?.('connected');
    });
    socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (Number.isInteger(payload.revision)) this.documentRevision = payload.revision;
        if (payload.type === 'ack') {
          this.documentInFlight = false;
          const queuedDocument = this.queuedDocument;
          this.queuedDocument = null;
          if (queuedDocument) this.sendDocument(queuedDocument, this.documentRevision);
          else this.resolveDocumentDrains();
        }
        if (payload.type === 'error' && ['CONFLICT', 'BAD_DOCUMENT'].includes(payload.code)) {
          this.documentInFlight = false;
          this.queuedDocument = null;
          this.rejectDocumentDrains(payload);
        }
        this.handlers.onEvent?.(payload);
      } catch {
        this.handlers.onError?.('A collaboration update could not be read.');
      }
    });
    socket.addEventListener('close', (event) => {
      if (this.socket === socket) this.socket = null;
      this.documentInFlight = false;
      this.queuedDocument = null;
      this.rejectDocumentDrains({
        code: 'collaboration_interrupted',
        message: 'Live document synchronization disconnected before saving.',
      });
      if (this.closed) return;
      if (event.code === 4401 || event.code === 4404) {
        this.handlers.onStatus?.('unavailable');
        return;
      }
      this.handlers.onStatus?.('reconnecting');
      const delay = Math.min(8_000, 500 * (2 ** this.retryCount));
      this.retryCount += 1;
      this.retryTimer = window.setTimeout(() => this.connect(), delay);
    });
    socket.addEventListener('error', () => this.handlers.onStatus?.('reconnecting'));
  }

  send(payload) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(payload));
    return true;
  }

  sendCursor(x, y) {
    return this.send({ type: 'cursor', x, y });
  }

  sendDocument(document, expectedRevision) {
    if (this.documentInFlight) {
      this.queuedDocument = document;
      return true;
    }
    const revision = Number.isInteger(this.documentRevision)
      ? this.documentRevision
      : expectedRevision;
    const sent = this.send({ type: 'document', document, expected_revision: revision });
    if (sent) this.documentInFlight = true;
    return sent;
  }

  getDocumentRevision(fallback = 0) {
    return Number.isInteger(this.documentRevision) ? this.documentRevision : fallback;
  }

  setDocumentRevision(revision) {
    if (Number.isInteger(revision)) this.documentRevision = revision;
  }

  flushDocumentWrites() {
    if (!this.documentInFlight && !this.queuedDocument) {
      return Promise.resolve(this.getDocumentRevision());
    }
    return new Promise((resolve, reject) => {
      this.documentDrainWaiters.push({ resolve, reject });
    });
  }

  resolveDocumentDrains() {
    if (this.documentInFlight || this.queuedDocument) return;
    const waiters = this.documentDrainWaiters;
    this.documentDrainWaiters = [];
    waiters.forEach(({ resolve }) => resolve(this.getDocumentRevision()));
  }

  rejectDocumentDrains(payload = {}) {
    const error = new Error(payload.message || 'Live document synchronization was interrupted.');
    error.code = payload.code || 'collaboration_interrupted';
    error.details = { currentRevision: payload.current_revision };
    const waiters = this.documentDrainWaiters;
    this.documentDrainWaiters = [];
    waiters.forEach(({ reject }) => reject(error));
  }

  sendNote(body, mentionedUserIds = [], nodeId = null) {
    return this.send({
      type: 'note',
      body,
      mentioned_user_ids: mentionedUserIds,
      node_id: nodeId,
    });
  }

  resolveNote(noteId, resolved = true) {
    return this.send({ type: 'note_resolve', note_id: noteId, resolved });
  }

  createTask(task) {
    return this.send({ type: 'task_create', ...task });
  }

  updateTask(taskId, changes) {
    return this.send({
      type: 'task_update', task_id: taskId,
      ...(typeof changes === 'string' ? { status: changes } : changes),
    });
  }

  createDeliverable(deliverable) {
    return this.send({ type: 'deliverable_create', ...deliverable });
  }

  updateDeliverable(deliverableId, changes) {
    return this.send({
      type: 'deliverable_update', deliverable_id: deliverableId,
      ...(typeof changes === 'string' ? { status: changes } : changes),
    });
  }

  disconnect() {
    this.closed = true;
    this.documentInFlight = false;
    this.queuedDocument = null;
    this.rejectDocumentDrains();
    if (this.retryTimer) window.clearTimeout(this.retryTimer);
    this.socket?.close(1000, 'Leaving flowchart');
    this.socket = null;
  }
}
