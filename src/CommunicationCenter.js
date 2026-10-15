import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CommunicationClient,
  checkCalendarReminders,
  createCommunicationChannel,
  getChannelMessages,
  getCommunicationOverview,
  getDirectMessages,
  markAllNotificationsRead,
  markChannelRead,
  markDirectConversationRead,
  markNotificationRead,
  searchMessages,
  sendChannelMessage,
  sendDirectMessage,
  deleteChatMessage,
  toggleChatMessageBookmark,
  toggleChatMessagePin,
  toggleChatMessageReaction,
  updateChatMessage,
  updateCommunicationChannelMembers,
} from './communicationService';
import VideoCallPanel, { IncomingCallToast } from './VideoCallPanel';
import { UserMultiSelect } from './UserPicker';

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function timeLabel(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(date);
  }
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
}

function MessagesIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-8 8H6l-4 2 1.4-4.2A9 9 0 1 1 21 12Z" /></svg>;
}

function BellIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></svg>;
}

function CallIcon({ video = false }) {
  return video
    ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 8H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-1l5 3V8l-5 3v-1a2 2 0 0 0-2-2Z" /></svg>
    : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3 4 5c0 8 7 15 15 15l2-3-5-3-2 2c-3-1-5-3-6-6l2-2-3-5Z" /></svg>;
}

function callId() {
  if (window.crypto?.randomUUID) return `call-${window.crypto.randomUUID()}`;
  return `call-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function activityNotifications(items = []) {
  return items.filter((notification) => notification.kind !== 'direct_message');
}

function UserAvatar({ user, className = '' }) {
  return <span className={`communication-avatar ${className}`} style={{ '--avatar-color': user.color }}>
    {initials(user.display_name)}
  </span>;
}

function ChannelAvatar({ channel }) {
  return <span className={`channel-avatar ${channel.channel_type}`}>{channel.channel_type === 'group' ? '◉' : '#'}</span>;
}

function MemberStack({ members = [], total = members.length }) {
  return <span className="channel-member-stack" aria-label={`${total} members`}>
    {members.slice(0, 3).map((member) => <UserAvatar key={member.id} user={member} />)}
    {total > 3 && <i>+{total - 3}</i>}
  </span>;
}

const QUICK_REACTIONS = ['👍', '❤️', '🎉', '👀', '✅', '😂'];
const POLL_PREFIX = '[[workspace-poll]]';
const POLL_REACTIONS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣'];

function parsePoll(body = '') {
  const value = typeof body === 'string' ? body : '';
  if (!value.startsWith(POLL_PREFIX)) return null;
  try {
    const poll = JSON.parse(value.slice(POLL_PREFIX.length));
    if (!poll.question || !Array.isArray(poll.options) || poll.options.length < 2) return null;
    return { question: String(poll.question), options: poll.options.slice(0, 6).map(String) };
  } catch { return null; }
}

function messagePreview(body = '') {
  const poll = parsePoll(body);
  return poll ? `Poll: ${poll.question}` : (body || '');
}

function InlineMessage({ text }) {
  const tokens = text.split(/(https?:\/\/[^\s]+|`[^`\n]+`|\*\*[^*\n]+\*\*|_[^_\n]+_)/g).filter(Boolean);
  return <>{tokens.map((token, index) => {
    if (/^https?:\/\//.test(token)) return <a key={`${token}-${index}`} href={token} target="_blank" rel="noreferrer">{token}</a>;
    if (token.startsWith('`') && token.endsWith('`')) return <code key={index}>{token.slice(1, -1)}</code>;
    if (token.startsWith('**') && token.endsWith('**')) return <strong key={index}>{token.slice(2, -2)}</strong>;
    if (token.startsWith('_') && token.endsWith('_')) return <em key={index}>{token.slice(1, -1)}</em>;
    return <React.Fragment key={index}>{token}</React.Fragment>;
  })}</>;
}

function RichMessageBody({ body }) {
  const blocks = body.split(/```/);
  return <div className="chat-rich-body">{blocks.map((block, index) => index % 2
    ? <pre key={index}><code>{block.replace(/^\w+\n/, '')}</code></pre>
    : block.split('\n').map((line, lineIndex) => <p key={`${index}-${lineIndex}`}><InlineMessage text={line} /></p>))}</div>;
}

function PollMessage({ poll, message, reactions, onReact }) {
  const total = reactions.filter((reaction) => POLL_REACTIONS.includes(reaction.emoji))
    .reduce((count, reaction) => count + reaction.count, 0);
  return <section className="chat-poll"><strong>{poll.question}</strong><small>{total} {total === 1 ? 'vote' : 'votes'} · select any that apply</small>
    {poll.options.map((option, index) => {
      const reaction = reactions.find((item) => item.emoji === POLL_REACTIONS[index]);
      const count = reaction?.count || 0;
      const percent = total ? Math.round((count / total) * 100) : 0;
      return <button key={`${option}-${index}`} className={reaction?.reacted_by_me ? 'selected' : ''} onClick={() => onReact(message, POLL_REACTIONS[index])}>
        <span style={{ width: `${percent}%` }} /><b>{option}</b><em>{count}</em>
      </button>;
    })}
  </section>;
}

function AttachmentPreview({ attachment }) {
  const cleanUrl = attachment.url.split(/[?#]/)[0].toLowerCase();
  const image = /\.(png|jpe?g|gif|webp|svg)$/.test(cleanUrl);
  const video = /\.(mp4|webm|mov)$/.test(cleanUrl);
  return <div className={`chat-attachment-preview ${image || video ? 'media' : ''}`}>
    {image && <img src={attachment.url} alt="" loading="lazy" />}
    {video && <video src={attachment.url} controls preload="metadata" />}
    <a href={attachment.url} target="_blank" rel="noreferrer"><span>↗</span><strong>{attachment.name}</strong><small>{new URL(attachment.url).hostname}</small></a>
  </div>;
}

function MessageCard({ message, kind, parent, currentUser, busy, onReply, onEdit, onDelete, onReact, onPin, onBookmark, onConvert }) {
  const [editing, setEditing] = useState(false);
  const [editBody, setEditBody] = useState(message.body || '');
  const [reactionsOpen, setReactionsOpen] = useState(false);
  const reactions = Array.isArray(message.reactions) ? message.reactions : Object.entries(message.reactions || {}).map(([emoji, users]) => ({
    emoji, count: users.length, reacted_by_me: users.includes(currentUser.id),
  }));
  const bookmarked = message.bookmarked ?? (message.bookmark_user_ids || []).includes(currentUser.id);
  const mine = message.sender.id === currentUser.id;
  const deleted = Boolean(message.deleted_at);
  const poll = parsePoll(message.body || '');
  const displayReactions = poll ? reactions.filter((reaction) => !POLL_REACTIONS.includes(reaction.emoji)) : reactions;
  const saveEdit = async () => {
    const next = editBody.trim();
    if (!next || next === message.body) { setEditing(false); return; }
    await onEdit(message, next); setEditing(false);
  };
  return <article className={`${mine ? 'mine' : ''} ${message.parent_id ? 'thread-reply' : ''} ${deleted ? 'deleted' : ''}`}>
    {!mine && <UserAvatar user={message.sender} />}
    <div className="chat-message-content">
      {parent && <button className="chat-reply-reference" onClick={() => onReply(parent)}><strong>{parent.sender.display_name}</strong><span>{parent.deleted_at ? 'Deleted message' : parent.body}</span></button>}
      {!mine && <strong className="channel-message-sender">{message.sender.display_name}</strong>}
      {editing ? <form className="chat-inline-edit" onSubmit={(event) => { event.preventDefault(); saveEdit(); }}>
        <textarea aria-label="Edit message" value={editBody} maxLength="2000" onChange={(event) => setEditBody(event.target.value)} />
        <span><button type="button" onClick={() => { setEditing(false); setEditBody(message.body); }}>Cancel</button><button disabled={!editBody.trim() || busy}>Save</button></span>
      </form> : deleted ? <p className="chat-deleted-message">Message deleted</p> : poll
        ? <PollMessage poll={poll} message={message} reactions={reactions} onReact={onReact} />
        : <RichMessageBody body={message.body} />}
      {!deleted && message.attachments?.length > 0 && <div className="chat-attachments">{message.attachments.map((attachment) => <AttachmentPreview key={`${attachment.url}-${attachment.name}`} attachment={attachment} />)}</div>}
      {!deleted && displayReactions.length > 0 && <div className="chat-reactions">{displayReactions.map((reaction) => <button key={reaction.emoji} className={reaction.reacted_by_me ? 'mine' : ''} onClick={() => onReact(message, reaction.emoji)}>{reaction.emoji} {reaction.count}</button>)}</div>}
      <span className="chat-message-meta">{message.pinned && <b title="Pinned">⌖</b>}{bookmarked && <b title="Bookmarked">★</b>}<time>{timeLabel(message.created_at)}</time>{message.edited_at && !deleted && <small>edited</small>}{mine && kind === 'direct' && !deleted && <small>{message.read ? 'Seen' : 'Sent'}</small>}</span>
      {!deleted && <div className="chat-message-actions" aria-label={`Actions for message from ${message.sender.display_name}`}>
        <button type="button" title="Reply in this conversation" onClick={() => onReply(message)}>Reply</button>
        <button type="button" title="Add a reaction" aria-expanded={reactionsOpen} onClick={() => setReactionsOpen((value) => !value)}>React</button>
        <button type="button" onClick={() => onPin(message)}>{message.pinned ? 'Unpin' : 'Pin'}</button>
        <button type="button" onClick={() => onBookmark(message)}>{bookmarked ? 'Unsave' : 'Save'}</button>
        <details className="chat-convert-menu"><summary title="Turn this message into connected work">Convert</summary><div><button type="button" onClick={() => onConvert(message, 'task')}>Task</button><button type="button" onClick={() => onConvert(message, 'request')}>Request</button><button type="button" onClick={() => onConvert(message, 'decision')}>Decision</button><button type="button" onClick={() => onConvert(message, 'risk')}>Risk</button><button type="button" onClick={() => onConvert(message, 'meeting')}>Meeting</button></div></details>
        {mine && <><button type="button" onClick={() => setEditing(true)}>Edit</button><button type="button" className="danger" onClick={() => onDelete(message)}>Delete</button></>}
      </div>}
      {reactionsOpen && !deleted && <div className="chat-reaction-picker">{QUICK_REACTIONS.map((emoji) => <button aria-label={`React ${emoji}`} key={emoji} onClick={() => { onReact(message, emoji); setReactionsOpen(false); }}>{emoji}</button>)}</div>}
    </div>
  </article>;
}

function ChannelForm({ contacts, saving, onCancel, onCreate }) {
  const [channelType, setChannelType] = useState('channel');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [memberIds, setMemberIds] = useState([]);

  const users = useMemo(() => contacts.map((contact) => contact.user || contact), [contacts]);
  const valid = name.trim().length >= 2 && (channelType === 'channel' || memberIds.length > 0);

  return <form className="channel-form" onSubmit={(event) => {
    event.preventDefault();
    if (valid) onCreate({ name: name.trim(), description: description.trim(), channelType, memberIds });
  }}>
    <div className="channel-form-heading"><div><p className="popover-eyebrow">New conversation</p><h3>Create a channel or group</h3></div>
      <button type="button" className="icon-button" aria-label="Close channel form" onClick={onCancel}>×</button></div>
    <div className="channel-type-options" role="radiogroup" aria-label="Conversation type">
      <label><input type="radio" name="channel-type" checked={channelType === 'channel'} onChange={() => setChannelType('channel')} />
        <span><strong>Workspace channel</strong><small>Everyone in the workspace can find and join the conversation.</small></span></label>
      <label><input type="radio" name="channel-type" checked={channelType === 'group'} onChange={() => setChannelType('group')} />
        <span><strong>Private group</strong><small>Only the people you select can see messages.</small></span></label>
    </div>
    <label className="channel-field">Name<input autoFocus value={name} maxLength="80" onChange={(event) => setName(event.target.value)} placeholder="e.g. Product launch" /></label>
    <label className="channel-field">Description <small>Optional</small><textarea value={description} maxLength="500" onChange={(event) => setDescription(event.target.value)} placeholder="What will this conversation cover?" /></label>
    {channelType === 'group' && <UserMultiSelect label="Group members" ariaLabel="Private group members"
      users={users} value={memberIds} onChange={setMemberIds} placeholder="Add at least one person" />}
    <div className="channel-form-actions"><button type="button" className="button secondary" onClick={onCancel}>Cancel</button>
      <button className="button primary" disabled={!valid || saving}>{saving ? 'Creating…' : `Create ${channelType}`}</button></div>
  </form>;
}

function ChannelMemberManager({ channel, contacts, currentUser, saving, onCancel, onSave }) {
  const [memberIds, setMemberIds] = useState(channel.members.map((member) => member.id));
  const users = useMemo(() => {
    const all = [...contacts.map((contact) => contact.user), currentUser];
    return [...new Map(all.map((user) => [user.id, user])).values()]
      .sort((first, second) => first.display_name.localeCompare(second.display_name));
  }, [contacts, currentUser]);

  return <form className="channel-member-manager" onSubmit={(event) => { event.preventDefault(); onSave(memberIds); }}>
    <div className="channel-form-heading"><div><p className="popover-eyebrow">Private group</p><h3>Manage members</h3></div>
      <button type="button" className="icon-button" aria-label="Close member manager" onClick={onCancel}>×</button></div>
    <p>Choose who can access <strong>{channel.name}</strong>. The group owner cannot be removed.</p>
    <UserMultiSelect label="Members" ariaLabel="Manage group members" users={users}
      value={memberIds} onChange={setMemberIds} requiredIds={[channel.created_by_id]} />
    <div className="channel-form-actions"><button type="button" className="button secondary" onClick={onCancel}>Cancel</button>
      <button className="button primary" disabled={memberIds.length < 2 || saving}>{saving ? 'Saving…' : 'Save members'}</button></div>
  </form>;
}

function PollComposer({ onCancel, onCreate }) {
  const [question, setQuestion] = useState('');
  const [options, setOptions] = useState(['', '']);
  const validOptions = options.map((option) => option.trim()).filter(Boolean);
  return <section className="chat-poll-composer" aria-label="Create a poll">
    <header><strong>Create a poll</strong><button type="button" aria-label="Close poll composer" onClick={onCancel}>×</button></header>
    <input autoFocus aria-label="Poll question" value={question} maxLength="300" onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a question" />
    {options.map((option, index) => <div key={index}><input aria-label={`Poll option ${index + 1}`} value={option} maxLength="180" onChange={(event) => setOptions((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} placeholder={`Option ${index + 1}`} />
      {options.length > 2 && <button type="button" aria-label={`Remove poll option ${index + 1}`} onClick={() => setOptions((current) => current.filter((_, itemIndex) => itemIndex !== index))}>×</button>}</div>)}
    <footer><button type="button" disabled={options.length >= 6} onClick={() => setOptions((current) => [...current, ''])}>＋ Add option</button><button type="button" disabled={!question.trim() || validOptions.length < 2} onClick={() => onCreate({ question: question.trim(), options: validOptions })}>Add poll</button></footer>
  </section>;
}

export default function CommunicationCenter({ currentUser, onNavigate }) {
  const [open, setOpen] = useState(null);
  const [contacts, setContacts] = useState([]);
  const [channels, setChannels] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [listMode, setListMode] = useState('people');
  const [selectedContact, setSelectedContact] = useState(null);
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [search, setSearch] = useState('');
  const [conversationSearch, setConversationSearch] = useState('');
  const [messageSearchResults, setMessageSearchResults] = useState([]);
  const [searchingMessages, setSearchingMessages] = useState(false);
  const [replyTo, setReplyTo] = useState(null);
  const [attachmentOpen, setAttachmentOpen] = useState(false);
  const [pollOpen, setPollOpen] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [attachmentName, setAttachmentName] = useState('');
  const [attachmentUrl, setAttachmentUrl] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState([]);
  const [messageView, setMessageView] = useState('all');
  const [busyMessageId, setBusyMessageId] = useState(null);
  const [typingUsers, setTypingUsers] = useState({});
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [savingChannel, setSavingChannel] = useState(false);
  const [channelFormOpen, setChannelFormOpen] = useState(false);
  const [memberManagerOpen, setMemberManagerOpen] = useState(false);
  const [error, setError] = useState('');
  const [activeCall, setActiveCall] = useState(null);
  const [incomingCall, setIncomingCall] = useState(null);
  const rootRef = useRef(null);
  const listRef = useRef(null);
  const selectedThreadRef = useRef(null);
  const conversationRequestRef = useRef(0);
  const communicationClientRef = useRef(null);
  const activeCallRef = useRef(null);
  const notificationClientIdRef = useRef(`call-notify-${currentUser.id}`);
  const typingTimersRef = useRef(new Map());
  const typingStopRef = useRef(null);
  const lastTypingSentRef = useRef(0);
  const composerRef = useRef(null);
  activeCallRef.current = activeCall;

  const resetConversation = useCallback(() => {
    conversationRequestRef.current += 1;
    selectedThreadRef.current = null;
    setSelectedContact(null);
    setSelectedChannel(null);
    setMessages([]);
    setDraft('');
    setReplyTo(null);
    setPendingAttachments([]);
    setAttachmentOpen(false);
    setPollOpen(false);
    setEmojiOpen(false);
    setConversationSearch('');
    setMessageView('all');
    setTypingUsers({});
    setLoadingMessages(false);
    setMemberManagerOpen(false);
  }, []);

  const reloadConversation = useCallback(async () => {
    const thread = selectedThreadRef.current;
    if (!thread) return;
    try {
      const next = thread.kind === 'person'
        ? await getDirectMessages(thread.id)
        : await getChannelMessages(thread.id);
      if (selectedThreadRef.current?.kind === thread.kind && selectedThreadRef.current?.id === thread.id) {
        setMessages(next);
      }
    } catch (requestError) {
      setError(requestError.message);
    }
  }, []);

  const applyOverview = useCallback((result) => {
    const nextChannels = result.communication_channels || [];
    setContacts(result.communication_contacts || []);
    setChannels(nextChannels);
    setNotifications(activityNotifications(result.notifications));
    setError('');
    if (selectedThreadRef.current?.kind === 'channel') {
      const selected = nextChannels.find((channel) => channel.id === selectedThreadRef.current.id);
      if (selected) setSelectedChannel(selected);
      else resetConversation();
    }
  }, [resetConversation]);

  useEffect(() => {
    let active = true;
    let overviewRetryTimer;
    const typingTimers = typingTimersRef.current;
    const refresh = (allowRetry = true) => getCommunicationOverview()
      .then((result) => { if (active) applyOverview(result); })
      .catch((requestError) => {
        if (!active) return;
        if (allowRetry) overviewRetryTimer = window.setTimeout(() => refresh(false), 500);
        else setError(requestError.message);
      });
    refresh();
    const refreshReminders = () => checkCalendarReminders()
      .then((due) => {
        if (!active || !due?.length) return;
        setNotifications((current) => {
          const existing = new Set(current.map((notification) => notification.id));
          return [...due.filter((notification) => !existing.has(notification.id)), ...current];
        });
      })
      .catch(() => {});
    refreshReminders();
    const reminderTimer = window.setInterval(refreshReminders, 60_000);

    if (typeof WebSocket === 'undefined') return () => { active = false; window.clearInterval(reminderTimer); window.clearTimeout(overviewRetryTimer); };
    const client = new CommunicationClient({
      onEvent: (event) => {
        if (event.type === 'notification' && event.notification.kind !== 'direct_message') {
          const notification = event.notification;
          setNotifications((current) => current.some((item) => item.id === notification.id)
            ? current : [notification, ...current]);
        }
        if (event.type === 'direct_message') {
          const message = event.message;
          const senderId = message.sender.id;
          const isOpenConversation = selectedThreadRef.current?.kind === 'person'
            && selectedThreadRef.current.id === senderId;
          setContacts((current) => current.map((contact) => contact.user.id === senderId ? {
            ...contact,
            latest_message: message.body,
            latest_message_at: message.created_at,
            unread_count: isOpenConversation ? 0 : contact.unread_count + 1,
          } : contact));
          if (isOpenConversation) {
            setMessages((current) => current.some((item) => item.id === message.id) ? current : [...current, message]);
            markDirectConversationRead(senderId).catch(() => {});
          }
        }
        if (event.type === 'channel_message') {
          const message = event.message;
          const isOpenChannel = selectedThreadRef.current?.kind === 'channel'
            && selectedThreadRef.current.id === message.channel_id;
          setChannels((current) => current.map((channel) => channel.id === message.channel_id ? {
            ...channel,
            latest_message: message.body,
            latest_message_at: message.created_at,
            unread_count: isOpenChannel ? 0 : channel.unread_count + 1,
          } : channel));
          if (isOpenChannel) {
            setMessages((current) => current.some((item) => item.id === message.id) ? current : [...current, message]);
            markChannelRead(message.channel_id).catch(() => {});
          }
        }
        if (event.type === 'channel_updated') refresh();
        if (event.type === 'message_changed') reloadConversation();
        if (event.type === 'direct_read' && selectedThreadRef.current?.kind === 'person'
          && selectedThreadRef.current.id === event.contact_id) reloadConversation();
        if (event.type === 'typing') {
          const thread = selectedThreadRef.current;
          const matches = thread && (
            (thread.kind === 'person' && thread.id === event.user?.id)
            || (thread.kind === 'channel' && thread.id === event.context?.id)
          );
          if (matches && event.user?.id !== currentUser.id) {
            window.clearTimeout(typingTimersRef.current.get(event.user.id));
            setTypingUsers((current) => event.active
              ? { ...current, [event.user.id]: event.user }
              : Object.fromEntries(Object.entries(current).filter(([id]) => id !== event.user.id)));
            if (event.active) typingTimersRef.current.set(event.user.id, window.setTimeout(() => {
              setTypingUsers((current) => Object.fromEntries(Object.entries(current).filter(([id]) => id !== event.user.id)));
            }, 3500));
          }
        }
        if (event.type === 'call_invite' && event.user?.id !== currentUser.id) {
          if (!activeCallRef.current || activeCallRef.current.callId !== event.call_id) {
            setIncomingCall(event);
          }
        }
      },
      onError: setError,
    });
    communicationClientRef.current = client;
    client.connect();
    return () => {
      active = false;
      window.clearInterval(reminderTimer);
      window.clearTimeout(overviewRetryTimer);
      conversationRequestRef.current += 1;
      window.clearTimeout(typingStopRef.current);
      typingTimers.forEach((timer) => window.clearTimeout(timer));
      client.disconnect();
      if (communicationClientRef.current === client) communicationClientRef.current = null;
    };
  }, [applyOverview, currentUser.id, reloadConversation]);

  useEffect(() => {
    const close = (event) => {
      if (!rootRef.current?.contains(event.target)) { setOpen(null); resetConversation(); }
    };
    const escape = (event) => {
      if (event.key === 'Escape') { setOpen(null); resetConversation(); }
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', escape);
    };
  }, [resetConversation]);

  useEffect(() => {
    const openPanel = (event) => {
      const panel = event.detail?.panel;
      if (!['messages', 'notifications'].includes(panel)) return;
      resetConversation();
      setChannelFormOpen(false);
      setOpen(panel);
    };
    window.addEventListener('workspace:open-communication', openPanel);
    return () => window.removeEventListener('workspace:open-communication', openPanel);
  }, [resetConversation]);

  useEffect(() => {
    if (listRef.current?.scrollTo) listRef.current.scrollTo({ top: listRef.current.scrollHeight });
    else if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

  const messageUnread = useMemo(() => (
    contacts.reduce((total, contact) => total + contact.unread_count, 0)
    + channels.reduce((total, channel) => total + channel.unread_count, 0)
  ), [contacts, channels]);
  const notificationUnread = useMemo(
    () => notifications.filter((notification) => !notification.read).length,
    [notifications]
  );
  const filteredContacts = useMemo(() => {
    const term = search.trim().toLowerCase();
    return contacts.filter(({ user }) => !term
      || `${user.display_name} ${user.email} ${user.handle}`.toLowerCase().includes(term))
      .sort((first, second) => first.unread_count !== second.unread_count
        ? second.unread_count - first.unread_count
        : new Date(second.latest_message_at || 0) - new Date(first.latest_message_at || 0));
  }, [contacts, search]);
  const filteredChannels = useMemo(() => {
    const term = search.trim().toLowerCase();
    return channels.filter((channel) => !term
      || `${channel.name} ${channel.description} ${channel.channel_type}`.toLowerCase().includes(term))
      .sort((first, second) => first.unread_count !== second.unread_count
        ? second.unread_count - first.unread_count
        : new Date(second.latest_message_at || 0) - new Date(first.latest_message_at || 0));
  }, [channels, search]);
  const visibleMessages = useMemo(() => {
    const term = conversationSearch.trim().toLowerCase();
    return messages.filter((message) => {
      const bookmarked = message.bookmarked ?? (message.bookmark_user_ids || []).includes(currentUser.id);
      return (!term || `${message.body} ${message.sender.display_name}`.toLowerCase().includes(term))
        && (messageView !== 'pinned' || message.pinned)
        && (messageView !== 'saved' || bookmarked);
    });
  }, [messages, conversationSearch, messageView, currentUser.id]);

  const runMessageSearch = async (event) => {
    event.preventDefault();
    if (search.trim().length < 2) return;
    setSearchingMessages(true); setError('');
    try { setMessageSearchResults(await searchMessages(search.trim())); }
    catch (requestError) { setError(requestError.message); }
    finally { setSearchingMessages(false); }
  };

  const openConversation = async (contact) => {
    const requestId = conversationRequestRef.current + 1;
    conversationRequestRef.current = requestId;
    selectedThreadRef.current = { kind: 'person', id: contact.user.id };
    setSelectedContact(contact); setSelectedChannel(null); setMessages([]); setLoadingMessages(true); setError(''); setReplyTo(null); setPendingAttachments([]); setConversationSearch(''); setPollOpen(false); setEmojiOpen(false);
    try {
      const conversation = await getDirectMessages(contact.user.id);
      if (conversationRequestRef.current !== requestId) return;
      setMessages(conversation);
      await markDirectConversationRead(contact.user.id);
      if (conversationRequestRef.current !== requestId) return;
      setContacts((current) => current.map((item) => item.user.id === contact.user.id
        ? { ...item, unread_count: 0 } : item));
    } catch (requestError) {
      if (conversationRequestRef.current === requestId) setError(requestError.message);
    } finally {
      if (conversationRequestRef.current === requestId) setLoadingMessages(false);
    }
  };

  const openChannelConversation = async (channel) => {
    const requestId = conversationRequestRef.current + 1;
    conversationRequestRef.current = requestId;
    selectedThreadRef.current = { kind: 'channel', id: channel.id };
    setSelectedChannel(channel); setSelectedContact(null); setMessages([]); setLoadingMessages(true); setError(''); setReplyTo(null); setPendingAttachments([]); setConversationSearch(''); setPollOpen(false); setEmojiOpen(false);
    try {
      const conversation = await getChannelMessages(channel.id);
      if (conversationRequestRef.current !== requestId) return;
      setMessages(conversation);
      await markChannelRead(channel.id);
      if (conversationRequestRef.current !== requestId) return;
      setChannels((current) => current.map((item) => item.id === channel.id ? { ...item, unread_count: 0 } : item));
    } catch (requestError) {
      if (conversationRequestRef.current === requestId) setError(requestError.message);
    } finally {
      if (conversationRequestRef.current === requestId) setLoadingMessages(false);
    }
  };

  const send = async (event) => {
    event.preventDefault();
    const body = draft.trim();
    if (!body || (!selectedContact && !selectedChannel) || sending) return;
    const thread = selectedThreadRef.current;
    setSending(true); setError('');
    try {
      const message = selectedContact
        ? await sendDirectMessage(selectedContact.user.id, body, replyTo?.id || null, pendingAttachments)
        : await sendChannelMessage(selectedChannel.id, body, replyTo?.id || null, pendingAttachments);
      if (selectedThreadRef.current?.kind !== thread.kind || selectedThreadRef.current?.id !== thread.id) return;
      setMessages((current) => current.some((item) => item.id === message.id) ? current : [...current, message]);
      if (selectedContact) {
        setContacts((current) => current.map((item) => item.user.id === thread.id
          ? { ...item, latest_message: message.body, latest_message_at: message.created_at } : item));
      } else {
        setChannels((current) => current.map((item) => item.id === thread.id
          ? { ...item, latest_message: message.body, latest_message_at: message.created_at } : item));
      }
      setDraft('');
      sendTyping(false);
      setReplyTo(null); setPendingAttachments([]); setAttachmentOpen(false); setAttachmentName(''); setAttachmentUrl(''); setPollOpen(false); setEmojiOpen(false);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSending(false);
    }
  };

  const sendTyping = (active) => {
    const thread = selectedThreadRef.current;
    if (!thread) return;
    communicationClientRef.current?.send?.({
      type: 'typing', active,
      context: { kind: thread.kind === 'person' ? 'direct' : 'channel', id: thread.id },
    });
  };
  const updateDraft = (value) => {
    setDraft(value);
    const now = Date.now();
    if (value.trim() && now - lastTypingSentRef.current > 1200) {
      sendTyping(true); lastTypingSentRef.current = now;
    }
    window.clearTimeout(typingStopRef.current);
    typingStopRef.current = window.setTimeout(() => sendTyping(false), 1800);
  };

  const mutateMessage = async (message, operation) => {
    const kind = selectedContact ? 'direct' : 'channel';
    setBusyMessageId(message.id); setError('');
    try { await operation(kind, message.id); await reloadConversation(); }
    catch (requestError) { setError(requestError.message); }
    finally { setBusyMessageId(null); }
  };
  const editMessage = (message, body) => mutateMessage(message, (kind, id) => updateChatMessage(kind, id, body));
  const removeMessage = (message) => {
    if (!window.confirm('Delete this message? Replies will remain visible.')) return Promise.resolve();
    return mutateMessage(message, deleteChatMessage);
  };
  const reactToMessage = (message, emoji) => mutateMessage(message, (kind, id) => toggleChatMessageReaction(kind, id, emoji));
  const pinMessage = (message) => mutateMessage(message, toggleChatMessagePin);
  const bookmarkMessage = (message) => mutateMessage(message, toggleChatMessageBookmark);
  const convertMessage = (message, type) => {
    const title = message.body.slice(0, 160);
    if (type === 'meeting') {
      const path = `/calendar?${new URLSearchParams({ create: '1', title, description: `Created from message ${message.id}` })}`;
      if (onNavigate) onNavigate(path); else window.location.assign(path); return;
    }
    if (['decision', 'risk'].includes(type)) {
      const path = `/operations?${new URLSearchParams({ tab: 'projects', create: type, title, source: 'chat', message: message.id })}`;
      if (onNavigate) onNavigate(path); else window.location.assign(path); return;
    }
    const params = new URLSearchParams({ create: '1', item_type: type, summary: title, source: 'chat', message: message.id });
    const path = `/work?${params.toString()}`;
    if (onNavigate) onNavigate(path); else window.location.assign(path);
  };
  const addAttachment = () => {
    const name = attachmentName.trim(); const url = attachmentUrl.trim();
    try {
      const parsed = new URL(url);
      if (!['http:', 'https:'].includes(parsed.protocol) || !name) throw new Error();
    } catch {
      setError('Attachment links need a name and a valid HTTP(S) URL.'); return;
    }
    setPendingAttachments((current) => [...current, { name, url }].slice(0, 5));
    setAttachmentName(''); setAttachmentUrl(''); setAttachmentOpen(false);
  };
  const applyFormatting = (before, after = before) => {
    const field = composerRef.current;
    const start = field?.selectionStart ?? draft.length;
    const end = field?.selectionEnd ?? draft.length;
    const selected = draft.slice(start, end);
    const next = `${draft.slice(0, start)}${before}${selected}${after}${draft.slice(end)}`;
    setDraft(next);
    window.requestAnimationFrame(() => {
      field?.focus();
      const cursor = start + before.length + selected.length + (selected ? after.length : 0);
      field?.setSelectionRange(selected ? cursor : start + before.length, selected ? cursor : start + before.length);
    });
  };
  const insertEmoji = (emoji) => {
    applyFormatting(emoji, ''); setEmojiOpen(false);
  };
  const createPollDraft = (poll) => {
    setDraft(`${POLL_PREFIX}${JSON.stringify(poll)}`);
    setPollOpen(false); setEmojiOpen(false); setAttachmentOpen(false);
  };
  const downloadConversation = () => {
    const payload = {
      exported_at: new Date().toISOString(),
      conversation: { kind: selectedContact ? 'direct' : selectedChannel.channel_type, id: selectedContact?.user.id || selectedChannel.id, title: threadTitle },
      messages: messages.map((message) => ({
        id: message.id, sender: message.sender.display_name, body: messagePreview(message.body),
        attachments: message.attachments || [], reactions: message.reactions || [], created_at: message.created_at,
      })),
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url;
    link.download = `${threadTitle.replace(/[^a-z0-9]+/gi, '-').toLowerCase() || 'conversation'}-export.json`;
    link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const createChannel = async (payload) => {
    setSavingChannel(true); setError('');
    try {
      const channel = await createCommunicationChannel(payload);
      setChannels((current) => [channel, ...current.filter((item) => item.id !== channel.id)]);
      setChannelFormOpen(false); setListMode('channels'); setSearch('');
      await openChannelConversation(channel);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSavingChannel(false);
    }
  };

  const saveMembers = async (memberIds) => {
    setSavingChannel(true); setError('');
    try {
      const channel = await updateCommunicationChannelMembers(selectedChannel.id, memberIds);
      setSelectedChannel(channel);
      setChannels((current) => current.map((item) => item.id === channel.id ? channel : item));
      setMemberManagerOpen(false);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSavingChannel(false);
    }
  };

  const readNotification = async (notification) => {
    if (!notification.read) {
      setNotifications((current) => current.map((item) => item.id === notification.id ? { ...item, read: true } : item));
      markNotificationRead(notification.id).catch(() => {});
    }
    if (notification.document_id) {
      const path = `/knowledge?document=${notification.document_id}`;
      if (onNavigate) onNavigate(path); else window.location.assign(path);
    } else if (notification.contact_id) {
      const contact = contacts.find((item) => item.user.id === notification.contact_id);
      if (contact) { setOpen('messages'); await openConversation(contact); }
    } else if (notification.communication_channel_id) {
      const channel = channels.find((item) => item.id === notification.communication_channel_id);
      if (channel) { setOpen('messages'); await openChannelConversation(channel); }
    } else if (notification.work_item_id) {
      const path = `/work?item=${notification.work_item_id}`;
      if (onNavigate) onNavigate(path); else window.location.assign(path);
    } else if (notification.calendar_event_id) {
      const path = `/calendar?event=${notification.calendar_event_id}`;
      if (onNavigate) onNavigate(path); else window.location.assign(path);
    } else if (notification.project_id) {
      const path = `/projects/${notification.project_id}`;
      if (onNavigate) onNavigate(path); else window.location.assign(path);
    }
  };

  const readAllNotifications = () => {
    setNotifications((current) => current.map((item) => ({ ...item, read: true })));
    markAllNotificationsRead().catch((requestError) => setError(requestError.message));
  };

  const activeThread = selectedContact || selectedChannel;
  const threadTitle = selectedContact?.user.display_name || selectedChannel?.name || '';
  const composerPlaceholder = selectedContact ? `Message @${selectedContact.user.handle}…` : `Message ${selectedChannel?.name || ''}…`;
  const mentionMatch = selectedChannel ? draft.match(/(?:^|\s)@([A-Za-z0-9._-]*)$/) : null;
  const mentionCandidates = mentionMatch ? (selectedChannel.members || []).filter((member) => member.id !== currentUser.id
    && `${member.handle} ${member.display_name}`.toLowerCase().includes(mentionMatch[1].toLowerCase())).slice(0, 6) : [];
  const selectMention = (member) => {
    setDraft((current) => current.replace(/@([A-Za-z0-9._-]*)$/, `@${member.handle} `));
  };
  const beginCall = (media) => {
    if (!activeThread) return;
    setActiveCall({
      callId: callId(),
      context: selectedContact
        ? { kind: 'direct', id: selectedContact.user.id }
        : { kind: 'channel', id: selectedChannel.id },
      title: selectedContact ? selectedContact.user.display_name : selectedChannel.name,
      media,
      ring: true,
      isHost: true,
    });
    setIncomingCall(null);
    setOpen(null);
  };
  const acceptIncomingCall = () => {
    setActiveCall({
      callId: incomingCall.call_id,
      context: incomingCall.context,
      title: incomingCall.title || incomingCall.user.display_name,
      media: incomingCall.media,
      ring: false,
      isHost: false,
    });
    setIncomingCall(null);
    setOpen(null);
  };
  const declineIncomingCall = () => {
    communicationClientRef.current?.send({
      type: 'call_decline',
      call_id: incomingCall.call_id,
      client_id: notificationClientIdRef.current,
      context: incomingCall.context,
      media: incomingCall.media,
      title: incomingCall.title || '',
      target_user_id: incomingCall.user.id,
      target_client_id: incomingCall.client_id,
    });
    setIncomingCall(null);
  };

  return <div className="communication-controls" ref={rootRef}>
    <button className="header-icon-button" aria-label="Messages" aria-expanded={open === 'messages'}
      onClick={() => { setOpen((current) => current === 'messages' ? null : 'messages'); resetConversation(); setChannelFormOpen(false); }}>
      <MessagesIcon />
      {messageUnread > 0 && <span className="notification-badge">{messageUnread > 99 ? '99+' : messageUnread}</span>}
    </button>
    <button className="header-icon-button" aria-label="Notifications" aria-expanded={open === 'notifications'}
      onClick={() => { setOpen((current) => current === 'notifications' ? null : 'notifications'); resetConversation(); }}>
      <BellIcon />
      {notificationUnread > 0 && <span className="notification-badge">{notificationUnread > 99 ? '99+' : notificationUnread}</span>}
    </button>

    {open === 'messages' && <section className="communication-popover messages-popover" role="dialog" aria-modal="false" aria-label="Workspace messages">
      {channelFormOpen ? <ChannelForm contacts={contacts} saving={savingChannel} onCancel={() => setChannelFormOpen(false)} onCreate={createChannel} />
        : memberManagerOpen && selectedChannel ? <ChannelMemberManager channel={selectedChannel} contacts={contacts} currentUser={currentUser}
          saving={savingChannel} onCancel={() => setMemberManagerOpen(false)} onSave={saveMembers} />
          : !activeThread ? <>
            <header><div><p className="popover-eyebrow">Workspace communication</p><h2>Messages</h2></div>
              <button className="channel-create-button" aria-label="Create channel or group" onClick={() => setChannelFormOpen(true)}>＋</button>
              <span className="communication-live"><i /> Live</span><button className="icon-button communication-close" aria-label="Close messages" onClick={() => setOpen(null)}>×</button></header>
            <div className="message-mode-tabs" role="tablist" aria-label="Message views">
              <button role="tab" aria-selected={listMode === 'people'} className={listMode === 'people' ? 'active' : ''} onClick={() => { setListMode('people'); setSearch(''); }}>People</button>
              <button role="tab" aria-selected={listMode === 'channels'} className={listMode === 'channels' ? 'active' : ''} onClick={() => { setListMode('channels'); setSearch(''); }}>Channels &amp; groups</button>
              <button role="tab" aria-selected={listMode === 'search'} className={listMode === 'search' ? 'active' : ''} onClick={() => { setListMode('search'); setSearch(''); setMessageSearchResults([]); }}>Search messages</button>
            </div>
            {listMode === 'search' ? <form className="contact-search message-global-search" onSubmit={runMessageSearch}><span>⌕</span><input aria-label="Search all messages" value={search}
              onChange={(event) => setSearch(event.target.value)} placeholder="Search message history" /><button disabled={search.trim().length < 2 || searchingMessages}>{searchingMessages ? '…' : 'Search'}</button></form>
              : <div className="contact-search"><span>⌕</span><input aria-label="Search contacts" value={search}
                onChange={(event) => setSearch(event.target.value)} placeholder={listMode === 'people' ? 'Search people' : 'Search channels and groups'} /></div>}
            {listMode === 'people' ? <div className="message-contact-list">
              {filteredContacts.length === 0 && <div className="communication-empty"><span>✦</span><strong>No contacts yet</strong><p>Workspace contacts appear here after onboarding.</p></div>}
              {filteredContacts.map((contact) => <button key={contact.user.id} aria-label={`Message ${contact.user.display_name}`} onClick={() => openConversation(contact)}>
                <UserAvatar user={contact.user} />
                <span><strong>{contact.user.display_name}<small>@{contact.user.handle}</small></strong>
                  <em>{messagePreview(contact.latest_message) || `${contact.user.role === 'admin' ? 'Admin' : 'Basic user'} · Start a conversation`}</em></span>
                <span className="contact-message-meta">{contact.latest_message_at && <time>{timeLabel(contact.latest_message_at)}</time>}
                  {contact.unread_count > 0 && <b>{contact.unread_count}</b>}</span>
              </button>)}
            </div> : listMode === 'channels' ? <div className="message-contact-list channel-list">
              {filteredChannels.length === 0 && <div className="communication-empty"><span>#</span><strong>No conversations yet</strong><p>Create a workspace channel or a private group.</p></div>}
              {filteredChannels.map((channel) => <button key={channel.id} aria-label={`Open ${channel.name}`} onClick={() => openChannelConversation(channel)}>
                <ChannelAvatar channel={channel} />
                <span><strong>{channel.name}<small>{channel.channel_type === 'group' ? 'Private group' : 'Workspace channel'}</small></strong>
                  <em>{messagePreview(channel.latest_message) || channel.description || `${channel.member_count} members · Start the conversation`}</em></span>
                <span className="contact-message-meta">{channel.latest_message_at ? <time>{timeLabel(channel.latest_message_at)}</time>
                  : <MemberStack members={channel.members} total={channel.member_count} />}
                  {channel.unread_count > 0 && <b>{channel.unread_count}</b>}</span>
              </button>)}
            </div> : <div className="message-search-results">
              {messageSearchResults.length === 0 && !searchingMessages && <div className="communication-empty"><span>⌕</span><strong>Find past decisions and context</strong><p>Searches only conversations you are allowed to access.</p></div>}
              {messageSearchResults.map((result) => <button key={`${result.kind}-${result.message_id}`} onClick={() => {
                if (result.kind === 'direct') {
                  const contact = contacts.find((item) => item.user.id === result.context_id); if (contact) openConversation(contact);
                } else {
                  const channel = channels.find((item) => item.id === result.context_id); if (channel) openChannelConversation(channel);
                }
              }}><span><strong>{result.context_title}</strong><small>{result.sender.display_name} · {timeLabel(result.created_at)}</small></span><p>{result.body}</p></button>)}
            </div>}
          </> : <>
            <header className="conversation-header"><button className="icon-button" aria-label="Back to contacts" onClick={resetConversation}>←</button>
              {selectedContact ? <UserAvatar user={selectedContact.user} /> : <ChannelAvatar channel={selectedChannel} />}
              <div><h2>{threadTitle}</h2><p>{selectedContact
                ? `@${selectedContact.user.handle} · ${selectedContact.user.role}`
                : `${selectedChannel.channel_type === 'group' ? 'Private group' : 'Workspace channel'} · ${selectedChannel.member_count} members`}</p></div>
              <div className="conversation-header-actions">
                {selectedChannel && <MemberStack members={selectedChannel.members || []} total={selectedChannel.member_count} />}
                {selectedChannel?.channel_type === 'group' && selectedChannel.can_manage
                  && <button className="channel-members-button" onClick={() => setMemberManagerOpen(true)}>Members</button>}
                <div className="conversation-call-actions">
                  <button aria-label={`Start audio call with ${threadTitle}`} onClick={() => beginCall('audio')}><CallIcon /></button>
                  <button aria-label={`Start video call with ${threadTitle}`} onClick={() => beginCall('video')}><CallIcon video /></button>
                </div>
                <button className="icon-button communication-close" aria-label="Close messages" onClick={() => setOpen(null)}>×</button>
              </div>
            </header>
            <div className="chat-tools"><label><span>⌕</span><input type="search" aria-label="Search this conversation" value={conversationSearch} onChange={(event) => setConversationSearch(event.target.value)} placeholder="Search this conversation" /></label>
              <div><button className={messageView === 'all' ? 'active' : ''} onClick={() => setMessageView('all')}>All</button><button className={messageView === 'pinned' ? 'active' : ''} onClick={() => setMessageView('pinned')}>⌖ Pinned</button><button className={messageView === 'saved' ? 'active' : ''} onClick={() => setMessageView('saved')}>★ Saved</button><button title="Export this conversation" onClick={downloadConversation}>⇩ Export</button></div></div>
            <div className="direct-message-list" ref={listRef}>
              {loadingMessages && <div className="communication-loading"><span className="spinner dark" /> Loading conversation…</div>}
              {!loadingMessages && messages.length === 0 && <div className="communication-empty"><span>↗</span><strong>{selectedContact ? 'Say hello' : 'Start the conversation'}</strong><p>{selectedContact ? 'Messages are private to you and this person.' : 'Everyone in this conversation can read and reply.'}</p></div>}
              {!loadingMessages && messages.length > 0 && visibleMessages.length === 0 && <div className="communication-empty compact"><span>⌕</span><strong>No matching messages</strong><p>Clear the search or change the message filter.</p></div>}
              {visibleMessages.map((message) => <MessageCard currentUser={currentUser} message={message} kind={selectedContact ? 'direct' : 'channel'}
                parent={message.parent_id ? messages.find((candidate) => candidate.id === message.parent_id) : null} key={message.id}
                busy={busyMessageId === message.id} onReply={setReplyTo} onEdit={editMessage} onDelete={removeMessage}
                onReact={reactToMessage} onPin={pinMessage} onBookmark={bookmarkMessage} onConvert={convertMessage} />)}
            </div>
            <form className="direct-message-composer advanced" onSubmit={send}>
              {replyTo && <div className="composer-context"><span><strong>Replying to {replyTo.sender.display_name}</strong><small>{replyTo.body || 'Deleted message'}</small></span><button type="button" aria-label="Cancel reply" onClick={() => setReplyTo(null)}>×</button></div>}
              {pendingAttachments.length > 0 && <div className="composer-attachments">{pendingAttachments.map((attachment) => <span key={attachment.url}>↗ {attachment.name}<button type="button" aria-label={`Remove ${attachment.name}`} onClick={() => setPendingAttachments((current) => current.filter((item) => item.url !== attachment.url))}>×</button></span>)}</div>}
              {attachmentOpen && <div className="composer-attachment-form"><input aria-label="Attachment name" value={attachmentName} maxLength="160" onChange={(event) => setAttachmentName(event.target.value)} placeholder="Link name" /><input aria-label="Attachment URL" type="url" value={attachmentUrl} maxLength="2000" onChange={(event) => setAttachmentUrl(event.target.value)} placeholder="https://…" /><button type="button" onClick={addAttachment}>Add link</button></div>}
              {pollOpen && <PollComposer onCancel={() => setPollOpen(false)} onCreate={createPollDraft} />}
              {Object.keys(typingUsers).length > 0 && <div className="chat-typing"><i /><span>{Object.values(typingUsers).map((person) => person.display_name).join(', ')} {Object.keys(typingUsers).length === 1 ? 'is' : 'are'} typing…</span></div>}
              {mentionCandidates.length > 0 && <div className="chat-mention-suggestions" role="listbox" aria-label="Mention a teammate">{mentionCandidates.map((member) => <button type="button" role="option" aria-selected="false" key={member.id} onClick={() => selectMention(member)}><UserAvatar user={member} /><span><strong>{member.display_name}</strong><small>@{member.handle}</small></span></button>)}</div>}
              {!pollOpen && <div className="chat-format-toolbar" aria-label="Message formatting"><button type="button" aria-label="Bold" onClick={() => applyFormatting('**')}><b>B</b></button><button type="button" aria-label="Italic" onClick={() => applyFormatting('_')}><i>I</i></button><button type="button" aria-label="Inline code" onClick={() => applyFormatting('`')}>&lt;/&gt;</button><button type="button" aria-label="Code block" onClick={() => applyFormatting('```\n', '\n```')}>Code</button><button type="button" aria-label="Bulleted list" onClick={() => applyFormatting('• ', '')}>List</button></div>}
              {emojiOpen && <div className="chat-emoji-picker" aria-label="Choose emoji">{QUICK_REACTIONS.map((emoji) => <button type="button" key={emoji} aria-label={`Insert ${emoji}`} onClick={() => insertEmoji(emoji)}>{emoji}</button>)}</div>}
              {!pollOpen && <textarea ref={composerRef} aria-label={`Message ${threadTitle}`} value={draft} maxLength="2000" onChange={(event) => updateDraft(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }}
                placeholder={`${composerPlaceholder} Enter to send · Shift+Enter for a new line`} />}
              <div><span className="chat-composer-actions"><button type="button" className="chat-attach-button" disabled={pendingAttachments.length >= 5} onClick={() => { setAttachmentOpen((value) => !value); setPollOpen(false); }}>＋ Link</button><button type="button" onClick={() => setEmojiOpen((value) => !value)}>☺ Emoji</button><button type="button" onClick={() => { setPollOpen(true); setAttachmentOpen(false); setEmojiOpen(false); }}>▥ Poll</button><small>{draft.length}/2000</small></span><button className="button primary" disabled={!draft.trim() || sending}>{sending ? 'Sending…' : replyTo ? 'Reply' : 'Send'}</button></div></form>
          </>}
      {error && <div className="communication-error" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
    </section>}

    {open === 'notifications' && <section className="communication-popover notifications-popover" role="dialog" aria-modal="false" aria-label="Notifications panel">
      <header><div><p className="popover-eyebrow">Activity</p><h2>Notifications</h2></div>
        <div className="notification-header-actions">{notificationUnread > 0 && <button className="text-button" onClick={readAllNotifications}>Mark all read</button>}<button className="icon-button communication-close" aria-label="Close notifications" onClick={() => setOpen(null)}>×</button></div></header>
      <div className="notification-list">
        {notifications.length === 0 && <div className="communication-empty"><span>✓</span><strong>You’re all caught up</strong><p>Mentions, assignments, and workspace activity will appear here.</p></div>}
        {notifications.map((notification) => <button key={notification.id}
          className={`notification-item ${notification.read ? '' : 'unread'}`} onClick={() => readNotification(notification)}>
          <span className="notification-mark" />
          <span><strong>{notification.title}</strong><small>{notification.body}</small><time>{timeLabel(notification.created_at)}</time></span>
        </button>)}
      </div>
      {error && <div className="communication-error" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
    </section>}
    {incomingCall && !activeCall && <IncomingCallToast call={incomingCall} onAccept={acceptIncomingCall} onDecline={declineIncomingCall} />}
    {activeCall && <VideoCallPanel currentUser={currentUser} call={activeCall} onClose={() => setActiveCall(null)} />}
  </div>;
}
