import React, { useEffect, useState } from 'react';
import ProjectPlan from './ProjectPlan';
import { UserSelect } from './UserPicker';

function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function timeLabel(value) {
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date(value));
}

function MentionText({ children }) {
  const parts = String(children).split(/(@[a-z0-9._-]+)/gi);
  return <>{parts.map((part, index) => part.startsWith('@')
    ? <mark className="mention" key={`${part}-${index}`}>{part}</mark>
    : part)}</>;
}

export function PresenceStack({ users, status }) {
  const visible = users.slice(0, 4);
  return <div className="presence-wrap">
    <div className="presence-stack" aria-label={`${users.length} active on this workflow`}>
      {visible.map((user) => <span className="presence-avatar" key={user.id} title={`${user.display_name} · ${user.role}`}
        style={{ '--avatar-color': user.color }}>{initials(user.display_name)}</span>)}
      {users.length > visible.length && <span className="presence-avatar overflow">+{users.length - visible.length}</span>}
    </div>
    <span className="presence-count">{users.length ? `${users.length} active` : 'Joining'}</span>
    <span className={`live-status ${status}`}><span />{status === 'connected' ? 'Live' : status === 'connecting' ? 'Joining…' : status === 'reconnecting' ? 'Reconnecting…' : 'Offline'}</span>
  </div>;
}

export function RemoteCursors({ cursors }) {
  return <div className="remote-cursor-layer" aria-hidden="true">
    {Object.values(cursors).map((cursor) => <div className="remote-cursor" key={cursor.user_id}
      style={{ left: `${cursor.x * 100}%`, top: `${cursor.y * 100}%`, '--cursor-color': cursor.color }}>
      <svg viewBox="0 0 20 24"><path d="M2 1 18 13l-7 1-4 7L2 1Z" /></svg>
      <span>{cursor.display_name}</span>
    </div>)}
  </div>;
}

export function CollaborationPanel({
  open,
  onClose,
  currentUserId,
  currentUser,
  connected,
  tasks = [],
  deliverables = [],
  notes = [],
  contacts = [],
  nodes = [],
  selectedNodeId = null,
  onCreateTask = () => {},
  onUpdateTask = () => {},
  onCreateDeliverable = () => {},
  onUpdateDeliverable = () => {},
  onSendNote = () => {},
  onResolveNote = () => {},
  onSelectNode = () => {},
  canManage = false,
  canComment = false,
}) {
  const [noteDraft, setNoteDraft] = useState('');
  const [noteNodeId, setNoteNodeId] = useState('');
  const [taskDraft, setTaskDraft] = useState({
    title: '', details: '', assignee_id: '', priority: 'medium', due_date: '',
    deliverable_id: '', node_id: '',
  });
  const [tab, setTab] = useState('tasks');
  const [showResolved, setShowResolved] = useState(false);
  const [showCompleted, setShowCompleted] = useState(false);

  useEffect(() => {
    if (open && selectedNodeId) setNoteNodeId(selectedNodeId);
  }, [open, selectedNodeId]);

  const mentionMatch = noteDraft.match(/(?:^|\s)@([a-z0-9._-]*)$/i);
  const mentionQuery = mentionMatch?.[1]?.toLowerCase();
  const mentionSuggestions = mentionMatch ? contacts.filter((contact) => {
    const user = contact.user || contact;
    return user.id !== currentUserId && (!mentionQuery
      || user.handle.toLowerCase().includes(mentionQuery)
      || user.display_name.toLowerCase().includes(mentionQuery));
  }).slice(0, 5) : [];

  const addMention = (contact) => {
    const user = contact.user || contact;
    setNoteDraft((current) => current.replace(/(?:^|\s)@[a-z0-9._-]*$/i, (match) => {
      const prefix = match.startsWith(' ') ? ' ' : '';
      return `${prefix}@${user.handle} `;
    }));
  };

  const submitNote = (event) => {
    event.preventDefault();
    const body = noteDraft.trim();
    if (!body || !connected) return;
    const mentionedUserIds = contacts.map((contact) => contact.user || contact)
      .filter((user) => body.toLowerCase().includes(`@${user.handle.toLowerCase()}`))
      .map((user) => user.id);
    onSendNote(body, mentionedUserIds, noteNodeId || null);
    setNoteDraft('');
    setNoteNodeId('');
  };

  const visibleNotes = notes.filter((note) => showResolved || !note.resolved);
  const unresolvedCount = notes.filter((note) => !note.resolved).length;
  const visibleTasks = tasks.filter((task) => showCompleted || task.status !== 'done');
  const openTaskCount = tasks.filter((task) => task.status !== 'done').length;
  const openDeliverableCount = deliverables.filter((item) => item.status !== 'done').length;
  const nodeLabels = Object.fromEntries(nodes.map((node) => [node.id, node.data?.label || node.id]));
  const deliverableLabels = Object.fromEntries(deliverables.map((item) => [item.id, item.title]));
  const taskAssignees = [
    { user: { ...currentUser, color: currentUser.color || '#5B4BE7', handle: 'me' } },
    ...contacts.filter((contact) => (contact.user || contact).id !== currentUserId),
  ];

  const submitTask = (event) => {
    event.preventDefault();
    if (!taskDraft.title.trim() || !connected) return;
    onCreateTask({ ...taskDraft, title: taskDraft.title.trim(), details: taskDraft.details.trim() });
    setTaskDraft({
      title: '', details: '', assignee_id: '', priority: 'medium', due_date: '',
      deliverable_id: '', node_id: '',
    });
  };

  if (!open) return null;
  return <aside className="collaboration-chat" aria-label="Workflow plan, tasks and notes">
    <header><div><p className="eyebrow">This workflow</p><h2>Delivery plan</h2></div>
      <button className="icon-button" aria-label="Close collaboration panel" onClick={onClose}>×</button></header>
    <nav className="collaboration-tabs" aria-label="Workflow collaboration sections">
      <button className={tab === 'tasks' ? 'active' : ''} onClick={() => setTab('tasks')}>Tasks<span>{openTaskCount}</span></button>
      <button className={tab === 'plan' ? 'active' : ''} onClick={() => setTab('plan')}>Plan<span>{openDeliverableCount}</span></button>
      <button className={tab === 'notes' ? 'active' : ''} onClick={() => setTab('notes')}>Notes<span>{unresolvedCount}</span></button>
    </nav>

    {tab === 'tasks' ? <>
      <div className="notes-toolbar"><span>{openTaskCount} open {openTaskCount === 1 ? 'task' : 'tasks'}</span>
        <label><input type="checkbox" checked={showCompleted} onChange={(event) => setShowCompleted(event.target.checked)} /> Show completed</label></div>
      <div className="flowchart-tasks">
        {visibleTasks.length === 0 && <div className="chat-empty"><span>✓</span><strong>No open tasks</strong><p>Turn decisions and follow-ups into assigned work.</p></div>}
        {visibleTasks.map((task) => <article className={`flowchart-task ${task.status === 'done' ? 'completed' : ''}`} key={task.id}>
          <div className="task-heading"><span className={`task-priority ${task.priority}`}>{task.priority}</span>
            <time>{task.due_date ? `Due ${new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(`${task.due_date}T12:00:00`))}` : 'No due date'}</time></div>
          <strong>{task.title}</strong>
          {task.details && <p>{task.details}</p>}
          {(task.deliverable_id || task.node_id) && <div className="task-links">
            {task.deliverable_id && <span>◎ {deliverableLabels[task.deliverable_id] || 'Deliverable'}</span>}
            {task.node_id && <button onClick={() => onSelectNode(task.node_id)}>↳ {nodeLabels[task.node_id] || 'Workflow step'}</button>}
          </div>}
          <div className="task-footer"><span>{task.assignee
            ? <><span className="chat-avatar" style={{ '--avatar-color': task.assignee.color }}>{initials(task.assignee.display_name)}</span>{task.assignee.display_name}</>
            : 'Unassigned'}</span>
            <select aria-label={`Status for ${task.title}`} value={task.status}
              disabled={!canManage || !connected}
              onChange={(event) => onUpdateTask(task.id, event.target.value)}>
              <option value="todo">To do</option><option value="in_progress">In progress</option><option value="done">Done</option>
            </select></div>
        </article>)}
      </div>
      {canManage && <form className="task-composer" onSubmit={submitTask}>
        <input aria-label="Task title" maxLength="160" value={taskDraft.title}
          onChange={(event) => setTaskDraft((current) => ({ ...current, title: event.target.value }))}
          placeholder={connected ? 'Add a task' : 'Waiting for live connection…'} />
        <textarea aria-label="Task details" maxLength="1000" value={taskDraft.details}
          onChange={(event) => setTaskDraft((current) => ({ ...current, details: event.target.value }))}
          placeholder="Details (optional)" />
        <div className="task-fields"><UserSelect label="Assign" ariaLabel="Task assignee"
          users={taskAssignees.map(({ user }) => user)} value={taskDraft.assignee_id}
          onChange={(assigneeId) => setTaskDraft((current) => ({ ...current, assignee_id: assigneeId }))}
          emptyLabel="Unassigned" />
          <label>Priority<select aria-label="Task priority" value={taskDraft.priority}
            onChange={(event) => setTaskDraft((current) => ({ ...current, priority: event.target.value }))}>
            <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
          <label>Due<input aria-label="Task due date" type="date" value={taskDraft.due_date}
            onChange={(event) => setTaskDraft((current) => ({ ...current, due_date: event.target.value }))} /></label>
          <label className="task-field-wide">Deliverable<select aria-label="Task deliverable" value={taskDraft.deliverable_id}
            onChange={(event) => setTaskDraft((current) => ({ ...current, deliverable_id: event.target.value }))}>
            <option value="">No deliverable</option>{deliverables.map((item) => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label>
          <label>Workflow step<select aria-label="Task workflow step" value={taskDraft.node_id}
            onChange={(event) => setTaskDraft((current) => ({ ...current, node_id: event.target.value }))}>
            <option value="">None</option>{nodes.map((node) => <option value={node.id} key={node.id}>{node.data?.label || node.id}</option>)}</select></label></div>
        <div><small>Assignees receive a notification</small><button className="button primary" disabled={!taskDraft.title.trim() || !connected}>Add task</button></div>
      </form>}
    </> : tab === 'plan' ? <ProjectPlan deliverables={deliverables} tasks={tasks} nodes={nodes}
      contacts={contacts} currentUser={currentUser} currentUserId={currentUserId} connected={connected}
      canManage={canManage}
      onCreateDeliverable={onCreateDeliverable} onUpdateDeliverable={onUpdateDeliverable}
      onSelectNode={onSelectNode} /> : <>
      <div className="notes-toolbar"><span>{unresolvedCount} open {unresolvedCount === 1 ? 'note' : 'notes'}</span>
        <label><input type="checkbox" checked={showResolved} onChange={(event) => setShowResolved(event.target.checked)} /> Show resolved</label></div>
      <div className="flowchart-notes">
        {visibleNotes.length === 0 && <div className="chat-empty"><span>✎</span><strong>No open notes</strong><p>Add context, assign a follow-up, or mention a teammate.</p></div>}
        {visibleNotes.map((note) => <article className={`flowchart-note ${note.resolved ? 'resolved' : ''}`} key={note.id}>
          <div className="note-meta"><span className="chat-avatar" style={{ '--avatar-color': note.author.color }}>{initials(note.author.display_name)}</span>
            <span><strong>{note.author.display_name}</strong><time>{timeLabel(note.created_at)}</time></span>
            {!note.resolved && (canManage || canComment) && <button onClick={() => onResolveNote(note.id, true)}>Resolve</button>}
            {note.resolved && (canManage || canComment) && <button onClick={() => onResolveNote(note.id, false)}>Reopen</button>}</div>
          <p><MentionText>{note.body}</MentionText></p>
          {note.node_id && <button className="note-node-link" onClick={() => onSelectNode(note.node_id)}>↳ {nodeLabels[note.node_id] || 'Workflow step'}</button>}
        </article>)}
      </div>
      {(canManage || canComment) && <form className="note-composer" onSubmit={submitNote}>
        <div className="note-target"><label>Attach to<select aria-label="Attach note to workflow step" value={noteNodeId}
          onChange={(event) => setNoteNodeId(event.target.value)}><option value="">Whole workflow</option>
          {nodes.map((node) => <option value={node.id} key={node.id}>{node.data?.label || node.id}</option>)}</select></label></div>
        <div className="mention-composer"><textarea aria-label="Add a workflow note" maxLength="2000" value={noteDraft}
          onChange={(event) => setNoteDraft(event.target.value)} placeholder={connected ? 'Add a note… Type @ to notify a contact' : 'Waiting for live connection…'} />
          {mentionSuggestions.length > 0 && <div className="mention-suggestions" role="listbox" aria-label="Mention a contact">
            {mentionSuggestions.map((contact) => {
              const user = contact.user || contact;
              return <button type="button" role="option" aria-selected="false" key={user.id} onClick={() => addMention(contact)}>
                <span className="chat-avatar" style={{ '--avatar-color': user.color }}>{initials(user.display_name)}</span>
                <span><strong>{user.display_name}</strong><small>@{user.handle}</small></span>
              </button>;
            })}</div>}
        </div>
        <div><small>{noteDraft.length}/2000 · @mentions notify contacts</small><button className="button primary" disabled={!noteDraft.trim() || !connected}>Add note</button></div>
      </form>}
    </>}
  </aside>;
}
