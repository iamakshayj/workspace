import { API_BASE_URL, notifyIfUnauthorized, websocketBaseUrl } from './apiClient';

export class CommunicationApiError extends Error {
  constructor(message, code = 'request_failed') {
    super(message);
    this.name = 'CommunicationApiError';
    this.code = code;
  }
}

export async function graphqlRequest(query, variables = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/graphql`, {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, variables }),
    });
  } catch {
    throw new CommunicationApiError('The communication service is unavailable.', 'backend_unavailable');
  }
  const payload = await response.json().catch(() => ({}));
  notifyIfUnauthorized(response);
  if (!response.ok || payload.errors?.length) {
    const error = payload.errors?.[0];
    throw new CommunicationApiError(
      error?.message || payload.detail || 'The communication request failed.',
      error?.extensions?.code || 'graphql_error'
    );
  }
  return payload.data;
}

const USER_FIELDS = `
  id display_name: displayName email role handle color
`;

const MESSAGE_FIELDS = `
  id body read created_at: createdAt parent_id: parentId pinned bookmarked can_edit: canEdit
  edited_at: editedAt deleted_at: deletedAt
  reactions { emoji count reacted_by_me: reactedByMe }
  attachments { name url }
  sender { ${USER_FIELDS} }
  recipient { ${USER_FIELDS} }
`;

const NOTIFICATION_FIELDS = `
  id kind title body project_id: projectId contact_id: contactId calendar_event_id: calendarEventId work_item_id: workItemId
  communication_channel_id: communicationChannelId communication_message_id: communicationMessageId
  document_id: documentId
  group_key: groupKey snoozed_until: snoozedUntil
  read created_at: createdAt
  actor { ${USER_FIELDS} }
`;

const CHANNEL_FIELDS = `
  id name description channel_type: channelType visibility
  unread_count: unreadCount latest_message: latestMessage latest_message_at: latestMessageAt
  member_count: memberCount created_by_id: createdById can_manage: canManage
  members { ${USER_FIELDS} }
`;

const CHANNEL_MESSAGE_FIELDS = `
  id channel_id: channelId body created_at: createdAt parent_id: parentId pinned bookmarked can_edit: canEdit
  edited_at: editedAt deleted_at: deletedAt
  reactions { emoji count reacted_by_me: reactedByMe }
  attachments { name url }
  sender { ${USER_FIELDS} }
`;

export function getCommunicationOverview() {
  // Strawberry resolves sibling fields concurrently. Keep each database-backed
  // collection in its own request so every resolver receives its own AsyncSession.
  return Promise.all([
    graphqlRequest(`query CommunicationOverviewContacts {
      communication_contacts: communicationContacts {
        user { ${USER_FIELDS} }
        unread_count: unreadCount
        latest_message: latestMessage
        latest_message_at: latestMessageAt
      }
    }`),
    graphqlRequest(`query CommunicationOverviewChannels {
      communication_channels: communicationChannels { ${CHANNEL_FIELDS} }
    }`),
    graphqlRequest(`query CommunicationOverviewNotifications {
      notifications { ${NOTIFICATION_FIELDS} }
    }`),
  ]).then(([contacts, channels, notifications]) => ({
    communication_contacts: contacts.communication_contacts || [],
    communication_channels: channels.communication_channels || [],
    notifications: notifications.notifications || [],
  }));
}

export function getDirectMessages(contactId) {
  return graphqlRequest(`query DirectMessages($contactId: ID!) {
    direct_messages: directMessages(contactId: $contactId) { ${MESSAGE_FIELDS} }
  }`, { contactId }).then((data) => data.direct_messages);
}

export function sendDirectMessage(contactId, body, parentId = null, attachments = []) {
  return graphqlRequest(`mutation SendDirectMessage($contactId: ID!, $body: String!, $parentId: ID, $attachments: [MessageAttachmentInput!]) {
    sendDirectMessage(recipientId: $contactId, body: $body, parentId: $parentId, attachments: $attachments) { ${MESSAGE_FIELDS} }
  }`, { contactId, body, parentId, attachments }).then((data) => data.sendDirectMessage);
}

export function getChannelMessages(channelId) {
  return graphqlRequest(`query ChannelMessages($channelId: ID!) {
    channel_messages: channelMessages(channelId: $channelId) { ${CHANNEL_MESSAGE_FIELDS} }
  }`, { channelId }).then((data) => data.channel_messages);
}

export function sendChannelMessage(channelId, body, parentId = null, attachments = []) {
  return graphqlRequest(`mutation SendChannelMessage($channelId: ID!, $body: String!, $parentId: ID, $attachments: [MessageAttachmentInput!]) {
    sendChannelMessage(channelId: $channelId, body: $body, parentId: $parentId, attachments: $attachments) { ${CHANNEL_MESSAGE_FIELDS} }
  }`, { channelId, body, parentId, attachments }).then((data) => data.sendChannelMessage);
}

export function updateChatMessage(messageKind, messageId, body) {
  return graphqlRequest(`mutation UpdateChatMessage($messageKind: String!, $messageId: ID!, $body: String!) {
    updateChatMessage(messageKind: $messageKind, messageId: $messageId, body: $body)
  }`, { messageKind, messageId, body }).then((data) => data.updateChatMessage);
}

export function deleteChatMessage(messageKind, messageId) {
  return graphqlRequest(`mutation DeleteChatMessage($messageKind: String!, $messageId: ID!) {
    deleteChatMessage(messageKind: $messageKind, messageId: $messageId)
  }`, { messageKind, messageId }).then((data) => data.deleteChatMessage);
}

export function toggleChatMessageReaction(messageKind, messageId, emoji) {
  return graphqlRequest(`mutation ToggleChatMessageReaction($messageKind: String!, $messageId: ID!, $emoji: String!) {
    toggleChatMessageReaction(messageKind: $messageKind, messageId: $messageId, emoji: $emoji)
  }`, { messageKind, messageId, emoji }).then((data) => data.toggleChatMessageReaction);
}

export function toggleChatMessagePin(messageKind, messageId) {
  return graphqlRequest(`mutation ToggleChatMessagePin($messageKind: String!, $messageId: ID!) {
    toggleChatMessagePin(messageKind: $messageKind, messageId: $messageId)
  }`, { messageKind, messageId }).then((data) => data.toggleChatMessagePin);
}

export function toggleChatMessageBookmark(messageKind, messageId) {
  return graphqlRequest(`mutation ToggleChatMessageBookmark($messageKind: String!, $messageId: ID!) {
    toggleChatMessageBookmark(messageKind: $messageKind, messageId: $messageId)
  }`, { messageKind, messageId }).then((data) => data.toggleChatMessageBookmark);
}

export function searchMessages(term) {
  return graphqlRequest(`query MessageSearch($term: String!) {
    messageSearch(term: $term) {
      kind context_id: contextId context_title: contextTitle message_id: messageId body created_at: createdAt
      sender { ${USER_FIELDS} }
    }
  }`, { term }).then((data) => data.messageSearch);
}

export function markChannelRead(channelId) {
  return graphqlRequest(`mutation MarkChannelRead($channelId: ID!) {
    markChannelRead(channelId: $channelId)
  }`, { channelId }).then((data) => data.markChannelRead);
}

export function createCommunicationChannel(payload) {
  return graphqlRequest(`mutation CreateCommunicationChannel($name: String!, $description: String!, $channelType: String!, $memberIds: [ID!]!) {
    createCommunicationChannel(name: $name, description: $description, channelType: $channelType, memberIds: $memberIds) { ${CHANNEL_FIELDS} }
  }`, payload).then((data) => data.createCommunicationChannel);
}

export function updateCommunicationChannelMembers(channelId, memberIds) {
  return graphqlRequest(`mutation UpdateCommunicationChannelMembers($channelId: ID!, $memberIds: [ID!]!) {
    updateCommunicationChannelMembers(channelId: $channelId, memberIds: $memberIds) { ${CHANNEL_FIELDS} }
  }`, { channelId, memberIds }).then((data) => data.updateCommunicationChannelMembers);
}

export function markDirectConversationRead(contactId) {
  return graphqlRequest(`mutation MarkDirectConversationRead($contactId: ID!) {
    markDirectConversationRead(contactId: $contactId)
  }`, { contactId }).then((data) => data.markDirectConversationRead);
}

export function markNotificationRead(notificationId) {
  return graphqlRequest(`mutation MarkNotificationRead($notificationId: ID!) {
    markNotificationRead(notificationId: $notificationId)
  }`, { notificationId }).then((data) => data.markNotificationRead);
}

export function markAllNotificationsRead() {
  return graphqlRequest(`mutation MarkAllNotificationsRead {
    markAllNotificationsRead
  }`).then((data) => data.markAllNotificationsRead);
}

export function checkCalendarReminders() {
  return graphqlRequest(`mutation CheckCalendarReminders {
    checkCalendarReminders { ${NOTIFICATION_FIELDS} }
  }`).then((data) => data.checkCalendarReminders);
}

export class CommunicationClient {
  constructor(handlers = {}) {
    this.handlers = handlers;
    this.socket = null;
    this.closed = false;
    this.retryCount = 0;
    this.retryTimer = null;
  }

  connect() {
    if (this.closed) return;
    const socket = new WebSocket(`${websocketBaseUrl()}/api/v1/communications`);
    this.socket = socket;
    socket.addEventListener('open', () => {
      this.retryCount = 0;
      this.handlers.onStatus?.('connected');
    });
    socket.addEventListener('message', (event) => {
      try {
        this.handlers.onEvent?.(JSON.parse(event.data));
      } catch {
        this.handlers.onError?.('A live communication update could not be read.');
      }
    });
    socket.addEventListener('close', (event) => {
      if (this.socket === socket) this.socket = null;
      if (this.closed || event.code === 4401) return;
      this.handlers.onStatus?.('reconnecting');
      const delay = Math.min(8_000, 500 * (2 ** this.retryCount));
      this.retryCount += 1;
      this.retryTimer = window.setTimeout(() => this.connect(), delay);
    });
  }

  send(payload) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(payload));
    return true;
  }

  disconnect() {
    this.closed = true;
    if (this.retryTimer) window.clearTimeout(this.retryTimer);
    this.socket?.close(1000, 'Leaving communications');
    this.socket = null;
  }
}
