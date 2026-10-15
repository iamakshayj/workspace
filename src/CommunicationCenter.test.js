import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import CommunicationCenter from './CommunicationCenter';
import {
  checkCalendarReminders,
  createCommunicationChannel,
  getChannelMessages,
  getCommunicationOverview,
  getDirectMessages,
  markChannelRead,
  markDirectConversationRead,
  sendDirectMessage,
  toggleChatMessageReaction,
  updateChatMessage,
} from './communicationService';

jest.mock('./communicationService', () => ({
  CommunicationClient: class {
    connect() {}
    disconnect() {}
  },
  checkCalendarReminders: jest.fn(),
  createCommunicationChannel: jest.fn(),
  deleteChatMessage: jest.fn(),
  getChannelMessages: jest.fn(),
  getCommunicationOverview: jest.fn(),
  getDirectMessages: jest.fn(),
  markAllNotificationsRead: jest.fn(),
  markChannelRead: jest.fn(),
  markDirectConversationRead: jest.fn(),
  markNotificationRead: jest.fn(),
  searchMessages: jest.fn(),
  sendChannelMessage: jest.fn(),
  sendDirectMessage: jest.fn(),
  toggleChatMessageBookmark: jest.fn(),
  toggleChatMessagePin: jest.fn(),
  toggleChatMessageReaction: jest.fn(),
  updateChatMessage: jest.fn(),
  updateCommunicationChannelMembers: jest.fn(),
}));

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

const currentUser = {
  id: 'current-user', display_name: 'Current User', handle: 'current', role: 'admin', color: '#555',
};
const contacts = [
  { user: { id: 'user-a', display_name: 'Ava Alpha', email: 'ava@example.com', handle: 'ava', role: 'basic', color: '#111' }, unread_count: 0 },
  { user: { id: 'user-b', display_name: 'Ben Beta', email: 'ben@example.com', handle: 'ben', role: 'basic', color: '#222' }, unread_count: 0 },
];

beforeEach(() => {
  jest.clearAllMocks();
  getCommunicationOverview.mockResolvedValue({ communication_contacts: contacts, communication_channels: [], notifications: [] });
  checkCalendarReminders.mockResolvedValue([]);
  markDirectConversationRead.mockResolvedValue(true);
  markChannelRead.mockResolvedValue(true);
});

test('shows direct-message unread counts only on the Messages widget', async () => {
  getCommunicationOverview.mockResolvedValue({
    communication_contacts: [{ ...contacts[0], unread_count: 2 }],
    communication_channels: [],
    notifications: [
      {
        id: 'message-notification', kind: 'direct_message', title: 'New message from Ava',
        body: 'Can you review this?', contact_id: 'user-a', read: false, created_at: '2026-08-26T12:00:00Z',
      },
      {
        id: 'mention-notification', kind: 'mention', title: 'Ava mentioned you',
        body: 'Please review this note.', project_id: 'project-1', read: false, created_at: '2026-08-26T12:00:00Z',
      },
    ],
  });

  render(<CommunicationCenter currentUser={currentUser} />);

  const messagesButton = screen.getByRole('button', { name: 'Messages' });
  const notificationsButton = screen.getByRole('button', { name: 'Notifications' });
  await waitFor(() => expect(within(messagesButton).getByText('2')).toBeInTheDocument());
  expect(within(notificationsButton).getByText('1')).toBeInTheDocument();

  fireEvent.click(notificationsButton);
  expect(await screen.findByText('Ava mentioned you')).toBeInTheDocument();
  expect(screen.queryByText('New message from Ava')).not.toBeInTheDocument();
});

test('delivers calendar reminders only through the notification widget', async () => {
  checkCalendarReminders.mockResolvedValue([{
    id: 'calendar-reminder-1', kind: 'calendar_reminder',
    title: 'Planning review starts in 15 minutes', body: 'Friday, Aug 29 · 2:00 PM CDT',
    calendar_event_id: 'event-1', read: false, created_at: '2026-08-29T18:45:00Z', actor: null,
  }]);

  render(<CommunicationCenter currentUser={currentUser} />);

  const notificationsButton = screen.getByRole('button', { name: 'Notifications' });
  await waitFor(() => expect(within(notificationsButton).getByText('1')).toBeInTheDocument());
  expect(within(screen.getByRole('button', { name: 'Messages' })).queryByText('1')).not.toBeInTheDocument();
  fireEvent.click(notificationsButton);
  expect(await screen.findByText('Planning review starts in 15 minutes')).toBeInTheDocument();
});

test('shows channel unread counts and opens a workspace channel', async () => {
  const channel = {
    id: 'channel-1', name: 'Product launch', description: 'Launch coordination',
    channel_type: 'channel', visibility: 'workspace', unread_count: 3,
    latest_message: 'Ready for review', latest_message_at: '2026-08-26T12:00:00Z',
    member_count: 3, members: [currentUser, contacts[0].user, contacts[1].user],
    created_by_id: currentUser.id, can_manage: true,
  };
  getCommunicationOverview.mockResolvedValue({
    communication_contacts: contacts, communication_channels: [channel], notifications: [],
  });
  getChannelMessages.mockResolvedValue([{
    id: 'channel-message-1', channel_id: channel.id, body: 'Ready for review',
    created_at: '2026-08-26T12:00:00Z', sender: contacts[0].user,
  }]);

  render(<CommunicationCenter currentUser={currentUser} />);

  const messagesButton = screen.getByRole('button', { name: 'Messages' });
  await waitFor(() => expect(within(messagesButton).getByText('3')).toBeInTheDocument());
  fireEvent.click(messagesButton);
  fireEvent.click(screen.getByRole('tab', { name: /channels & groups/i }));
  fireEvent.click(await screen.findByRole('button', { name: /open product launch/i }));

  expect(await screen.findByText('Ready for review')).toBeInTheDocument();
  expect(getChannelMessages).toHaveBeenCalledWith(channel.id);
  expect(markChannelRead).toHaveBeenCalledWith(channel.id);
});

test('creates a private group with selected workspace contacts', async () => {
  const created = {
    id: 'group-1', name: 'Launch leads', description: '', channel_type: 'group', visibility: 'private',
    unread_count: 0, latest_message: null, latest_message_at: null, member_count: 2,
    members: [currentUser, contacts[0].user], created_by_id: currentUser.id, can_manage: true,
  };
  createCommunicationChannel.mockResolvedValue(created);
  getChannelMessages.mockResolvedValue([]);

  render(<CommunicationCenter currentUser={currentUser} />);
  fireEvent.click(screen.getByRole('button', { name: 'Messages' }));
  fireEvent.click(await screen.findByRole('button', { name: /create channel or group/i }));
  fireEvent.click(screen.getByLabelText(/private group/i));
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Launch leads' } });
  fireEvent.click(screen.getByRole('combobox', { name: /private group members/i }));
  fireEvent.change(screen.getByRole('searchbox', { name: /search private group members/i }), {
    target: { value: 'ava' },
  });
  fireEvent.click(screen.getByRole('option', { name: /Ava Alpha/i }));
  fireEvent.click(screen.getByRole('button', { name: /create group/i }));

  await waitFor(() => expect(createCommunicationChannel).toHaveBeenCalledWith({
    name: 'Launch leads', description: '', channelType: 'group', memberIds: ['user-a'],
  }));
  expect(await screen.findByRole('heading', { name: 'Launch leads' })).toBeInTheDocument();
});

test('does not show a stale conversation response after switching contacts', async () => {
  const first = deferred();
  const second = deferred();
  getDirectMessages.mockImplementation((contactId) => (
    contactId === 'user-a' ? first.promise : second.promise
  ));
  render(<CommunicationCenter currentUser={currentUser} />);

  fireEvent.click(screen.getByRole('button', { name: /messages/i }));
  fireEvent.click(await screen.findByRole('button', { name: /Ava Alpha/i }));
  fireEvent.click(screen.getByRole('button', { name: /back to contacts/i }));
  fireEvent.click(screen.getByRole('button', { name: /Ben Beta/i }));

  second.resolve([{
    id: 'message-b', body: 'Message for Ben', created_at: '2026-08-26T12:00:00Z',
    sender: currentUser, recipient: contacts[1].user,
  }]);
  expect(await screen.findByText('Message for Ben')).toBeInTheDocument();

  first.resolve([{
    id: 'message-a', body: 'Stale message for Ava', created_at: '2026-08-26T12:00:00Z',
    sender: currentUser, recipient: contacts[0].user,
  }]);
  await waitFor(() => expect(screen.queryByText('Stale message for Ava')).not.toBeInTheDocument());
});

test('opens a permission-safe video-call lobby from a direct conversation', async () => {
  getDirectMessages.mockResolvedValue([]);
  render(<CommunicationCenter currentUser={currentUser} />);

  fireEvent.click(screen.getByRole('button', { name: 'Messages' }));
  fireEvent.click(await screen.findByRole('button', { name: /message Ava Alpha/i }));
  fireEvent.click(await screen.findByRole('button', { name: /start video call with Ava Alpha/i }));

  expect(screen.getByRole('dialog', { name: /Ava Alpha call/i })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Ready to join?' })).toBeInTheDocument();
  expect(screen.getByRole('radio', { name: /video/i })).toHaveAttribute('aria-checked', 'true');
  expect(screen.getByRole('button', { name: 'Join now' })).toBeEnabled();
});

test('supports replies, reactions, and author edits in a conversation', async () => {
  const message = {
    id: 'message-1', body: 'Review the launch plan', created_at: '2026-08-26T12:00:00Z',
    sender: currentUser, recipient: contacts[0].user, parent_id: null, reactions: [],
    attachments: [], pinned: false, bookmarked: false, can_edit: true,
  };
  getDirectMessages.mockResolvedValue([message]);
  sendDirectMessage.mockResolvedValue({ ...message, id: 'message-2', body: 'On it', parent_id: message.id });
  toggleChatMessageReaction.mockResolvedValue(true);
  updateChatMessage.mockResolvedValue(true);
  render(<CommunicationCenter currentUser={currentUser} />);

  fireEvent.click(screen.getByRole('button', { name: 'Messages' }));
  fireEvent.click(await screen.findByRole('button', { name: /message Ava Alpha/i }));
  expect(await screen.findByText('Review the launch plan')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Reply' }));
  expect(screen.getByText(/Replying to Current User/i)).toBeInTheDocument();
  const composer = screen.getByRole('textbox', { name: /Message Ava Alpha/i });
  fireEvent.change(composer, { target: { value: 'On it' } });
  fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
  await waitFor(() => expect(sendDirectMessage).toHaveBeenCalledWith('user-a', 'On it', 'message-1', []));

  fireEvent.click(screen.getByRole('button', { name: 'React' }));
  fireEvent.click(screen.getByRole('button', { name: 'React 👍' }));
  await waitFor(() => expect(toggleChatMessageReaction).toHaveBeenCalledWith('direct', 'message-1', '👍'));

  fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
  const editor = screen.getByRole('textbox', { name: 'Edit message' });
  fireEvent.change(editor, { target: { value: 'Review the approved launch plan' } });
  const saveEdit = within(editor.closest('form')).getByRole('button', { name: 'Save' });
  await waitFor(() => expect(saveEdit).toBeEnabled());
  fireEvent.click(saveEdit);
  await waitFor(() => expect(updateChatMessage).toHaveBeenCalledWith('direct', 'message-1', 'Review the approved launch plan'));
});

test('builds a poll in the message composer and sends it through the existing conversation', async () => {
  const existingPoll = '[[workspace-poll]]{"question":"Which demo should we run?","options":["Customer onboarding","Release planning"]}';
  getDirectMessages.mockResolvedValue([{
    id: 'existing-poll', body: existingPoll, created_at: '2026-08-26T12:00:00Z',
    sender: contacts[0].user, recipient: currentUser, reactions: [], attachments: [],
  }]);
  sendDirectMessage.mockImplementation((contactId, body) => Promise.resolve({
    id: 'poll-message', body, created_at: '2026-08-26T12:00:00Z',
    sender: currentUser, recipient: contacts[0].user, reactions: [], attachments: [],
  }));
  render(<CommunicationCenter currentUser={currentUser} />);

  fireEvent.click(screen.getByRole('button', { name: 'Messages' }));
  fireEvent.click(await screen.findByRole('button', { name: /message Ava Alpha/i }));
  expect(await screen.findByText('Which demo should we run?')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Customer onboarding/i })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /poll/i }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Poll question' }), { target: { value: 'Which launch window?' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Poll option 1' }), { target: { value: 'Tuesday' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Poll option 2' }), { target: { value: 'Thursday' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add poll' }));
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  await waitFor(() => expect(sendDirectMessage).toHaveBeenCalledWith(
    'user-a', expect.stringContaining('[[workspace-poll]]'), null, []
  ));
});
