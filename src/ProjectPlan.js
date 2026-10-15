import React, { useMemo, useState } from 'react';
import { UserSelect } from './UserPicker';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function dateKey(value) {
  const date = value instanceof Date ? value : new Date(`${value}T12:00:00`);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatDate(value, options = { month: 'short', day: 'numeric' }) {
  if (!value) return 'No target date';
  return new Intl.DateTimeFormat(undefined, options).format(new Date(`${value}T12:00:00`));
}

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function deliverableProgress(deliverable, tasks) {
  const linked = tasks.filter((task) => task.deliverable_id === deliverable.id);
  if (linked.length) return Math.round((linked.filter((task) => task.status === 'done').length / linked.length) * 100);
  return deliverable.status === 'done' ? 100 : 0;
}

export default function ProjectPlan({
  deliverables = [],
  tasks = [],
  nodes = [],
  contacts = [],
  currentUser,
  connected,
  canManage = false,
  onCreateDeliverable = () => {},
  onUpdateDeliverable = () => {},
  onSelectNode = () => {},
}) {
  const today = useMemo(() => new Date(), []);
  const todayKey = dateKey(today);
  const [month, setMonth] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
  const [selectedDate, setSelectedDate] = useState(todayKey);
  const [draft, setDraft] = useState({
    title: '', description: '', owner_id: '', target_date: '', node_id: '',
  });

  const members = useMemo(() => Array.from(new Map([
    { ...currentUser, color: currentUser.color || '#5B4BE7' },
    ...contacts.map((contact) => contact.user || contact),
  ].filter((member) => member?.id).map((member) => [member.id, member])).values()), [contacts, currentUser]);

  const nodeLabels = useMemo(
    () => Object.fromEntries(nodes.map((node) => [node.id, node.data?.label || node.id])),
    [nodes]
  );
  const calendarItems = useMemo(() => [
    ...deliverables.filter((item) => item.target_date).map((item) => ({
      id: `deliverable-${item.id}`, date: item.target_date, type: 'deliverable', title: item.title,
      status: item.status,
    })),
    ...tasks.filter((item) => item.due_date).map((item) => ({
      id: `task-${item.id}`, date: item.due_date, type: 'task', title: item.title, status: item.status,
    })),
  ], [deliverables, tasks]);
  const itemsByDate = useMemo(() => calendarItems.reduce((result, item) => ({
    ...result, [item.date]: [...(result[item.date] || []), item],
  }), {}), [calendarItems]);

  const firstCalendarDate = new Date(month.getFullYear(), month.getMonth(), 1 - new Date(
    month.getFullYear(), month.getMonth(), 1
  ).getDay());
  const calendarDays = Array.from({ length: 42 }, (_, index) => new Date(
    firstCalendarDate.getFullYear(), firstCalendarDate.getMonth(), firstCalendarDate.getDate() + index
  ));
  const selectedItems = itemsByDate[selectedDate] || [];
  const deliverableProgressValues = deliverables.map((item) => deliverableProgress(item, tasks));
  const overallProgress = deliverables.length
    ? Math.round(deliverableProgressValues.reduce((total, value) => total + value, 0) / deliverables.length)
    : tasks.length ? Math.round((tasks.filter((task) => task.status === 'done').length / tasks.length) * 100) : 0;
  const blockedCount = deliverables.filter((item) => item.status === 'blocked').length;
  const overdueCount = calendarItems.filter((item) => item.date < todayKey && item.status !== 'done').length;

  const submit = (event) => {
    event.preventDefault();
    if (!draft.title.trim() || !connected) return;
    onCreateDeliverable({
      ...draft,
      title: draft.title.trim(),
      description: draft.description.trim(),
    });
    setDraft({ title: '', description: '', owner_id: '', target_date: '', node_id: '' });
  };

  return <div className="project-plan">
    <section className="plan-overview">
      <div className="plan-overview-heading"><span><strong>{overallProgress}%</strong><small>Plan progress</small></span>
        <span><strong>{deliverables.filter((item) => item.status === 'done').length}/{deliverables.length}</strong><small>Deliverables</small></span>
        <span className={blockedCount ? 'attention' : ''}><strong>{blockedCount}</strong><small>Blocked</small></span>
        <span className={overdueCount ? 'attention' : ''}><strong>{overdueCount}</strong><small>Overdue</small></span></div>
      <div className="plan-progress-track" aria-label={`${overallProgress}% plan progress`}><span style={{ width: `${overallProgress}%` }} /></div>
    </section>

    <section className="plan-calendar">
      <header><button aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>‹</button>
        <strong>{new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(month)}</strong>
        <button aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>›</button></header>
      <div className="calendar-grid calendar-weekdays">{WEEKDAYS.map((day) => <span key={day}>{day}</span>)}</div>
      <div className="calendar-grid calendar-days">{calendarDays.map((day) => {
        const key = dateKey(day);
        const items = itemsByDate[key] || [];
        return <button className={`${day.getMonth() === month.getMonth() ? '' : 'outside'} ${key === todayKey ? 'today' : ''} ${key === selectedDate ? 'selected' : ''}`}
          aria-label={`${formatDate(key, { month: 'long', day: 'numeric', year: 'numeric' })}${items.length ? `, ${items.length} planned ${items.length === 1 ? 'item' : 'items'}` : ''}`}
          onClick={() => setSelectedDate(key)} key={key}><span>{day.getDate()}</span>
          {items.length > 0 && <i>{items.slice(0, 3).map((item) => <b className={item.type} key={item.id} />)}</i>}</button>;
      })}</div>
      <div className="calendar-agenda"><strong>{formatDate(selectedDate, { weekday: 'short', month: 'long', day: 'numeric' })}</strong>
        {selectedItems.length === 0 ? <span>Nothing scheduled</span> : selectedItems.map((item) =>
          <span key={item.id}><i className={item.type} /> <b>{item.title}</b><small>{item.type}</small></span>)}</div>
    </section>

    <section className="deliverables-section"><div className="deliverables-heading"><div><strong>Deliverables</strong><span>Outcomes this workflow must produce</span></div><b>{deliverables.length}</b></div>
      {deliverables.length === 0 && <div className="plan-empty"><span>◎</span><strong>No deliverables yet</strong><p>Define the outcomes, then connect tasks and workflow steps.</p></div>}
      <div className="deliverable-list">{deliverables.map((deliverable) => {
        const progress = deliverableProgress(deliverable, tasks);
        const linkedTasks = tasks.filter((task) => task.deliverable_id === deliverable.id);
        return <article className={`deliverable-card ${deliverable.status}`} key={deliverable.id}>
          <header><span><small>{deliverable.target_date ? `Target ${formatDate(deliverable.target_date)}` : 'No target date'}</small><strong>{deliverable.title}</strong></span>
            <select aria-label={`Status for deliverable ${deliverable.title}`} value={deliverable.status}
              disabled={!canManage || !connected}
              onChange={(event) => onUpdateDeliverable(deliverable.id, event.target.value)}>
              <option value="planned">Planned</option><option value="in_progress">In progress</option>
              <option value="blocked">Blocked</option><option value="done">Done</option>
            </select></header>
          {deliverable.description && <p>{deliverable.description}</p>}
          <div className="deliverable-progress"><span><i style={{ width: `${progress}%` }} /></span><b>{progress}%</b></div>
          <footer><span>{deliverable.owner ? <><i className="project-member-avatar" style={{ '--avatar-color': deliverable.owner.color }}>{initials(deliverable.owner.display_name)}</i>{deliverable.owner.display_name}</> : 'No owner'}</span>
            <span>{linkedTasks.length} {linkedTasks.length === 1 ? 'task' : 'tasks'}</span>
            {deliverable.node_id && <button onClick={() => onSelectNode(deliverable.node_id)}>↳ {nodeLabels[deliverable.node_id] || 'Workflow step'}</button>}</footer>
        </article>;
      })}</div>
    </section>

    {canManage && <form className="deliverable-composer" onSubmit={submit}>
      <strong>Add deliverable</strong>
      <input aria-label="Deliverable title" maxLength="160" value={draft.title}
        onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
        placeholder={connected ? 'Outcome to achieve' : 'Waiting for live connection…'} />
      <textarea aria-label="Deliverable description" maxLength="2000" value={draft.description}
        onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
        placeholder="Definition of done (optional)" />
      <div><UserSelect label="Owner" ariaLabel="Deliverable owner" users={members} value={draft.owner_id}
        onChange={(ownerId) => setDraft((current) => ({ ...current, owner_id: ownerId }))} emptyLabel="No owner" />
        <label>Target<input aria-label="Deliverable target date" type="date" value={draft.target_date}
          onChange={(event) => setDraft((current) => ({ ...current, target_date: event.target.value }))} /></label>
        <label>Workflow step<select aria-label="Deliverable workflow step" value={draft.node_id}
          onChange={(event) => setDraft((current) => ({ ...current, node_id: event.target.value }))}>
          <option value="">Whole workflow</option>{nodes.map((node) => <option key={node.id} value={node.id}>{node.data?.label || node.id}</option>)}</select></label></div>
      <footer><small>Owners receive a notification</small><button className="button primary" disabled={!draft.title.trim() || !connected}>Add deliverable</button></footer>
    </form>}
  </div>;
}
