import React, { useEffect, useMemo, useRef, useState } from 'react';
import WorkspaceTopNav from './WorkspaceTopNav';
import { UserSelect } from './UserPicker';
import { saveWorkspaceView } from './enterpriseService';
import {
  bulkUpdateWorkItems, createRelease, createSprint, createWorkComment, createWorkItem, createWorkLink,
  deleteWorkItem, duplicateWorkItem, followWorkItem, getWorkOverview, mergeWorkItems, splitWorkItem,
  reactToWorkComment, updateRelease, updateSprint, updateWorkItem, updateWorkWorkflow,
} from './workService';

const DEFAULT_COLUMNS = [
  { id: 'backlog', label: 'Backlog', hint: 'Ideas and unscheduled work', color: '#8792A3', category: 'queue', progress: 0, wip_limit: null },
  { id: 'selected', label: 'Ready', hint: 'Committed and ready to start', color: '#4B84D8', category: 'queue', progress: 10, wip_limit: null },
  { id: 'in_progress', label: 'In progress', hint: 'Work actively underway', color: '#E09A34', category: 'active', progress: 40, wip_limit: 8 },
  { id: 'ready_for_qa', label: 'Ready for QA', hint: 'Implementation ready to test', color: '#B46BD7', category: 'qa', progress: 65, wip_limit: 6 },
  { id: 'in_qa', label: 'In QA', hint: 'Testing and verification', color: '#7A62D5', category: 'qa', progress: 80, wip_limit: 5 },
  { id: 'review', label: 'Review / approval', hint: 'Final validation or sign-off', color: '#536ED8', category: 'review', progress: 90, wip_limit: 5 },
  { id: 'blocked', label: 'Blocked', hint: 'Waiting on a dependency', color: '#D3586C', category: 'blocked', progress: 40, wip_limit: null },
  { id: 'done', label: 'Done', hint: 'Delivered and verified', color: '#2A9A70', category: 'done', progress: 100, wip_limit: null },
];
const DEFAULT_ITEM_TYPES = [
  { id: 'initiative', label: 'Initiative', icon: '◆', parent_types: [], child_type: 'epic' },
  { id: 'epic', label: 'Epic', icon: '⚡', parent_types: ['initiative'], child_type: 'story' },
  { id: 'feature', label: 'Feature', icon: '◈', parent_types: ['initiative', 'epic'], child_type: 'story' },
  { id: 'story', label: 'Story', icon: '▤', parent_types: ['epic', 'feature'], child_type: 'subtask' },
  { id: 'subtask', label: 'Subtask', icon: '↳', parent_types: ['story', 'task'], child_type: null },
  { id: 'task', label: 'Task', icon: '✓', parent_types: ['epic', 'story'], child_type: 'subtask' },
  { id: 'bug', label: 'Defect', icon: '◆', parent_types: ['epic', 'story'], child_type: null },
  { id: 'spike', label: 'Spike', icon: '⌁', parent_types: ['epic', 'story'], child_type: null },
  { id: 'improvement', label: 'Improvement', icon: '↑', parent_types: ['epic', 'story'], child_type: 'subtask' },
  { id: 'technical_debt', label: 'Technical debt', icon: '⚙', parent_types: ['epic', 'story'], child_type: 'subtask' },
  { id: 'milestone', label: 'Milestone', icon: '◇', parent_types: [], child_type: null },
  { id: 'request', label: 'Request', icon: '→', parent_types: [], child_type: null },
  { id: 'deliverable', label: 'Deliverable', icon: '□', parent_types: [], child_type: null },
  { id: 'approval', label: 'Approval', icon: '◎', parent_types: [], child_type: null },
];
const PRIORITIES = ['lowest', 'low', 'medium', 'high', 'highest'];
const EMPTY_OVERVIEW = { items: [], sprints: [], releases: [], members: [], projects: [], saved_views: [], current_user_role: 'basic', workflow: { columns: DEFAULT_COLUMNS, item_types: DEFAULT_ITEM_TYPES } };
const EMPTY_ITEM = {
  summary: '', item_type: 'task', description: '', acceptance_criteria: '', status: 'backlog',
  priority: 'medium', assignee_id: '', sprint_id: '', release_id: '', project_id: '',
  owner_id: '', severity: 'none', component: '', team: '', actual_minutes: '',
  parent_id: '', node_id: '', story_points: '', estimate_minutes: '', labels: '', checklist: [], watcher_ids: [], archived: false,
  start_date: '', due_date: '', custom_fields: {},
};

function RichTextEditor({ label, value, onChange, placeholder }) {
  const apply = (prefix, suffix = prefix) => {
    const field = document.activeElement;
    const start = field?.selectionStart ?? value.length;
    const end = field?.selectionEnd ?? value.length;
    onChange(`${value.slice(0, start)}${prefix}${value.slice(start, end)}${suffix}${value.slice(end)}`);
  };
  return <label className="rich-text-field">{label}<span className="rich-text-toolbar" aria-label={`${label} formatting`}>
    <button type="button" onClick={() => apply('**')}>Bold</button><button type="button" onClick={() => apply('_')}>Italic</button>
    <button type="button" onClick={() => apply('\n- ', '')}>List</button><button type="button" onClick={() => apply('`')}>Code</button>
  </span><textarea value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function RichText({ value }) {
  const parts = String(value || '').split(/(`[^`]+`|\*\*[^*]+\*\*|_[^_]+_)/g);
  return <p>{parts.map((part, index) => part.startsWith('`') && part.endsWith('`') ? <code key={index}>{part.slice(1, -1)}</code>
    : part.startsWith('**') && part.endsWith('**') ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part.startsWith('_') && part.endsWith('_') ? <em key={index}>{part.slice(1, -1)}</em> : part)}</p>;
}

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function displayDate(value) {
  if (!value) return 'No date';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    .format(new Date(`${value.slice(0, 10)}T12:00:00`));
}

function compactDate(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
    .format(new Date(`${value.slice(0, 10)}T12:00:00`));
}

function relativeTime(value) {
  const seconds = Math.max(1, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function points(items) {
  return items.reduce((sum, item) => sum + (item.story_points || 0), 0);
}

function workflowColumns(overview) {
  return overview.workflow?.columns?.length ? overview.workflow.columns : DEFAULT_COLUMNS;
}

function workflowItemTypes(overview) {
  return overview.workflow?.item_types?.length ? overview.workflow.item_types : DEFAULT_ITEM_TYPES;
}

function parentTypesFor(itemType, types) {
  return types.find((candidate) => candidate.id === itemType)?.parent_types || [];
}

function childTypeFor(item, types) {
  return types.find((candidate) => candidate.id === item.item_type)?.child_type || null;
}

function columnFor(status, columns) {
  return columns.find((column) => column.id === status) || { id: status, label: status?.replaceAll('_', ' ') || 'Unknown', color: '#8792A3', category: 'queue', progress: 0 };
}

function isDone(item, columns) {
  return columnFor(item.status, columns).category === 'done';
}

const PRIORITY_WEIGHT = { highest: 5, high: 4, medium: 3, low: 2, lowest: 1 };

function tokenizeIssueQuery(query) {
  return (String(query || '').match(/(?:[^\s"]+|"[^"]*")+/g) || []).map((token) => token.replaceAll('"', ''));
}

function matchesIssueQuery(item, query, overview, user) {
  const columns = workflowColumns(overview);
  const sprint = overview.sprints.find((candidate) => candidate.id === item.sprint_id);
  const release = overview.releases.find((candidate) => candidate.id === item.release_id);
  const project = overview.projects.find((candidate) => candidate.id === item.project_id);
  const searchable = `${item.key} ${item.summary} ${item.description} ${item.acceptance_criteria} ${(item.labels || []).join(' ')} ${item.component || ''} ${item.team || ''}`.toLowerCase();
  return tokenizeIssueQuery(query).every((rawToken) => {
    const excluded = rawToken.startsWith('-');
    const token = excluded ? rawToken.slice(1) : rawToken;
    const separator = token.indexOf(':');
    const field = separator > 0 ? token.slice(0, separator).toLowerCase() : '';
    const value = (separator > 0 ? token.slice(separator + 1) : token).toLowerCase();
    let match;
    if (!field) match = searchable.includes(value);
    else if (field === 'status') match = [item.status, columnFor(item.status, columns).label].some((candidate) => candidate.toLowerCase().includes(value));
    else if (['type', 'issuetype'].includes(field)) match = item.item_type.toLowerCase().includes(value);
    else if (field === 'priority') match = item.priority.toLowerCase().includes(value);
    else if (field === 'assignee') match = value === 'me' ? item.assignee?.id === user.id : (item.assignee?.display_name || 'unassigned').toLowerCase().includes(value);
    else if (field === 'reporter') match = value === 'me' ? item.reporter?.id === user.id : (item.reporter?.display_name || '').toLowerCase().includes(value);
    else if (field === 'sprint') match = value === 'backlog' ? !item.sprint_id : value === 'active' ? sprint?.status === 'active' : (sprint?.name || '').toLowerCase().includes(value);
    else if (['release', 'fixversion'].includes(field)) match = (release?.name || '').toLowerCase().includes(value);
    else if (field === 'project') match = (project?.title || '').toLowerCase().includes(value);
    else if (field === 'label') match = (item.labels || []).some((label) => label.toLowerCase().includes(value));
    else if (field === 'component') match = (item.component || '').toLowerCase().includes(value);
    else if (field === 'team') match = (item.team || '').toLowerCase().includes(value);
    else if (field === 'is') {
      match = value === 'overdue' ? Boolean(item.due_date && !isDone(item, columns) && item.due_date < new Date().toISOString().slice(0, 10))
        : value === 'unassigned' ? !item.assignee : value === 'blocked' ? columnFor(item.status, columns).category === 'blocked'
          : value === 'archived' ? item.archived : false;
    } else match = searchable.includes(token.toLowerCase());
    return excluded ? !match : match;
  });
}

function itemProgress(item, items, columns) {
  const children = items.filter((candidate) => candidate.parent_id === item.id);
  const targets = children.length ? children : [item];
  const totalWeight = targets.reduce((sum, candidate) => sum + (candidate.story_points || 1), 0);
  return Math.round(targets.reduce((sum, candidate) => sum + columnFor(candidate.status, columns).progress * (candidate.story_points || 1), 0) / totalWeight);
}

function flowchartContext(item, overview) {
  const project = overview.projects.find((candidate) => candidate.id === item.project_id);
  const node = project?.nodes.find((candidate) => candidate.id === item.node_id);
  return project ? { project, node } : null;
}

function WorkAvatar({ member, small = false }) {
  if (!member) return <span className={`work-avatar ${small ? 'small' : ''} unassigned`}>?</span>;
  return <span className={`work-avatar ${small ? 'small' : ''}`} style={{ '--avatar-color': member.color }} title={member.display_name}>{initials(member.display_name)}</span>;
}

function TypeIcon({ type, itemTypes = DEFAULT_ITEM_TYPES }) {
  const config = itemTypes.find((candidate) => candidate.id === type);
  return <span className={`work-type ${type}`} title={config?.label || type}>{config?.icon || '✓'}</span>;
}

function WorkCard({ item, sprint, onOpen, onDragStart, canEdit = true, columns, itemTypes }) {
  const overdue = item.due_date && !isDone(item, columns) && item.due_date < new Date().toISOString().slice(0, 10);
  return <article className={`work-card priority-${item.priority}`} draggable={canEdit} onDragStart={(event) => { if (canEdit) onDragStart(event, item); }} onClick={() => onOpen(item.id)}>
    <div className="work-card-top"><span><TypeIcon type={item.item_type} itemTypes={itemTypes} />{item.key}</span><WorkAvatar member={item.assignee} small /></div>
    <h3>{item.summary}</h3>
    {item.labels.length > 0 && <div className="work-labels">{item.labels.slice(0, 3).map((label) => <span key={label}>{label}</span>)}</div>}
    <footer>
      <span className={`work-priority ${item.priority}`}><i />{item.priority}</span>
      <span>{item.story_points != null ? `${item.story_points} pt` : '—'}</span>
      {item.due_date && <span className={overdue ? 'overdue' : ''}>{compactDate(item.due_date)}</span>}
      {sprint && <span className="work-sprint-chip">{sprint.name}</span>}
    </footer>
  </article>;
}

function WorkItemForm({ overview, initial = EMPTY_ITEM, onCancel, onSubmit, saving, title = 'Create work item' }) {
  const [form, setForm] = useState(initial);
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  const project = overview.projects.find((candidate) => candidate.id === form.project_id);
  const customFieldDefinitions = project?.settings?.fields || [];
  const eligibleParents = overview.items.filter((item) => parentTypesFor(form.item_type, itemTypes).includes(item.item_type));
  const set = (name, value) => setForm((current) => ({ ...current, [name]: value }));
  const setItemType = (itemType) => setForm((current) => {
    const currentParent = overview.items.find((item) => item.id === current.parent_id);
    return {
      ...current, item_type: itemType,
      parent_id: currentParent && parentTypesFor(itemType, itemTypes).includes(currentParent.item_type) ? current.parent_id : '',
    };
  });
  const submit = (event) => {
    event.preventDefault();
    onSubmit({
      ...form,
      assignee_id: form.assignee_id || null, owner_id: form.owner_id || null,
      sprint_id: form.sprint_id || null,
      release_id: form.release_id || null, project_id: form.project_id || null,
      parent_id: form.parent_id || null, node_id: form.node_id || null,
      story_points: form.story_points === '' ? null : Number(form.story_points),
      estimate_minutes: form.estimate_minutes === '' ? null : Number(form.estimate_minutes),
      actual_minutes: form.actual_minutes === '' ? null : Number(form.actual_minutes),
      labels: typeof form.labels === 'string' ? form.labels.split(',').map((label) => label.trim()).filter(Boolean) : form.labels,
      start_date: form.start_date || null, due_date: form.due_date || null,
      custom_fields: form.custom_fields || {},
    });
  };
  return <form className="work-form" onSubmit={submit}>
    <header><div><p className="eyebrow">Plan the outcome</p><h2>{title}</h2></div><button type="button" className="icon-button" onClick={onCancel} aria-label="Close">×</button></header>
    <label className="work-form-summary">Summary<input autoFocus required maxLength="180" value={form.summary} onChange={(event) => set('summary', event.target.value)} placeholder="What needs to be accomplished?" /></label>
    <div className="work-form-grid">
      <label>Type<select value={form.item_type} onChange={(event) => setItemType(event.target.value)}>{itemTypes.map((type) => <option value={type.id} key={type.id}>{type.label}</option>)}</select></label>
      <label>Priority<select value={form.priority} onChange={(event) => set('priority', event.target.value)}>{PRIORITIES.map((priority) => <option key={priority}>{priority}</option>)}</select></label>
      <label>Status<select value={form.status} onChange={(event) => set('status', event.target.value)}>{columns.map((column) => <option value={column.id} key={column.id}>{column.label}</option>)}</select></label>
      <UserSelect label="Assignee" ariaLabel="Work item assignee" users={overview.members}
        value={form.assignee_id} onChange={(assigneeId) => set('assignee_id', assigneeId)} emptyLabel="Unassigned" />
      <UserSelect label="Owner" ariaLabel="Work item owner" users={overview.members}
        value={form.owner_id} onChange={(ownerId) => set('owner_id', ownerId)} emptyLabel="No accountable owner" />
      <label>Sprint<select value={form.sprint_id} onChange={(event) => set('sprint_id', event.target.value)}><option value="">Backlog / no sprint</option>{overview.sprints.filter((sprint) => !['completed', 'cancelled'].includes(sprint.status)).map((sprint) => <option value={sprint.id} key={sprint.id}>{sprint.name}</option>)}</select></label>
      <label>Release<select value={form.release_id} onChange={(event) => set('release_id', event.target.value)}><option value="">No release</option>{overview.releases.filter((release) => !['released', 'cancelled'].includes(release.status)).map((release) => <option value={release.id} key={release.id}>{release.name}</option>)}</select></label>
      <label>Story points<input type="number" min="0" value={form.story_points} onChange={(event) => set('story_points', event.target.value)} placeholder="5" /></label>
      <label>Estimate (minutes)<input type="number" min="0" value={form.estimate_minutes} onChange={(event) => set('estimate_minutes', event.target.value)} placeholder="120" /></label>
      <label>Actual (minutes)<input type="number" min="0" value={form.actual_minutes} onChange={(event) => set('actual_minutes', event.target.value)} placeholder="90" /></label>
      <label>Severity<select value={form.severity} onChange={(event) => set('severity', event.target.value)}><option value="none">None</option><option value="minor">Minor</option><option value="major">Major</option><option value="critical">Critical</option><option value="blocker">Blocker</option></select></label>
      <label>Component<input maxLength="120" value={form.component} onChange={(event) => set('component', event.target.value)} placeholder="Payments" /></label>
      <label>Team<input maxLength="120" value={form.team} onChange={(event) => set('team', event.target.value)} placeholder="Platform" /></label>
      <label>Start date<input type="date" value={form.start_date} onChange={(event) => set('start_date', event.target.value)} /></label>
      <label>Due date<input type="date" value={form.due_date} onChange={(event) => set('due_date', event.target.value)} /></label>
      <label>Parent<select aria-label="Parent work item" value={form.parent_id} required={form.item_type === 'subtask'} disabled={eligibleParents.length === 0} onChange={(event) => set('parent_id', event.target.value)}><option value="">{form.item_type === 'subtask' ? 'Choose a story or task' : 'No parent'}</option>{eligibleParents.map((item) => <option value={item.id} key={item.id}>{item.key} · {item.summary}</option>)}</select></label>
      <label>Labels<input value={form.labels} onChange={(event) => set('labels', event.target.value)} placeholder="customer, platform" /></label>
      <label>Workflow<select value={form.project_id} onChange={(event) => { set('project_id', event.target.value); set('node_id', ''); }}><option value="">No workflow link</option>{overview.projects.map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.title}</option>)}</select></label>
      <label>Workflow step<select value={form.node_id} disabled={!project} onChange={(event) => set('node_id', event.target.value)}><option value="">Whole workflow</option>{project?.nodes.map((node) => <option value={node.id} key={node.id}>{node.label}</option>)}</select></label>
      {customFieldDefinitions.map((field) => <label key={field.id || field.name}>{field.name || field.label}
        {field.type === 'select' ? <select value={form.custom_fields?.[field.id] || ''} onChange={(event) => set('custom_fields', { ...(form.custom_fields || {}), [field.id]: event.target.value })}><option value="">Not set</option>{(field.options || []).map((option) => <option key={option.value || option} value={option.value || option}>{option.label || option}</option>)}</select>
          : <input type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'} value={form.custom_fields?.[field.id] || ''} onChange={(event) => set('custom_fields', { ...(form.custom_fields || {}), [field.id]: event.target.value })} />}</label>)}
    </div>
    <RichTextEditor label="Description" value={form.description} onChange={(value) => set('description', value)} placeholder="Context, constraints, and expected outcome" />
    <RichTextEditor label="Acceptance criteria" value={form.acceptance_criteria} onChange={(value) => set('acceptance_criteria', value)} placeholder="What must be true for this to be done?" />
    <footer><button type="button" className="button secondary" onClick={onCancel}>Cancel</button><button className="button primary" disabled={saving || !form.summary.trim() || (form.item_type === 'subtask' && !form.parent_id)}>{saving ? 'Saving…' : 'Save work item'}</button></footer>
  </form>;
}

function ItemDrawer({ item, overview, user, onClose, onPatch, onRefresh, onOpenFlowchart, onSchedule, onCreateChild, onDelete, onDuplicate, onFollow, onSplit, onMerge }) {
  const [comment, setComment] = useState('');
  const [linkTarget, setLinkTarget] = useState('');
  const [linkType, setLinkType] = useState('blocks');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [checklistTitle, setChecklistTitle] = useState('');
  const [replyTo, setReplyTo] = useState(null);
  const [attachment, setAttachment] = useState({ name: '', url: '' });
  const [copiedLink, setCopiedLink] = useState(false);
  const project = overview.projects.find((candidate) => candidate.id === item.project_id);
  const canEdit = user.role === 'admin' || [item.reporter.id, item.assignee?.id].includes(user.id);
  const sprint = overview.sprints.find((candidate) => candidate.id === item.sprint_id);
  const release = overview.releases.find((candidate) => candidate.id === item.release_id);
  const parent = overview.items.find((candidate) => candidate.id === item.parent_id);
  const children = overview.items.filter((candidate) => candidate.parent_id === item.id);
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  const nextChildType = childTypeFor(item, itemTypes);
  const nextChildLabel = itemTypes.find((type) => type.id === nextChildType)?.label || nextChildType;
  const linkItems = item.links.map((link) => ({ link, other: overview.items.find((candidate) => candidate.id === (link.source_id === item.id ? link.target_id : link.source_id)) })).filter(({ other }) => other);
  const isFollowing = (item.watcher_ids || []).includes(user.id);
  const patch = async (changes) => {
    setError('');
    try { await onPatch(item, changes); } catch (requestError) { setError(requestError.message); }
  };
  const sendComment = async (event) => {
    event.preventDefault();
    if (!comment.trim()) return;
    setBusy(true); setError('');
    try { await createWorkComment(item.id, comment, replyTo?.id || null, attachment.name && attachment.url ? [attachment] : []); setComment(''); setReplyTo(null); setAttachment({ name: '', url: '' }); await onRefresh(item.id); }
    catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  const addLink = async (event) => {
    event.preventDefault();
    if (!linkTarget) return;
    setBusy(true); setError('');
    try { await createWorkLink(item.id, { target_id: linkTarget, link_type: linkType }); setLinkTarget(''); await onRefresh(item.id); }
    catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };
  return <div className="work-drawer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="work-drawer">
      <header><div><span><TypeIcon type={item.item_type} itemTypes={itemTypes} />{item.key}</span><h2>{item.summary}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close item">×</button></header>
      <div className="work-drawer-body">
        {error && <div className="notice error"><strong>Couldn’t save</strong><span>{error}</span></div>}
        <div className="work-item-actions">
          <button onClick={() => onFollow(item, !isFollowing)}>{isFollowing ? '★ Following' : '☆ Follow'}</button>
          <button onClick={() => onSchedule(item)}>◷ Schedule work</button>
          <button onClick={() => onDuplicate(item)}>⧉ Duplicate</button>
          {canEdit && <button onClick={() => onSplit(item)}>⑂ Split</button>}
          {canEdit && <button onClick={() => onMerge(item)}>⇥ Merge</button>}
          <button onClick={async () => { await navigator.clipboard?.writeText(`${window.location.origin}/work?item=${item.id}`); setCopiedLink(true); window.setTimeout(() => setCopiedLink(false), 1800); }}>{copiedLink ? '✓ Link copied' : '↗ Copy link'}</button>
          {canEdit && <button onClick={() => patch({ archived: !item.archived })}>{item.archived ? 'Restore' : 'Archive'}</button>}
        </div>
        <section className="work-detail-fields">
          <label>Type<select disabled={!canEdit} value={item.item_type} onChange={(event) => patch({ item_type: event.target.value })}>{itemTypes.map((type) => <option value={type.id} key={type.id}>{type.label}</option>)}</select></label>
          <label>Status<select disabled={!canEdit} value={item.status} onChange={(event) => patch({ status: event.target.value })}>{columns.map((column) => <option value={column.id} key={column.id}>{column.label}</option>)}</select></label>
          <label>Priority<select disabled={!canEdit} value={item.priority} onChange={(event) => patch({ priority: event.target.value })}>{PRIORITIES.map((priority) => <option key={priority}>{priority}</option>)}</select></label>
          <UserSelect label="Assignee" ariaLabel="Work item assignee" users={overview.members}
            disabled={!canEdit} value={item.assignee?.id || ''} onChange={(assigneeId) => patch({ assignee_id: assigneeId || null })}
            emptyLabel="Unassigned" />
          <UserSelect label="Owner" ariaLabel="Work item owner" users={overview.members}
            disabled={!canEdit} value={item.owner?.id || ''} onChange={(ownerId) => patch({ owner_id: ownerId || null })}
            emptyLabel="No accountable owner" />
          <label>Severity<select disabled={!canEdit} value={item.severity || 'none'} onChange={(event) => patch({ severity: event.target.value })}><option value="none">None</option><option value="minor">Minor</option><option value="major">Major</option><option value="critical">Critical</option><option value="blocker">Blocker</option></select></label>
          <label>Sprint<select disabled={!canEdit} value={item.sprint_id || ''} onChange={(event) => patch({ sprint_id: event.target.value || null })}><option value="">No sprint</option>{overview.sprints.map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.name}</option>)}</select></label>
          <label>Release<select disabled={!canEdit} value={item.release_id || ''} onChange={(event) => patch({ release_id: event.target.value || null })}><option value="">No release</option>{overview.releases.map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.name}</option>)}</select></label>
          <label>Points<input disabled={!canEdit} type="number" min="0" value={item.story_points ?? ''} onChange={(event) => patch({ story_points: event.target.value === '' ? null : Number(event.target.value) })} /></label>
          <label>Actual minutes<input disabled={!canEdit} type="number" min="0" value={item.actual_minutes ?? ''} onChange={(event) => patch({ actual_minutes: event.target.value === '' ? null : Number(event.target.value) })} /></label>
          <label>Component<input disabled={!canEdit} defaultValue={item.component || ''} onBlur={(event) => { if (event.target.value !== (item.component || '')) patch({ component: event.target.value }); }} /></label>
          <label>Team<input disabled={!canEdit} defaultValue={item.team || ''} onBlur={(event) => { if (event.target.value !== (item.team || '')) patch({ team: event.target.value }); }} /></label>
          <label>Start<input disabled={!canEdit} type="date" value={item.start_date || ''} onChange={(event) => patch({ start_date: event.target.value || null })} /></label>
          <label>Due<input disabled={!canEdit} type="date" value={item.due_date || ''} onChange={(event) => patch({ due_date: event.target.value || null })} /></label>
        </section>
        <section className="work-detail-copy"><h3>Description</h3>{item.description ? <RichText value={item.description} /> : <p className="empty">No description yet.</p>}<h3>Acceptance criteria</h3>{item.acceptance_criteria ? <RichText value={item.acceptance_criteria} /> : <p className="empty">No acceptance criteria yet.</p>}</section>
        {Object.keys(item.custom_fields || {}).length > 0 && <section className="work-custom-fields"><h3>Custom fields</h3>{Object.entries(item.custom_fields).map(([key, value]) => <label key={key}>{key}<input disabled={!canEdit} value={value ?? ''} onChange={(event) => patch({ custom_fields: { ...(item.custom_fields || {}), [key]: event.target.value } })} /></label>)}</section>}
        <section className="work-checklist"><h3>Checklist <span>{(item.checklist || []).filter((entry) => entry.done).length}/{(item.checklist || []).length}</span></h3>
          {(item.checklist || []).map((entry) => <label key={entry.id}><input type="checkbox" checked={entry.done} disabled={!canEdit}
            onChange={() => patch({ checklist: item.checklist.map((candidate) => candidate.id === entry.id ? { ...candidate, done: !candidate.done } : candidate) })} /><span>{entry.title}</span>
            {canEdit && <button type="button" aria-label={`Remove ${entry.title}`} onClick={() => patch({ checklist: item.checklist.filter((candidate) => candidate.id !== entry.id) })}>×</button>}</label>)}
          {canEdit && <form onSubmit={(event) => { event.preventDefault(); const title = checklistTitle.trim(); if (!title) return; patch({ checklist: [...(item.checklist || []), { id: `check-${Date.now().toString(36)}`, title, done: false }] }); setChecklistTitle(''); }}><input maxLength="240" value={checklistTitle} onChange={(event) => setChecklistTitle(event.target.value)} placeholder="Add a checklist item" /><button disabled={!checklistTitle.trim()}>Add</button></form>}
        </section>
        {(project || sprint || release) && <section className="work-context"><h3>Planning context</h3>{sprint && <span><b>Sprint</b>{sprint.name}</span>}{release && <span><b>Release</b>{release.name}</span>}{project && <button onClick={() => onOpenFlowchart(project.id, item.node_id)}><b>Workflow</b>{project.title}{item.node_id ? ' · linked step' : ''} ↗</button>}</section>}
        {(parent || children.length > 0 || nextChildType) && <section className="work-hierarchy-context"><header><h3>Work breakdown</h3>{nextChildType && canEdit && <button type="button" onClick={() => onCreateChild(item)}>＋ Add {nextChildLabel}</button>}</header>
          {parent && <button type="button" className="work-hierarchy-parent" onClick={() => onRefresh(parent.id)}><span>Parent</span><strong><TypeIcon type={parent.item_type} itemTypes={itemTypes} />{parent.key} · {parent.summary}</strong></button>}
          {children.length > 0 && <div>{children.map((child) => <button type="button" key={child.id} onClick={() => onRefresh(child.id)}><TypeIcon type={child.item_type} itemTypes={itemTypes} /><span><strong>{child.key} · {child.summary}</strong><small>{columnFor(child.status, columns).label}</small></span></button>)}</div>}
          {!parent && children.length === 0 && <p>No child work yet. Break this item into smaller deliverables.</p>}
        </section>}
        <section className="work-dependencies"><h3>Dependencies</h3>{linkItems.map(({ link, other }) => <button key={link.id} onClick={() => onRefresh(other.id)}><span>{link.source_id === item.id ? link.link_type.replace('_', ' ') : `is ${link.link_type.replace('_', ' ')} by`}</span><strong>{other.key} · {other.summary}</strong></button>)}
          <form onSubmit={addLink}><select value={linkType} onChange={(event) => setLinkType(event.target.value)}><option value="blocks">blocks</option><option value="depends_on">depends on</option><option value="relates_to">relates to</option><option value="duplicates">duplicates</option><option value="supports">supports</option><option value="contributes_to">contributes to</option><option value="impacts">impacts</option></select><select value={linkTarget} onChange={(event) => setLinkTarget(event.target.value)}><option value="">Choose work item…</option>{overview.items.filter((candidate) => candidate.id !== item.id).map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.key} · {candidate.summary}</option>)}</select><button disabled={!linkTarget || busy}>Add</button></form>
        </section>
        <section className="work-comments"><h3>Comments <span>{item.comments.length}</span></h3>{item.comments.map((entry) => <article className={entry.parent_id ? 'comment-reply' : ''} key={entry.id}><WorkAvatar member={entry.author} small /><div><span><strong>{entry.author.display_name}</strong><time>{relativeTime(entry.created_at)}</time></span><RichText value={entry.body} />
          {(entry.attachments || []).length > 0 && <div className="work-comment-attachments">{entry.attachments.map((file) => <a key={file.url} href={file.url} target="_blank" rel="noreferrer">▣ {file.name}</a>)}</div>}
          <footer><button type="button" onClick={() => setReplyTo(entry)}>Reply</button>{['👍', '✅', '❤️'].map((emoji) => { const reaction = entry.reactions?.find((candidate) => candidate.emoji === emoji); return <button type="button" className={reaction?.reacted_by_me ? 'active' : ''} key={emoji} onClick={async () => { await reactToWorkComment(item.id, entry.id, emoji); await onRefresh(item.id); }}>{emoji}{reaction?.count ? ` ${reaction.count}` : ''}</button>; })}</footer></div></article>)}
          <form onSubmit={sendComment}>{replyTo && <div className="comment-replying">Replying to {replyTo.author.display_name}<button type="button" onClick={() => setReplyTo(null)}>×</button></div>}<RichTextEditor label="Comment" value={comment} onChange={setComment} placeholder="Add context or mention a teammate with @username…" /><details><summary>Attach link</summary><div className="comment-attachment-form"><input aria-label="Attachment name" value={attachment.name} onChange={(event) => setAttachment({ ...attachment, name: event.target.value })} placeholder="File name" /><input aria-label="Attachment URL" type="url" value={attachment.url} onChange={(event) => setAttachment({ ...attachment, url: event.target.value })} placeholder="https://…" /></div></details><button className="button primary" disabled={busy || !comment.trim()}>Comment</button></form>
        </section>
        <section className="work-activity"><h3>Activity</h3>{item.activity.map((entry) => <div key={entry.id}><span className="activity-dot" /><p><strong>{entry.actor.display_name}</strong> {entry.action.replace('_', ' ')} this item</p><time>{relativeTime(entry.created_at)}</time></div>)}</section>
        {user.role === 'admin' && <button className="work-delete" onClick={() => onDelete(item)}>Delete work item</button>}
      </div>
    </aside>
  </div>;
}

function IssuesView({ items, overview, user, onOpen, onBulkUpdate, onSaveFilter }) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('rank');
  const [selected, setSelected] = useState(() => new Set());
  const [bulkField, setBulkField] = useState('status');
  const [bulkValue, setBulkValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [visibleLimit, setVisibleLimit] = useState(50);
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  const issueViews = (overview.saved_views || []).filter((view) => view.config?.kind === 'issue_filter');
  const filtered = useMemo(() => items.filter((item) => matchesIssueQuery(item, query, overview, user)).sort((left, right) => {
    if (sort === 'updated') return new Date(right.updated_at) - new Date(left.updated_at);
    if (sort === 'priority') return (PRIORITY_WEIGHT[right.priority] || 0) - (PRIORITY_WEIGHT[left.priority] || 0) || left.rank - right.rank;
    if (sort === 'due') return (left.due_date || '9999').localeCompare(right.due_date || '9999');
    if (sort === 'key') return left.sequence_number - right.sequence_number;
    return left.rank - right.rank;
  }), [items, overview, query, sort, user]);
  const selectedItems = filtered.filter((item) => selected.has(item.id));
  const allSelected = filtered.length > 0 && filtered.every((item) => selected.has(item.id));
  const toggleAll = () => setSelected((current) => allSelected ? new Set([...current].filter((id) => !filtered.some((item) => item.id === id))) : new Set([...current, ...filtered.map((item) => item.id)]));
  const options = bulkField === 'status' ? columns.map((column) => [column.id, column.label])
    : bulkField === 'priority' ? PRIORITIES.map((priority) => [priority, priority])
      : bulkField === 'assignee_id' ? [['', 'Unassigned'], ...overview.members.map((member) => [member.id, member.display_name])]
        : bulkField === 'sprint_id' ? [['', 'Backlog / no sprint'], ...overview.sprints.map((sprint) => [sprint.id, sprint.name])]
          : [['', 'No release'], ...overview.releases.map((release) => [release.id, release.name])];
  const applyBulk = async () => {
    if (!selectedItems.length || (!bulkValue && ['status', 'priority'].includes(bulkField))) return;
    setBusy(true);
    try {
      await onBulkUpdate(selectedItems, { [bulkField]: bulkValue || null });
      setSelected(new Set());
    } finally { setBusy(false); }
  };
  const setIssueQuery = (value) => { setQuery(value); setVisibleLimit(50); };
  const addQuery = (token) => setIssueQuery(`${query} ${token}`.trim());
  return <div className="issues-view">
    <header className="work-view-heading"><div><p className="eyebrow">Issue navigator</p><h2>Search, triage, and update work</h2><p>Use smart filters across every project, sprint, release, workflow, team, and owner.</p></div><div className="issue-view-actions"><label>Saved filter<select value="" onChange={(event) => { const view = issueViews.find((candidate) => candidate.id === event.target.value); if (view) { setQuery(view.config.query || ''); setSort(view.config.sort || 'rank'); } }}><option value="">Choose…</option>{issueViews.map((view) => <option key={view.id} value={view.id}>{view.name}{view.shared ? ' · shared' : ''}</option>)}</select></label><button onClick={() => onSaveFilter(query, sort)}>☆ Save filter</button></div></header>
    <section className="issue-query-panel"><label><span>⌕</span><input aria-label="Issue query" value={query} onChange={(event) => setIssueQuery(event.target.value)} placeholder={'Try status:"In QA" assignee:me -label:blocked'} /></label><div className="issue-query-chips"><span>Quick filters</span><button onClick={() => addQuery('assignee:me')}>My issues</button><button onClick={() => addQuery('sprint:active')}>Active sprint</button><button onClick={() => addQuery('is:blocked')}>Blocked</button><button onClick={() => addQuery('is:overdue')}>Overdue</button><button onClick={() => addQuery('type:bug')}>Defects</button>{query && <button className="clear" onClick={() => setIssueQuery('')}>Clear</button>}</div><small>Fields: status, type, priority, assignee, reporter, sprint, release, project, label, component, team, and is:overdue/unassigned/blocked. Prefix a filter with − to exclude it.</small></section>
    {selectedItems.length > 0 && <section className="issue-bulk-bar"><strong>{selectedItems.length} selected</strong><label>Change<select value={bulkField} onChange={(event) => { setBulkField(event.target.value); setBulkValue(''); }}><option value="status">Status</option><option value="assignee_id">Assignee</option><option value="priority">Priority</option><option value="sprint_id">Sprint</option><option value="release_id">Release</option></select></label><select aria-label="Bulk value" value={bulkValue} onChange={(event) => setBulkValue(event.target.value)}>{options.map(([value, label]) => <option key={`${bulkField}-${value}`} value={value}>{label}</option>)}</select><button className="button primary" disabled={busy || (!bulkValue && ['status', 'priority'].includes(bulkField))} onClick={applyBulk}>{busy ? 'Updating…' : 'Apply'}</button><button onClick={() => setSelected(new Set())}>Cancel</button></section>}
    <section className="issue-table-shell" role="table" aria-label="Work issues"><header><span><b>{filtered.length}</b> issues{filtered.length > visibleLimit ? ` · showing ${visibleLimit}` : ''}</span><label>Sort by<select value={sort} onChange={(event) => setSort(event.target.value)}><option value="rank">Rank</option><option value="updated">Recently updated</option><option value="priority">Priority</option><option value="due">Due date</option><option value="key">Issue key</option></select></label></header><div className="issue-table issue-table-head" role="row"><input aria-label="Select all matching issues" type="checkbox" checked={allSelected} onChange={toggleAll} /><span role="columnheader">Type / key</span><span role="columnheader">Summary</span><span role="columnheader">Status</span><span role="columnheader">Priority</span><span role="columnheader">Assignee</span><span role="columnheader">Sprint / release</span><span role="columnheader">Due</span></div>{filtered.slice(0, visibleLimit).map((item) => {
      const sprint = overview.sprints.find((candidate) => candidate.id === item.sprint_id);
      const release = overview.releases.find((candidate) => candidate.id === item.release_id);
      return <div className={`issue-table issue-table-row ${selected.has(item.id) ? 'selected' : ''}`} role="row" key={item.id}><input aria-label={`Select ${item.key}`} type="checkbox" checked={selected.has(item.id)} onChange={() => setSelected((current) => { const next = new Set(current); if (next.has(item.id)) next.delete(item.id); else next.add(item.id); return next; })} /><button className="issue-key" role="cell" onClick={() => onOpen(item.id)}><TypeIcon type={item.item_type} itemTypes={itemTypes} /><b>{item.key}</b></button><button className="issue-summary" role="cell" onClick={() => onOpen(item.id)}><strong>{item.summary}</strong><small>{item.project_id ? overview.projects.find((project) => project.id === item.project_id)?.title : 'Workspace work'}{item.component ? ` · ${item.component}` : ''}</small></button><span role="cell" className="issue-status" style={{ '--status-color': columnFor(item.status, columns).color }}>{columnFor(item.status, columns).label}</span><span role="cell" className={`work-priority ${item.priority}`}><i />{item.priority}</span><span role="cell" className="issue-assignee"><WorkAvatar member={item.assignee} small />{item.assignee?.display_name || 'Unassigned'}</span><span role="cell" className="issue-plan">{sprint?.name || release?.name || 'Backlog'}{sprint && release ? <small>{release.name}</small> : null}</span><span role="cell" className={item.due_date && item.due_date < new Date().toISOString().slice(0, 10) && !isDone(item, columns) ? 'overdue' : ''}>{compactDate(item.due_date) || '—'}</span></div>;
    })}{filtered.length > visibleLimit && <button className="issue-load-more" onClick={() => setVisibleLimit((current) => Math.min(filtered.length, current + 50))}>Show {Math.min(50, filtered.length - visibleLimit)} more issues</button>}{filtered.length === 0 && <div className="work-empty"><span>⌕</span><strong>No issues match</strong><p>Adjust the query or clear a quick filter.</p></div>}</section>
  </div>;
}

function DependenciesView({ items, overview, onOpen }) {
  const columns = workflowColumns(overview);
  const links = [...new Map(items.flatMap((item) => item.links || []).map((link) => [link.id, link])).values()]
    .filter((link) => ['blocks', 'depends_on'].includes(link.link_type));
  const byId = new Map(items.map((item) => [item.id, item]));
  const edges = links.map((link) => link.link_type === 'blocks' ? [link.source_id, link.target_id, link] : [link.target_id, link.source_id, link])
    .filter(([source, target]) => byId.has(source) && byId.has(target));
  const adjacency = new Map();
  edges.forEach(([source, target]) => adjacency.set(source, [...(adjacency.get(source) || []), target]));
  const cyclicIds = new Set();
  const visiting = new Set();
  const visited = new Set();
  const walk = (id, trail = []) => {
    if (visiting.has(id)) { trail.slice(trail.indexOf(id)).forEach((candidate) => cyclicIds.add(candidate)); return; }
    if (visited.has(id)) return;
    visiting.add(id); (adjacency.get(id) || []).forEach((target) => walk(target, [...trail, id])); visiting.delete(id); visited.add(id);
  };
  items.forEach((item) => walk(item.id));
  const blockedIds = new Set(edges.map(([, target]) => target));
  const blocked = items.filter((item) => blockedIds.has(item.id) && !isDone(item, columns));
  const roots = items.filter((item) => (adjacency.get(item.id) || []).length > 0 && !blockedIds.has(item.id));
  return <div className="dependencies-view"><header className="work-view-heading"><div><p className="eyebrow">Dependency control</p><h2>Cross-project delivery paths</h2><p>See what blocks delivery, spot circular chains, and open any issue without losing context.</p></div></header><div className="dependency-kpis"><article><span>Blocking links</span><strong>{edges.length}</strong><small>Across visible work</small></article><article><span>Blocked work</span><strong>{blocked.length}</strong><small>Open items waiting upstream</small></article><article className={cyclicIds.size ? 'attention' : ''}><span>Circular dependencies</span><strong>{cyclicIds.size}</strong><small>{cyclicIds.size ? 'Resolve these chains' : 'No cycles detected'}</small></article><article><span>Delivery roots</span><strong>{roots.length}</strong><small>Items that unblock others</small></article></div>{cyclicIds.size > 0 && <section className="dependency-warning"><strong>⚠ Circular chain detected</strong><span>{[...cyclicIds].map((id) => byId.get(id)?.key).filter(Boolean).join(' → ')}</span></section>}<section className="dependency-map"><header><span>Upstream blocker</span><span>Relationship</span><span>Downstream work</span><span>Schedule signal</span></header>{edges.map(([sourceId, targetId, link]) => {
    const source = byId.get(sourceId); const target = byId.get(targetId);
    const late = source.due_date && target.due_date && source.due_date > target.due_date;
    return <div key={link.id} className={cyclicIds.has(sourceId) && cyclicIds.has(targetId) ? 'cycle' : ''}><button onClick={() => onOpen(source.id)}><TypeIcon type={source.item_type} itemTypes={workflowItemTypes(overview)} /><span><strong>{source.key}</strong>{source.summary}</span></button><span>blocks <b>→</b></span><button onClick={() => onOpen(target.id)}><TypeIcon type={target.item_type} itemTypes={workflowItemTypes(overview)} /><span><strong>{target.key}</strong>{target.summary}</span></button><span className={late ? 'late' : ''}>{late ? `Risk: blocker due ${compactDate(source.due_date)}` : source.due_date ? `Upstream due ${compactDate(source.due_date)}` : 'No upstream date'}</span></div>;
  })}{edges.length === 0 && <div className="work-empty"><span>⌁</span><strong>No blocking paths yet</strong><p>Add a blocks or depends on link from an issue to model the delivery chain.</p></div>}</section></div>;
}

function ReleasesView({ items, overview, isAdmin, onOpen, onUpdateRelease }) {
  const [copied, setCopied] = useState('');
  const columns = workflowColumns(overview);
  const copyNotes = async (release, releaseItems) => {
    const groups = releaseItems.reduce((result, item) => ({ ...result, [item.item_type]: [...(result[item.item_type] || []), item] }), {});
    const notes = [`# ${release.name}`, release.description || '', ...Object.entries(groups).flatMap(([type, entries]) => [`\n## ${workflowItemTypes(overview).find((candidate) => candidate.id === type)?.label || type}`, ...entries.map((item) => `- ${item.key}: ${item.summary}`)])].join('\n');
    await navigator.clipboard?.writeText(notes); setCopied(release.id); window.setTimeout(() => setCopied(''), 1600);
  };
  return <div className="releases-view"><header className="work-view-heading"><div><p className="eyebrow">Versions & releases</p><h2>Release readiness</h2><p>Control scope, surface unresolved risk, and create release notes from one live plan.</p></div></header><div className="release-grid">{overview.releases.map((release) => {
    const releaseItems = items.filter((item) => item.release_id === release.id);
    const done = releaseItems.filter((item) => isDone(item, columns));
    const blocked = releaseItems.filter((item) => columnFor(item.status, columns).category === 'blocked');
    const defects = releaseItems.filter((item) => item.item_type === 'bug' && !isDone(item, columns));
    const ready = releaseItems.length > 0 && done.length === releaseItems.length;
    return <article key={release.id}><header><div><span className={`sprint-status ${release.status}`}>{release.status.replace('_', ' ')}</span><h3>{release.name}</h3><p>{release.description || 'No release outcome documented.'}</p></div><strong>{releaseItems.length ? Math.round(done.length / releaseItems.length * 100) : 0}%</strong></header><div className="release-readiness"><span><b>{done.length}/{releaseItems.length}</b> delivered</span><span className={blocked.length ? 'danger' : ''}><b>{blocked.length}</b> blocked</span><span className={defects.length ? 'danger' : ''}><b>{defects.length}</b> open defects</span><span><b>{displayDate(release.target_date)}</b> target</span></div><div className="release-scope">{releaseItems.slice(0, 8).map((item) => <button key={item.id} onClick={() => onOpen(item.id)}><TypeIcon type={item.item_type} itemTypes={workflowItemTypes(overview)} /><span><strong>{item.key}</strong>{item.summary}</span><b style={{ color: columnFor(item.status, columns).color }}>{columnFor(item.status, columns).label}</b></button>)}{releaseItems.length > 8 && <small>＋ {releaseItems.length - 8} more scoped issues</small>}</div><footer><button onClick={() => copyNotes(release, releaseItems)}>{copied === release.id ? '✓ Notes copied' : '▤ Copy release notes'}</button>{isAdmin && release.status === 'planned' && <button onClick={() => onUpdateRelease(release, 'in_progress')}>Start release</button>}{isAdmin && release.status === 'in_progress' && <button className="primary" disabled={!ready} title={ready ? 'Mark release delivered' : 'Complete every scoped issue before release'} onClick={() => onUpdateRelease(release, 'released')}>Release</button>}</footer></article>;
  })}{overview.releases.length === 0 && <div className="work-empty"><span>◇</span><strong>No releases planned</strong><p>Create a release from Roadmap, then assign work to its scope.</p></div>}</div></div>;
}

function BoardView({ items, overview, onOpen, onMove, canEditItem }) {
  const [dragging, setDragging] = useState(null);
  const [expandedColumns, setExpandedColumns] = useState(() => new Set());
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  return <div className="agile-board" style={{ '--board-columns': columns.length }}>{columns.map((column) => {
    const columnItems = items.filter((item) => item.status === column.id);
    const overLimit = column.wip_limit && columnItems.length > column.wip_limit;
    return <section className={`board-column ${dragging ? 'dragging' : ''} ${overLimit ? 'over-limit' : ''}`} style={{ '--column-color': column.color }} key={column.id} onDragOver={(event) => event.preventDefault()} onDrop={() => { if (dragging && dragging.status !== column.id) onMove(dragging, column.id); setDragging(null); }}>
      <header><span><i /><strong>{column.label}</strong><b>{columnItems.length}{column.wip_limit ? ` / ${column.wip_limit}` : ''}</b></span><small>{column.hint}</small>{overLimit && <em>WIP limit exceeded</em>}</header>
      <div>{columnItems.slice(0, expandedColumns.has(column.id) ? columnItems.length : 12).map((item) => <WorkCard key={item.id} item={item} columns={columns} itemTypes={itemTypes} sprint={overview.sprints.find((sprint) => sprint.id === item.sprint_id)} onOpen={onOpen} canEdit={canEditItem(item)} onDragStart={(event, current) => { event.dataTransfer.effectAllowed = 'move'; setDragging(current); }} />)}{columnItems.length > 12 && <button className="board-show-more" onClick={() => setExpandedColumns((current) => { const next = new Set(current); if (next.has(column.id)) next.delete(column.id); else next.add(column.id); return next; })}>{expandedColumns.has(column.id) ? 'Show fewer' : `Show ${columnItems.length - 12} more`}</button>}{columnItems.length === 0 && <p className="board-empty">Drop work here</p>}</div>
    </section>;
  })}</div>;
}

function SwimlaneBoard({ items, overview, onOpen, onMove, canEditItem, swimlane }) {
  if (!swimlane) return <BoardView items={items} overview={overview} onOpen={onOpen} onMove={onMove} canEditItem={canEditItem} />;
  const groupKey = (item) => swimlane === 'assignee' ? item.assignee?.display_name || 'Unassigned'
    : swimlane === 'team' ? item.team || 'No team' : overview.projects.find((project) => project.id === item.project_id)?.title || 'No project';
  const groups = [...new Set(items.map(groupKey))].sort();
  return <div className="swimlane-board">{groups.map((group) => <section key={group}><header><strong>{group}</strong><span>{items.filter((item) => groupKey(item) === group).length} items</span></header><BoardView items={items.filter((item) => groupKey(item) === group)} overview={overview} onOpen={onOpen} onMove={onMove} canEditItem={canEditItem} /></section>)}</div>;
}

function BacklogView({ items, overview, isAdmin, onOpen, onAssignSprint, onRank }) {
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  const backlog = items.filter((item) => !item.sprint_id && !isDone(item, columns)).sort((left, right) => left.rank - right.rank);
  const sprintGroups = overview.sprints.filter((sprint) => !['completed', 'cancelled'].includes(sprint.status));
  const row = (item, groupItems, index) => <div className="backlog-row" key={item.id}><span className="backlog-rank">{isAdmin && <><button disabled={index === 0} aria-label={`Move ${item.key} up`} onClick={() => onRank(item, -1, groupItems)}>↑</button><button disabled={index === groupItems.length - 1} aria-label={`Move ${item.key} down`} onClick={() => onRank(item, 1, groupItems)}>↓</button></>}</span><TypeIcon type={item.item_type} itemTypes={itemTypes} /><button className="backlog-open" onClick={() => onOpen(item.id)}><strong>{item.key}</strong><span>{item.summary}</span></button><span className={`work-priority ${item.priority}`}><i />{item.priority}</span><b>{item.story_points ?? '—'}</b><WorkAvatar member={item.assignee} small />{isAdmin ? <select aria-label={`Sprint for ${item.key}`} value={item.sprint_id || ''} onChange={(event) => onAssignSprint(item, event.target.value || null)}><option value="">Backlog</option>{sprintGroups.map((sprint) => <option value={sprint.id} key={sprint.id}>{sprint.name}</option>)}</select> : <span>{overview.sprints.find((sprint) => sprint.id === item.sprint_id)?.name || 'Backlog'}</span>}</div>;
  return <div className="backlog-view"><section><header><div><h2>Product backlog</h2><p>Rank work, estimate scope, and pull the highest-value outcomes into a sprint.</p></div><span>{backlog.length} items · {points(backlog)} points</span></header><div className="backlog-heading"><span>Rank</span><span>Type</span><span>Issue</span><span>Priority</span><span>Points</span><span>Owner</span><span>Sprint</span></div>{backlog.map((item, index) => row(item, backlog, index))}{backlog.length === 0 && <div className="work-empty"><span>✓</span><strong>Backlog is clear</strong><p>Capture the next outcome with Create work.</p></div>}</section>{sprintGroups.map((sprint) => { const sprintItems = items.filter((item) => item.sprint_id === sprint.id).sort((left, right) => left.rank - right.rank); return <section key={sprint.id}><header><div><h2>{sprint.name}</h2><p>{sprint.goal || 'No sprint goal defined.'}</p></div><span>{sprintItems.length} items · {points(sprintItems)}/{sprint.capacity_points || '—'} points</span></header>{sprintItems.map((item, index) => row(item, sprintItems, index))}</section>; })}</div>;
}

function StoryTreeItem({ item, overview, childrenByParent, onOpen, onCreateChild, onOpenFlowchart, canEditItem, ancestry = [] }) {
  if (ancestry.includes(item.id)) return null;
  const children = childrenByParent.get(item.id) || [];
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  const nextChildType = childTypeFor(item, itemTypes);
  const nextChildLabel = itemTypes.find((type) => type.id === nextChildType)?.label || nextChildType;
  const context = flowchartContext(item, overview);
  const statusConfig = columnFor(item.status, columns);
  const progress = itemProgress(item, overview.items, columns);
  const qaChildren = children.filter((child) => columnFor(child.status, columns).category === 'qa').length;
  return <li className={`story-tree-item story-tree-${item.item_type}`}>
    <article className="story-tree-row">
      <button type="button" className="story-tree-open" onClick={() => onOpen(item.id)}>
        <TypeIcon type={item.item_type} itemTypes={itemTypes} />
        <span className="story-tree-copy"><small>{item.key} · {itemTypes.find((type) => type.id === item.item_type)?.label || item.item_type}</small><strong>{item.summary}</strong>{children.length > 0 && <em>{progress}% progress{qaChildren ? ` · ${qaChildren} in QA` : ''}</em>}</span>
      </button>
      <span className={`story-status ${item.status}`} style={{ '--status-color': statusConfig.color }}><i />{statusConfig.label}</span>
      <span className="story-progress"><i><b style={{ width: `${progress}%` }} /></i><strong>{progress}%</strong></span>
      <WorkAvatar member={item.assignee} small />
      {context ? <button type="button" className="story-flow-link" onClick={() => onOpenFlowchart(context.project.id, item.node_id)} title={`Open ${context.project.title}`}>
        <span aria-hidden="true">↳</span><span>{context.project.title}<small>{context.node?.label || 'Whole workflow'}</small></span>
      </button> : <span className="story-flow-empty">No workflow</span>}
      {nextChildType && canEditItem(item) ? <button type="button" className="story-add-child" onClick={() => onCreateChild(item)}>＋ {nextChildLabel}</button> : <span className="story-add-spacer" />}
    </article>
    {children.length > 0 && <ul>{children.map((child) => <StoryTreeItem key={child.id} item={child} overview={overview}
      childrenByParent={childrenByParent} onOpen={onOpen} onCreateChild={onCreateChild} onOpenFlowchart={onOpenFlowchart}
      canEditItem={canEditItem} ancestry={[...ancestry, item.id]} />)}</ul>}
  </li>;
}

function StoriesView({ items, overview, onOpen, onCreateChild, onOpenFlowchart, canEditItem }) {
  const itemIds = new Set(items.map((item) => item.id));
  const childrenByParent = new Map();
  items.forEach((item) => {
    if (!item.parent_id || !itemIds.has(item.parent_id)) return;
    childrenByParent.set(item.parent_id, [...(childrenByParent.get(item.parent_id) || []), item]);
  });
  const roots = items.filter((item) => !item.parent_id || !itemIds.has(item.parent_id));
  const rootCount = roots.length;
  const childCount = items.filter((item) => item.parent_id && itemIds.has(item.parent_id)).length;
  const linkedCount = items.filter((item) => item.project_id).length;
  return <div className="stories-view">
    <header className="work-view-heading stories-heading"><div><p className="eyebrow">Connected work hierarchy</p><p>Break down any type of work and trace each deliverable back to its process step.</p></div>
      <div className="story-summary"><span><strong>{rootCount}</strong> top-level</span><span><strong>{childCount}</strong> child items</span><span><strong>{linkedCount}</strong> workflow links</span></div>
    </header>
    <div className="story-tree-columns" aria-hidden="true"><span>Work item</span><span>Status</span><span>Progress</span><span>Owner</span><span>Workflow step</span><span>Break down</span></div>
    {roots.length > 0 ? <ul className="story-tree" aria-label="Story hierarchy">{roots.map((item) => <StoryTreeItem key={item.id} item={item} overview={overview}
      childrenByParent={childrenByParent} onOpen={onOpen} onCreateChild={onCreateChild} onOpenFlowchart={onOpenFlowchart}
      canEditItem={canEditItem} />)}</ul> : <div className="work-empty story-tree-empty"><span>▤</span><strong>No work hierarchy yet</strong><p>Create a parent work item, break it into deliverables, and optionally link each item to a workflow step.</p></div>}
  </div>;
}

function SprintView({ overview, items, isAdmin, onOpen, onCreate, onTransition }) {
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', goal: '', start_date: '', end_date: '', capacity_points: '' });
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  const submit = async (event) => { event.preventDefault(); await onCreate({ ...form, start_date: form.start_date || null, end_date: form.end_date || null, capacity_points: form.capacity_points === '' ? null : Number(form.capacity_points) }); setCreating(false); setForm({ name: '', goal: '', start_date: '', end_date: '', capacity_points: '' }); };
  return <div className="sprints-view"><header className="work-view-heading"><div><p className="eyebrow">Iteration planning</p><h2>Sprints</h2><p>Set a measurable goal, balance capacity, and keep one active sprint.</p></div>{isAdmin && <button className="button primary" onClick={() => setCreating((value) => !value)}>{creating ? 'Cancel' : 'Create sprint'}</button>}</header>{creating && <form className="sprint-form" onSubmit={submit}><label>Sprint name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Sprint 12" /></label><label>Goal<input value={form.goal} onChange={(event) => setForm({ ...form, goal: event.target.value })} placeholder="Improve onboarding reliability" /></label><label>Start<input type="date" value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} /></label><label>End<input type="date" value={form.end_date} onChange={(event) => setForm({ ...form, end_date: event.target.value })} /></label><label>Capacity<input type="number" min="0" value={form.capacity_points} onChange={(event) => setForm({ ...form, capacity_points: event.target.value })} placeholder="40" /></label><button className="button primary">Save sprint</button></form>}
    <div className="sprint-grid">{overview.sprints.map((sprint) => {
      const sprintItems = items.filter((item) => item.sprint_id === sprint.id);
      const committed = points(sprintItems);
      const delivered = points(sprintItems.filter((item) => isDone(item, columns)));
      const qaCount = sprintItems.filter((item) => columnFor(item.status, columns).category === 'qa').length;
      const progress = sprintItems.length ? Math.round(sprintItems.reduce((sum, item) => sum + itemProgress(item, items, columns), 0) / sprintItems.length) : 0;
      const capacity = sprint.capacity_points || Math.max(committed, 1);
      return <article className={`sprint-card ${sprint.status}`} key={sprint.id}><header><span className={`sprint-status ${sprint.status}`}>{sprint.status}</span><span>{displayDate(sprint.start_date)} — {displayDate(sprint.end_date)}</span></header><h3>{sprint.name}</h3><p>{sprint.goal || 'No goal has been defined.'}</p><div className="sprint-metrics"><span><strong>{sprintItems.length}</strong><small>items</small></span><span><strong>{committed}</strong><small>committed</small></span><span><strong>{qaCount}</strong><small>in QA</small></span><span><strong>{progress}%</strong><small>progress</small></span><span><strong>{sprint.capacity_points ?? '—'}</strong><small>capacity</small></span></div><div className="capacity-track" title={`${delivered} delivered points`}><i style={{ width: `${Math.min(100, (committed / capacity) * 100)}%` }} /><b style={{ width: `${progress}%` }} /></div><div className="sprint-items">{sprintItems.slice(0, 6).map((item) => <button key={item.id} onClick={() => onOpen(item.id)}><TypeIcon type={item.item_type} itemTypes={itemTypes} /><span>{item.key} · {item.summary}</span><b>{columnFor(item.status, columns).label}</b></button>)}</div>{isAdmin && sprint.status === 'planned' && <button className="button secondary sprint-action" onClick={() => onTransition(sprint, 'active')}>Start sprint</button>}{isAdmin && sprint.status === 'active' && <button className="button primary sprint-action" onClick={() => onTransition(sprint, 'completed')}>Complete sprint</button>}</article>;
    })}{overview.sprints.length === 0 && <div className="work-empty"><span>◎</span><strong>No sprints yet</strong><p>Create an iteration and pull prioritized backlog work into it.</p></div>}</div>
  </div>;
}

function RoadmapView({ overview, items, isAdmin, onOpen, onCreateRelease, onUpdateRelease }) {
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', description: '', start_date: '', target_date: '', scenario: 'committed' });
  const submit = async (event) => { event.preventDefault(); await onCreateRelease({ ...form, start_date: form.start_date || null, target_date: form.target_date || null }); setCreating(false); setForm({ name: '', description: '', start_date: '', target_date: '', scenario: 'committed' }); };
  const unplannedEpics = items.filter((item) => ['epic', 'milestone'].includes(item.item_type) && !item.release_id);
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  return <div className="roadmap-view"><header className="work-view-heading"><div><p className="eyebrow">Long-term planning</p><h2>Roadmap</h2><p>Connect strategic epics to releases, target dates, baselines, and portfolio scenarios.</p></div>{isAdmin && <button className="button primary" onClick={() => setCreating((value) => !value)}>{creating ? 'Cancel' : 'Create release'}</button>}</header>{creating && <form className="sprint-form release-form" onSubmit={submit}><label>Release name<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="2027 Q1 platform" /></label><label>Description<input value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="Business outcome" /></label><label>Start<input type="date" value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} /></label><label>Target<input type="date" value={form.target_date} onChange={(event) => setForm({ ...form, target_date: event.target.value })} /></label><label>Scenario<select value={form.scenario} onChange={(event) => setForm({ ...form, scenario: event.target.value })}><option value="committed">Committed</option><option value="optimistic">Optimistic</option><option value="conservative">Conservative</option></select></label><button className="button primary">Save release</button></form>}
    <div className="roadmap-timeline"><div className="roadmap-scale"><span>Now</span><span>Near term</span><span>Later</span></div>{overview.releases.map((release) => { const releaseItems = items.filter((item) => item.release_id === release.id); const complete = releaseItems.length ? Math.round(releaseItems.reduce((sum, item) => sum + itemProgress(item, items, columns), 0) / releaseItems.length) : 0; const baselineTarget = release.baseline?.target_date; const variance = baselineTarget && release.target_date ? Math.round((new Date(release.target_date) - new Date(baselineTarget)) / 86400000) : 0; return <section key={release.id}><header><span className={`release-dot ${release.status}`} /><div><h3>{release.name}</h3><p>{release.description || 'No release description.'}</p><small>{release.scenario || 'committed'} scenario{baselineTarget ? ` · baseline ${displayDate(baselineTarget)}${variance ? ` · ${variance > 0 ? '+' : ''}${variance}d variance` : ''}` : ''}</small></div><span>{displayDate(release.target_date)}</span>{isAdmin && release.status !== 'released' && <button onClick={() => onUpdateRelease(release, release.status === 'planned' ? 'in_progress' : 'released')}>{release.status === 'planned' ? 'Start' : 'Release'}</button>}</header><div className="release-progress"><i><b style={{ width: `${complete}%` }} /></i><span>{complete}% · {releaseItems.length} work items</span></div><div className="roadmap-items">{releaseItems.map((item) => <button key={item.id} onClick={() => onOpen(item.id)}><TypeIcon type={item.item_type} itemTypes={itemTypes} /><span><strong>{item.key}</strong>{item.summary}</span><b style={{ color: columnFor(item.status, columns).color }}>{columnFor(item.status, columns).label}</b></button>)}</div></section>; })}</div>{unplannedEpics.length > 0 && <section className="unplanned-epics"><h3>Unscheduled strategic work</h3>{unplannedEpics.map((item) => <button key={item.id} onClick={() => onOpen(item.id)}><TypeIcon type={item.item_type} itemTypes={itemTypes} /><strong>{item.key}</strong><span>{item.summary}</span></button>)}</section>}
  </div>;
}

function ReportsView({ overview, items }) {
  const columns = workflowColumns(overview);
  const completed = items.filter((item) => isDone(item, columns));
  const active = items.filter((item) => !isDone(item, columns));
  const qaItems = items.filter((item) => columnFor(item.status, columns).category === 'qa');
  const workInProgress = items.filter((item) => ['active', 'qa', 'review'].includes(columnFor(item.status, columns).category));
  const overdue = active.filter((item) => item.due_date && item.due_date < new Date().toISOString().slice(0, 10));
  const completedSprints = overview.sprints.filter((sprint) => sprint.status === 'completed').slice(0, 8).reverse();
  const maxVelocity = Math.max(1, ...completedSprints.map((sprint) => points(items.filter((item) => item.sprint_id === sprint.id && isDone(item, columns)))));
  const completionDate = (item) => item.activity?.find((event) => {
    const next = event.changes?.status?.to;
    return next && columnFor(next, columns).category === 'done';
  })?.created_at || (isDone(item, columns) ? item.updated_at : null);
  const completedWithDates = completed.map((item) => ({ item, completedAt: completionDate(item) })).filter((entry) => entry.completedAt);
  const averageLeadDays = completedWithDates.length ? Math.round(completedWithDates.reduce((sum, entry) => (
    sum + Math.max(0, new Date(entry.completedAt) - new Date(entry.item.created_at)) / 86400000
  ), 0) / completedWithDates.length * 10) / 10 : 0;
  const cycleSamples = completedWithDates.map((entry) => {
    const started = [...(entry.item.activity || [])].reverse().find((event) => {
      const next = event.changes?.status?.to;
      return next && ['active', 'qa', 'review'].includes(columnFor(next, columns).category);
    });
    return started ? Math.max(0, (new Date(entry.completedAt) - new Date(started.created_at)) / 86400000) : null;
  }).filter((value) => value != null);
  const averageCycleDays = cycleSamples.length ? Math.round(cycleSamples.reduce((sum, value) => sum + value, 0) / cycleSamples.length * 10) / 10 : 0;
  const thirtyDaysAgo = Date.now() - 30 * 86400000;
  const recentThroughput = completedWithDates.filter((entry) => new Date(entry.completedAt).getTime() >= thirtyDaysAgo).length;
  const activeSprint = overview.sprints.find((sprint) => sprint.status === 'active');
  const sprintItems = activeSprint ? items.filter((item) => item.sprint_id === activeSprint.id) : [];
  const sprintStart = activeSprint?.start_date ? new Date(`${activeSprint.start_date}T12:00:00`) : null;
  const sprintEnd = activeSprint?.end_date ? new Date(`${activeSprint.end_date}T12:00:00`) : null;
  const burndownDays = sprintStart && sprintEnd && sprintEnd >= sprintStart ? Array.from({ length: Math.min(31, Math.floor((sprintEnd - sprintStart) / 86400000) + 1) }, (_, index) => {
    const date = new Date(sprintStart.getTime() + index * 86400000);
    const remaining = points(sprintItems.filter((item) => !completionDate(item) || new Date(completionDate(item)) > date));
    return { date, remaining };
  }) : [];
  const maxBurndown = Math.max(1, points(sprintItems));
  const statusMax = Math.max(1, ...columns.map((column) => items.filter((item) => item.status === column.id).length));
  const releaseStats = overview.releases.slice(0, 8).map((release) => {
    const releaseItems = items.filter((item) => item.release_id === release.id);
    const total = Math.max(1, points(releaseItems) || releaseItems.length);
    const delivered = points(releaseItems.filter((item) => isDone(item, columns))) || releaseItems.filter((item) => isDone(item, columns)).length;
    return { ...release, total, delivered, percent: Math.round(delivered / total * 100) };
  });
  return <div className="reports-view"><header className="work-view-heading"><div><p className="eyebrow">Delivery intelligence</p><h2>Reports</h2><p>Track throughput, QA queues, flow efficiency, team load, and sprint predictability.</p></div></header><div className="report-kpis"><article><span>Completion</span><strong>{items.length ? Math.round((completed.length / items.length) * 100) : 0}%</strong><small>{completed.length} of {items.length} items</small></article><article><span>Work in progress</span><strong>{workInProgress.length}</strong><small>Across active, QA, and review</small></article><article className={qaItems.length ? 'qa' : ''}><span>QA queue</span><strong>{qaItems.length}</strong><small>Ready for or currently testing</small></article><article className={overdue.length ? 'attention' : ''}><span>Overdue</span><strong>{overdue.length}</strong><small>Open items past due</small></article><article><span>Delivered points</span><strong>{points(completed)}</strong><small>Across all completed work</small></article></div><div className="flow-kpis"><span><small>Average lead time</small><strong>{averageLeadDays}d</strong></span><span><small>Average cycle time</small><strong>{averageCycleDays}d</strong></span><span><small>30-day throughput</small><strong>{recentThroughput}</strong></span><span><small>Blocked now</small><strong>{active.filter((item) => columnFor(item.status, columns).category === 'blocked').length}</strong></span></div><div className="report-grid"><section><header><h3>Cumulative work by status</h3><p>Current distribution across the delivery system</p></header><div className="status-chart">{columns.map((column) => { const count = items.filter((item) => item.status === column.id).length; return <div key={column.id}><span>{column.label}</span><i><b style={{ width: `${(count / statusMax) * 100}%`, background: column.color }} /></i><strong>{count}</strong></div>; })}</div></section><section><header><h3>Sprint velocity</h3><p>Completed story points per finished sprint</p></header><div className="velocity-chart">{completedSprints.map((sprint) => { const value = points(items.filter((item) => item.sprint_id === sprint.id && isDone(item, columns))); return <div key={sprint.id}><i><b style={{ height: `${Math.max(4, (value / maxVelocity) * 100)}%` }} /></i><span>{sprint.name}</span><strong>{value}</strong></div>; })}{completedSprints.length === 0 && <div className="report-placeholder">Complete a sprint to establish velocity.</div>}</div></section><section><header><h3>Active sprint burndown</h3><p>{activeSprint ? `${activeSprint.name} · remaining story points by day` : 'Start a dated sprint to see burndown'}</p></header>{burndownDays.length ? <div className="burndown-chart">{burndownDays.map((point) => <span key={point.date.toISOString()} title={`${compactDate(point.date.toISOString())}: ${point.remaining} points`}><i style={{ height: `${Math.max(3, point.remaining / maxBurndown * 100)}%` }} /></span>)}</div> : <div className="report-placeholder">A start date and end date are required.</div>}</section><section><header><h3>Release burnup</h3><p>Delivered scope against committed scope</p></header><div className="status-chart">{releaseStats.map((release) => <div key={release.id}><span>{release.name}</span><i><b style={{ width: `${release.percent}%` }} /></i><strong>{release.delivered}/{release.total}</strong></div>)}{releaseStats.length === 0 && <div className="report-placeholder">Create a release to track scope burnup.</div>}</div></section><section className="workload-report"><header><h3>Team workload</h3><p>Open work and assigned points by teammate</p></header>{overview.members.map((member) => { const assigned = active.filter((item) => item.assignee?.id === member.id); return <div key={member.id}><WorkAvatar member={member} small /><span><strong>{member.display_name}</strong><small>{assigned.length} open items</small></span><b>{points(assigned)} pt</b></div>; })}</section><section><header><h3>Planning health</h3><p>Signals that need delivery-lead attention</p></header><div className="health-signals"><span><i className="warning" /><b>{active.filter((item) => !item.assignee).length}</b> unassigned items</span><span><i /><b>{active.filter((item) => item.sprint_id && item.story_points == null).length}</b> sprint items without estimates</span><span><i className="danger" /><b>{overdue.length}</b> overdue items</span><span><i className="success" /><b>{active.filter((item) => item.release_id).length}</b> open items tied to releases</span></div></section></div></div>;
}

const WORKFLOW_PRESETS = {
  software: { label: 'Product & software', columns: DEFAULT_COLUMNS },
  general: { label: 'General delivery', columns: [
    { ...DEFAULT_COLUMNS[0], label: 'To do', hint: 'Unscheduled requests and ideas' },
    { ...DEFAULT_COLUMNS[1], label: 'Planned', hint: 'Prioritized and ready to begin' },
    { ...DEFAULT_COLUMNS[2], label: 'Working', hint: 'Work currently underway' },
    { ...DEFAULT_COLUMNS[4], label: 'Verification', hint: 'Quality or completeness check' },
    { ...DEFAULT_COLUMNS[5], label: 'Approval', hint: 'Waiting for final sign-off' },
    { ...DEFAULT_COLUMNS[6] }, { ...DEFAULT_COLUMNS[7], label: 'Complete' },
  ] },
  marketing: { label: 'Marketing campaign', columns: [
    { ...DEFAULT_COLUMNS[0], label: 'Ideas' }, { ...DEFAULT_COLUMNS[1], label: 'Ready to create' },
    { ...DEFAULT_COLUMNS[2], label: 'Creating', hint: 'Content or campaign production' },
    { ...DEFAULT_COLUMNS[4], label: 'Brand & compliance', hint: 'Quality, brand, and legal checks' },
    { ...DEFAULT_COLUMNS[5], label: 'Stakeholder review' }, { ...DEFAULT_COLUMNS[6] },
    { ...DEFAULT_COLUMNS[7], label: 'Published', hint: 'Launched and measured' },
  ] },
  service: { label: 'Service operations', columns: [
    { ...DEFAULT_COLUMNS[0], label: 'Intake', hint: 'New requests and cases' },
    { ...DEFAULT_COLUMNS[1], label: 'Triaged' }, { ...DEFAULT_COLUMNS[2], label: 'Resolving' },
    { ...DEFAULT_COLUMNS[4], label: 'Quality check' }, { ...DEFAULT_COLUMNS[5], label: 'Customer confirmation' },
    { ...DEFAULT_COLUMNS[6], label: 'Waiting' }, { ...DEFAULT_COLUMNS[7], label: 'Resolved' },
  ] },
};

function WorkflowCustomizer({ overview, onCancel, onSave, saving, error }) {
  const [columns, setColumns] = useState(() => workflowColumns(overview).map((column) => ({ ...column })));
  const [itemTypes, setItemTypes] = useState(() => workflowItemTypes(overview).map((type) => ({ ...type, parent_types: [...(type.parent_types || [])] })));
  const usedStatuses = new Set(overview.items.map((item) => item.status));
  const usedTypes = new Set(overview.items.map((item) => item.item_type));
  const referencedTypes = new Set(itemTypes.flatMap((type) => [...(type.parent_types || []), ...(type.child_type ? [type.child_type] : [])]));
  const patchColumn = (index, changes) => setColumns((current) => current.map((column, candidate) => candidate === index ? { ...column, ...changes } : column));
  const patchType = (index, changes) => setItemTypes((current) => current.map((type, candidate) => candidate === index ? { ...type, ...changes } : type));
  const moveColumn = (index, direction) => setColumns((current) => {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= current.length) return current;
    const next = [...current]; [next[index], next[nextIndex]] = [next[nextIndex], next[index]]; return next;
  });
  const applyPreset = (key) => {
    const preset = WORKFLOW_PRESETS[key];
    const presetIds = new Set(preset.columns.map((column) => column.id));
    const inUseExtras = columns.filter((column) => usedStatuses.has(column.id) && !presetIds.has(column.id));
    setColumns([...preset.columns.map((column) => ({ ...column })), ...inUseExtras]);
  };
  const addColumn = () => setColumns((current) => [...current, {
    id: `stage_${Date.now().toString(36)}`, label: 'New stage', hint: 'Describe what belongs here',
    color: '#5F6FDA', category: 'active', progress: 50, wip_limit: null,
  }]);
  const addType = () => setItemTypes((current) => [...current, {
    id: `work_${Date.now().toString(36)}`, label: 'New work type', icon: '□', parent_types: [], child_type: null,
  }]);
  const submit = (event) => { event.preventDefault(); onSave({ columns, item_types: itemTypes }); };
  return <form className="workflow-form" onSubmit={submit}>
    <header><div><p className="eyebrow">Workspace configuration</p><h2>Customize workflow</h2><p>Shape this board for product, operations, marketing, HR, finance, service, or any delivery team.</p></div><button type="button" className="icon-button" onClick={onCancel} aria-label="Close workflow settings">×</button></header>
    {error && <div className="notice error workflow-error"><strong>Couldn’t save workflow</strong><span>{error}</span></div>}
    <section className="workflow-presets"><strong>Start from a preset</strong><div>{Object.entries(WORKFLOW_PRESETS).map(([key, preset]) => <button type="button" key={key} onClick={() => applyPreset(key)}>{preset.label}</button>)}</div></section>
    <section className="workflow-section"><header><div><h3>Board stages</h3><p>Order stages, define progress, and limit concurrent work.</p></div><button type="button" onClick={addColumn}>＋ Add stage</button></header>
      <div className="workflow-column-heading"><span>Order</span><span>Stage</span><span>Category</span><span>Progress</span><span>WIP limit</span><span>Color</span><span /></div>
      {columns.map((column, index) => <div className="workflow-column-row" key={column.id}>
        <span className="workflow-order"><button type="button" disabled={index === 0} onClick={() => moveColumn(index, -1)}>↑</button><button type="button" disabled={index === columns.length - 1} onClick={() => moveColumn(index, 1)}>↓</button></span>
        <label><input aria-label={`Stage ${index + 1} name`} required maxLength="60" value={column.label} onChange={(event) => patchColumn(index, { label: event.target.value })} /><input className="workflow-hint" aria-label={`${column.label} description`} maxLength="160" value={column.hint} onChange={(event) => patchColumn(index, { hint: event.target.value })} /><small>{column.id}</small></label>
        <select aria-label={`${column.label} category`} value={column.category} onChange={(event) => patchColumn(index, { category: event.target.value })}>{['queue', 'active', 'qa', 'review', 'blocked', 'done'].map((category) => <option key={category}>{category}</option>)}</select>
        <label className="workflow-number"><input aria-label={`${column.label} progress`} type="number" min="0" max="100" value={column.progress} onChange={(event) => patchColumn(index, { progress: Number(event.target.value) })} /><span>%</span></label>
        <input aria-label={`${column.label} WIP limit`} type="number" min="1" placeholder="None" value={column.wip_limit ?? ''} onChange={(event) => patchColumn(index, { wip_limit: event.target.value ? Number(event.target.value) : null })} />
        <input aria-label={`${column.label} color`} type="color" value={column.color} onChange={(event) => patchColumn(index, { color: event.target.value })} />
        <button type="button" className="workflow-remove" disabled={usedStatuses.has(column.id) || columns.length <= 2} title={usedStatuses.has(column.id) ? 'Move existing work before removing this stage' : 'Remove stage'} onClick={() => setColumns((current) => current.filter((candidate) => candidate.id !== column.id))}>×</button>
      </div>)}
    </section>
    <section className="workflow-section"><header><div><h3>Work types</h3><p>Create terminology that matches how your organization works.</p></div><button type="button" onClick={addType}>＋ Add type</button></header>
      <div className="workflow-types">{itemTypes.map((type, index) => <div key={type.id}><input aria-label={`${type.label} icon`} className="workflow-icon" required maxLength="8" value={type.icon} onChange={(event) => patchType(index, { icon: event.target.value })} /><label><input aria-label={`Work type ${index + 1} name`} required maxLength="60" value={type.label} onChange={(event) => patchType(index, { label: event.target.value })} /><small>{type.id}</small></label><input aria-label={`${type.label} parent types`} placeholder="Allowed parent IDs, comma separated" value={(type.parent_types || []).join(', ')} onChange={(event) => patchType(index, { parent_types: event.target.value.split(',').map((value) => value.trim()).filter(Boolean) })} /><select aria-label={`${type.label} child type`} value={type.child_type || ''} onChange={(event) => patchType(index, { child_type: event.target.value || null })}><option value="">No default child</option>{itemTypes.filter((candidate) => candidate.id !== type.id).map((candidate) => <option value={candidate.id} key={candidate.id}>{candidate.label}</option>)}</select><button type="button" className="workflow-remove" disabled={usedTypes.has(type.id) || referencedTypes.has(type.id) || itemTypes.length <= 1} title={usedTypes.has(type.id) ? 'Reclassify existing work before removing this type' : referencedTypes.has(type.id) ? 'Remove this type from other hierarchy rules first' : 'Remove work type'} onClick={() => setItemTypes((current) => current.filter((candidate) => candidate.id !== type.id))}>×</button></div>)}</div>
    </section>
    <footer><span>Stages and work types already in use are protected.</span><div><button type="button" className="button secondary" onClick={onCancel}>Cancel</button><button className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save workflow'}</button></div></footer>
  </form>;
}

const WORK_TABS = ['board', 'issues', 'stories', 'backlog', 'sprints', 'releases', 'roadmap', 'dependencies', 'reports'];

function createContextFromQuery(query) {
  if (query.get('create') !== '1') return null;
  const itemType = query.get('item_type') || 'task';
  return {
    title: query.get('source') === 'chat' ? 'Create task from message'
      : query.get('source') === 'assistant' ? `Create ${itemType}` : 'Create work item',
    initial: {
      ...EMPTY_ITEM,
      item_type: itemType,
      summary: (query.get('summary') || '').slice(0, 160),
      description: query.get('source') === 'chat'
        ? `Created from workspace message ${query.get('message') || ''}`.trim()
        : query.get('source') === 'calendar'
          ? `Follow-up from calendar event ${query.get('event') || ''}`.trim()
          : '',
    },
  };
}

export default function WorkManagement({ user, onNavigate, navigationKey = window.location.search }) {
  const initialQuery = useMemo(() => new URLSearchParams(navigationKey), [navigationKey]);
  const [overview, setOverview] = useState(EMPTY_OVERVIEW);
  const [state, setState] = useState('loading');
  const [error, setError] = useState('');
  const [tab, setTab] = useState(() => initialQuery.get('tab') || localStorage.getItem('flowforge:work-tab') || 'board');
  const [search, setSearch] = useState('');
  const [mineOnly, setMineOnly] = useState(false);
  const [activeSprintOnly, setActiveSprintOnly] = useState(() => (
    (initialQuery.get('tab') || localStorage.getItem('flowforge:work-tab') || 'board') === 'board'
    && initialQuery.get('scope') !== 'all'
  ));
  const [showArchived, setShowArchived] = useState(false);
  const [swimlane, setSwimlane] = useState('');
  const [createContext, setCreateContext] = useState(() => createContextFromQuery(initialQuery));
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState(() => initialQuery.get('item'));
  const [flowContext, setFlowContext] = useState(() => ({
    projectId: initialQuery.get('project'), nodeId: initialQuery.get('node'),
  }));
  const handledNavigationRef = useRef(navigationKey);
  const isAdmin = overview.current_user_role === 'admin';
  const columns = workflowColumns(overview);
  const itemTypes = workflowItemTypes(overview);
  const selectedItem = overview.items.find((item) => item.id === selectedId);
  const activeSprint = overview.sprints.find((sprint) => sprint.status === 'active');
  const contextProject = overview.projects.find((project) => project.id === flowContext.projectId);
  const contextNode = contextProject?.nodes.find((node) => node.id === flowContext.nodeId);
  const canEditItem = (item) => isAdmin || item.reporter.id === user.id || item.assignee?.id === user.id;
  const visibleItems = useMemo(() => overview.items.filter((item) => {
    const text = `${item.key} ${item.summary} ${item.description} ${item.labels.join(' ')}`.toLowerCase();
    return (!search || text.includes(search.toLowerCase()))
      && (showArchived || !item.archived)
      && (!mineOnly || item.assignee?.id === user.id || item.reporter.id === user.id)
      && (!activeSprintOnly || !activeSprint || item.sprint_id === activeSprint.id)
      && (!flowContext.projectId || item.project_id === flowContext.projectId)
      && (!flowContext.nodeId || item.node_id === flowContext.nodeId);
  }), [overview.items, search, mineOnly, activeSprintOnly, activeSprint, user.id, flowContext, showArchived]);

  const load = async (keepSelection = null) => {
    try { const result = await getWorkOverview(); setOverview(result); setState('ready'); setError(''); if (keepSelection) setSelectedId(keepSelection); }
    catch (requestError) { setError(requestError.message); setState('error'); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { localStorage.setItem('flowforge:work-tab', tab); }, [tab]);
  useEffect(() => {
    if (handledNavigationRef.current === navigationKey) return;
    handledNavigationRef.current = navigationKey;
    const query = new URLSearchParams(navigationKey);
    const requestedTab = query.get('tab');
    if (WORK_TABS.includes(requestedTab)) {
      setTab(requestedTab);
      setActiveSprintOnly(requestedTab === 'board' && query.get('scope') !== 'all');
    }
    const requestedCreate = createContextFromQuery(query);
    setCreateContext(requestedCreate);
  }, [navigationKey]);

  const patchItem = async (item, changes) => {
    const previous = overview;
    setOverview((current) => ({ ...current, items: current.items.map((candidate) => candidate.id === item.id ? { ...candidate, ...changes, assignee: changes.assignee_id !== undefined ? current.members.find((member) => member.id === changes.assignee_id) || null : candidate.assignee } : candidate) }));
    try { const updated = await updateWorkItem(item.id, { expected_revision: item.revision, ...changes }); setOverview((current) => ({ ...current, items: current.items.map((candidate) => candidate.id === item.id ? { ...candidate, ...updated } : candidate) })); }
    catch (requestError) { setOverview(previous); throw requestError; }
  };
  const openCreate = () => setCreateContext({
    title: 'Create work item',
    initial: { ...EMPTY_ITEM, item_type: itemTypes.some((type) => type.id === 'task') ? 'task' : itemTypes[0].id, status: columns[0].id, project_id: flowContext.projectId || '', node_id: flowContext.nodeId || '' },
  });
  const openCreateChild = (parent) => {
    const itemType = childTypeFor(parent, itemTypes);
    if (!itemType) return;
    const itemTypeLabel = itemTypes.find((type) => type.id === itemType)?.label || itemType;
    setCreateContext({
      title: `Add ${itemTypeLabel.toLowerCase()} to ${parent.key}`,
      initial: {
        ...EMPTY_ITEM, item_type: itemType, status: columns[0].id, parent_id: parent.id,
        sprint_id: parent.sprint_id || '', release_id: parent.release_id || '',
        project_id: parent.project_id || '', node_id: parent.node_id || '',
      },
    });
  };
  const submitItem = async (payload) => { setSaving(true); setError(''); try { const created = await createWorkItem(payload); await load(created.id); setCreateContext(null); setSelectedId(created.id); } catch (requestError) { setError(requestError.message); } finally { setSaving(false); } };
  const saveWorkflow = async (payload) => { setSaving(true); setError(''); try { const workflow = await updateWorkWorkflow(payload); setOverview((current) => ({ ...current, workflow })); setWorkflowOpen(false); } catch (requestError) { setError(requestError.message); } finally { setSaving(false); } };
  const createNewSprint = async (payload) => { try { await createSprint(payload); await load(); } catch (requestError) { setError(requestError.message); } };
  const transitionSprint = async (sprint, nextStatus) => { try { await updateSprint(sprint.id, { expected_revision: sprint.revision, name: sprint.name, goal: sprint.goal, start_date: sprint.start_date, end_date: sprint.end_date, capacity_points: sprint.capacity_points, status: nextStatus }); await load(); } catch (requestError) { setError(requestError.message); } };
  const createNewRelease = async (payload) => { try { await createRelease(payload); await load(); } catch (requestError) { setError(requestError.message); } };
  const transitionRelease = async (release, nextStatus) => { try { await updateRelease(release.id, { expected_revision: release.revision, name: release.name, description: release.description, start_date: release.start_date, target_date: release.target_date, status: nextStatus }); await load(); } catch (requestError) { setError(requestError.message); } };
  const bulkPatchItems = async (items, changes) => {
    try {
      const chunks = Array.from({ length: Math.ceil(items.length / 100) }, (_, index) => items.slice(index * 100, index * 100 + 100));
      const updated = (await Promise.all(chunks.map((chunk) => bulkUpdateWorkItems({ item_ids: chunk.map((item) => item.id), ...changes })))).flat();
      const byId = new Map(updated.map((item) => [item.id, item]));
      setOverview((current) => ({ ...current, items: current.items.map((item) => byId.has(item.id) ? { ...item, ...byId.get(item.id) } : item) }));
    } catch (requestError) { setError(requestError.message); throw requestError; }
  };
  const rankItem = async (item, direction, groupItems) => {
    const ordered = [...groupItems].sort((left, right) => left.rank - right.rank);
    const index = ordered.findIndex((candidate) => candidate.id === item.id);
    const destination = index + direction;
    if (index < 0 || destination < 0 || destination >= ordered.length) return;
    let rank;
    if (direction < 0) rank = destination === 0 ? Math.max(0, ordered[0].rank / 2) : (ordered[destination - 1].rank + ordered[destination].rank) / 2;
    else rank = destination === ordered.length - 1 ? ordered[destination].rank + 1024 : (ordered[destination].rank + ordered[destination + 1].rank) / 2;
    try { await patchItem(item, { rank }); } catch (requestError) { setError(requestError.message); }
  };
  const removeItem = async (item) => { if (!window.confirm(`Delete ${item.key}? This also removes its comments and dependencies.`)) return; try { await deleteWorkItem(item.id); setSelectedId(null); await load(); } catch (requestError) { setError(requestError.message); } };
  const duplicateItem = async (item) => { try { const created = await duplicateWorkItem(item.id); await load(created.id); setSelectedId(created.id); } catch (requestError) { setError(requestError.message); } };
  const splitItem = async (item) => {
    const entered = window.prompt(`Split ${item.key} into named child items (one per line):`, 'First deliverable\nSecond deliverable');
    const parts = entered?.split('\n').map((value) => value.trim()).filter(Boolean) || [];
    if (parts.length < 2) return;
    try { await splitWorkItem(item.id, parts); await load(item.id); } catch (requestError) { setError(requestError.message); }
  };
  const mergeItem = async (item) => {
    const candidates = overview.items.filter((candidate) => candidate.id !== item.id && !candidate.archived);
    const entered = window.prompt(`Merge other items into ${item.key}. Enter keys separated by commas:`, candidates.slice(0, 3).map((candidate) => candidate.key).join(', '));
    const keys = new Set((entered || '').split(',').map((value) => value.trim().toLowerCase()).filter(Boolean));
    const sourceIds = candidates.filter((candidate) => keys.has(candidate.key.toLowerCase())).map((candidate) => candidate.id);
    if (!sourceIds.length) return;
    try { await mergeWorkItems(item.id, sourceIds); await load(item.id); } catch (requestError) { setError(requestError.message); }
  };
  const followItem = async (item, following) => { try { await followWorkItem(item.id, following); await load(item.id); } catch (requestError) { setError(requestError.message); } };
  const clearFlowContext = () => {
    window.history.replaceState({}, '', '/work');
    setFlowContext({ projectId: null, nodeId: null });
  };
  const scheduleWork = (item) => {
    const params = new URLSearchParams({
      create: '1',
      title: `${item.key} · ${item.summary}`.slice(0, 160),
      description: `Work session for ${item.key}. Open item: ${window.location.origin}/work?item=${item.id}`,
      duration: String(item.estimate_minutes && item.estimate_minutes <= 480 ? Math.max(15, Math.round(item.estimate_minutes / 15) * 15) : 30),
    });
    if (item.due_date) params.set('date', item.due_date.slice(0, 10));
    onNavigate(`/calendar?${params.toString()}`);
  };
  const applySavedView = (viewId) => {
    const config = (overview.saved_views || []).find((view) => view.id === viewId)?.config;
    if (!config) return;
    setMineOnly(Boolean(config.mine)); setActiveSprintOnly(Boolean(config.active_sprint));
    setShowArchived(Boolean(config.archived)); setSwimlane(config.swimlane || '');
  };
  const saveCurrentView = async () => {
    const name = window.prompt('Name this board view:', 'My delivery view')?.trim();
    if (!name) return;
    try {
      await saveWorkspaceView({ name, view_type: 'board', scope_type: 'workspace', scope_id: null,
        config: { kind: 'board', mine: mineOnly, active_sprint: activeSprintOnly, archived: showArchived, swimlane }, shared: false, is_default: false });
      await load();
    } catch (requestError) { setError(requestError.message); }
  };
  const saveIssueFilter = async (query, sort) => {
    const name = window.prompt('Name this issue filter:', 'Delivery triage')?.trim();
    if (!name) return;
    try {
      await saveWorkspaceView({ name, view_type: 'board', scope_type: 'workspace', scope_id: null,
        config: { kind: 'issue_filter', query, sort }, shared: false, is_default: false });
      await load();
    } catch (requestError) { setError(requestError.message); }
  };

  return <main id="workspace-main" className="work-shell">
    <WorkspaceTopNav active="work" onNavigate={onNavigate} role={user.role} />
    <section className="work-layout"><aside className="work-sidebar"><div className="work-sidebar-heading"><span>Workspace</span><strong>Plan & deliver</strong></div><nav>{[
      ['board', '▦', 'Board'], ['issues', '⌕', 'Issues'], ['stories', '▤', 'Hierarchy'], ['backlog', '☷', 'Backlog'], ['sprints', '◎', 'Sprints'], ['releases', '◇', 'Releases'], ['roadmap', '⌁', 'Roadmap'], ['dependencies', '⤢', 'Dependencies'], ['reports', '⌗', 'Reports'],
    ].map(([id, icon, label]) => <button className={tab === id ? 'active' : ''} key={id} onClick={() => setTab(id)}><span>{icon}</span>{label}{id === 'board' && <b>{visibleItems.filter((item) => !isDone(item, columns)).length}</b>}</button>)}</nav><section><span>Quick views</span><button className={mineOnly ? 'selected' : ''} onClick={() => setMineOnly((value) => !value)}><span>◉</span>My work</button><button className={activeSprintOnly ? 'selected' : ''} onClick={() => setActiveSprintOnly((value) => !value)} disabled={!activeSprint}><span>◷</span>{activeSprint?.name || 'No active sprint'}</button><button className={showArchived ? 'selected' : ''} onClick={() => setShowArchived((value) => !value)}><span>□</span>{showArchived ? 'Hide archived' : 'Show archived'}</button></section><footer><strong>{overview.members.length}</strong><span>workspace members</span><div>{overview.members.slice(0, 5).map((member) => <WorkAvatar key={member.id} member={member} small />)}</div></footer></aside>
      <div className="work-main">{flowContext.projectId && <section className="work-flow-context">
        <div><span>Workflow delivery view</span><strong>{contextProject?.title || 'Linked workflow'}{flowContext.nodeId ? ` / ${contextNode?.label || 'Selected node'}` : ''}</strong><small>Board, backlog, roadmap, and reports are scoped to this process context.</small></div>
        <button onClick={() => onNavigate(`/projects/${flowContext.projectId}${flowContext.nodeId ? `?node=${flowContext.nodeId}` : ''}`)}>Open workflow ↗</button><button onClick={clearFlowContext}>Show all work</button>
      </section>}<header className="work-toolbar"><div className="work-toolbar-heading"><div><h1>{tab === 'board' ? activeSprintOnly && activeSprint ? activeSprint.name : 'Workspace board' : { issues: 'Issue navigator', stories: 'Stories & subtasks', backlog: 'Backlog', sprints: 'Sprint planning', releases: 'Releases', roadmap: 'Roadmap', dependencies: 'Dependencies', reports: 'Reports' }[tab]}</h1><p>{flowContext.nodeId ? `Delivery work owned by ${contextNode?.label || 'this workflow step'}.` : tab === 'board' ? activeSprintOnly && activeSprint ? activeSprint.goal || 'Focused work in the active sprint.' : 'Coordinate daily work across teams and long-term initiatives.' : tab === 'stories' ? 'Break epics into deliverable stories and executable subtasks.' : tab === 'issues' ? 'Search and safely update work across the workspace.' : 'One connected system from strategy to execution.'}</p></div><div className="work-toolbar-actions">{isAdmin && <button className="button secondary" onClick={() => { setError(''); setWorkflowOpen(true); }}>⚙ Customize</button>}<button className="button primary work-page-create" aria-label="Create work" onClick={openCreate}><span aria-hidden="true">＋</span> Create work</button></div></div><label className="work-search"><span>⌕</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search work by key, summary, or label" /></label><div className="work-filter-status">{mineOnly && <button onClick={() => setMineOnly(false)}>My work ×</button>}{activeSprintOnly && <button onClick={() => setActiveSprintOnly(false)}>Active sprint ×</button>}{flowContext.projectId && <button onClick={clearFlowContext}>Workflow ×</button>}{flowContext.nodeId && <button onClick={() => setFlowContext((current) => ({ ...current, nodeId: null }))}>Node ×</button>}<b>{visibleItems.length} items</b></div></header>
        {tab === 'board' && <div className="board-view-controls"><label>Swimlanes<select value={swimlane} onChange={(event) => setSwimlane(event.target.value)}><option value="">None</option><option value="assignee">Assignee</option><option value="team">Team</option><option value="project">Project</option></select></label><label>Saved board<select defaultValue="" onChange={(event) => applySavedView(event.target.value)}><option value="">Choose view…</option>{(overview.saved_views || []).filter((view) => view.config?.kind !== 'issue_filter').map((view) => <option key={view.id} value={view.id}>{view.name}{view.shared ? ' · shared' : ''}</option>)}</select></label><button onClick={saveCurrentView}>Save current view</button></div>}
        {error && <div className="work-global-error notice error"><strong>Work needs attention</strong><span>{error}</span><button onClick={() => setError('')}>×</button></div>}
        {state === 'loading' && <div className="work-loading"><span className="spinner dark" /> Loading your workspace…</div>}
        {state === 'error' && <div className="work-empty"><span>!</span><strong>Couldn’t load work</strong><p>{error}</p><button className="button secondary" onClick={() => load()}>Try again</button></div>}
        {state === 'ready' && <div className="work-view">{tab === 'board' && <SwimlaneBoard swimlane={swimlane} items={visibleItems} overview={overview} onOpen={setSelectedId} canEditItem={canEditItem} onMove={(item, status) => patchItem(item, { status }).catch((requestError) => setError(requestError.message))} />}{tab === 'issues' && <IssuesView items={visibleItems} overview={overview} user={user} onOpen={setSelectedId} onBulkUpdate={bulkPatchItems} onSaveFilter={saveIssueFilter} />}{tab === 'stories' && <StoriesView items={visibleItems} overview={overview} onOpen={setSelectedId} onCreateChild={openCreateChild} onOpenFlowchart={(projectId, nodeId) => onNavigate(`/projects/${projectId}${nodeId ? `?node=${nodeId}` : ''}`)} canEditItem={canEditItem} />}{tab === 'backlog' && <BacklogView items={visibleItems} overview={overview} isAdmin={isAdmin} onOpen={setSelectedId} onRank={rankItem} onAssignSprint={(item, sprintId) => patchItem(item, { sprint_id: sprintId }).catch((requestError) => setError(requestError.message))} />}{tab === 'sprints' && <SprintView overview={overview} items={visibleItems} isAdmin={isAdmin} onOpen={setSelectedId} onCreate={createNewSprint} onTransition={transitionSprint} />}{tab === 'releases' && <ReleasesView items={visibleItems} overview={overview} isAdmin={isAdmin} onOpen={setSelectedId} onUpdateRelease={transitionRelease} />}{tab === 'roadmap' && <RoadmapView overview={overview} items={visibleItems} isAdmin={isAdmin} onOpen={setSelectedId} onCreateRelease={createNewRelease} onUpdateRelease={transitionRelease} />}{tab === 'dependencies' && <DependenciesView items={visibleItems} overview={overview} onOpen={setSelectedId} />}{tab === 'reports' && <ReportsView overview={overview} items={visibleItems} />}</div>}
      </div></section>
    {createContext && <div className="work-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setCreateContext(null); }}><WorkItemForm overview={overview}
      initial={createContext.initial} title={createContext.title}
      onCancel={() => setCreateContext(null)} onSubmit={submitItem} saving={saving} /></div>}
    {workflowOpen && <div className="work-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setWorkflowOpen(false); }}><WorkflowCustomizer overview={overview} onCancel={() => setWorkflowOpen(false)} onSave={saveWorkflow} saving={saving} error={error} /></div>}
    {selectedItem && <ItemDrawer item={selectedItem} overview={overview} user={user} onClose={() => setSelectedId(null)} onPatch={patchItem} onRefresh={load} onOpenFlowchart={(projectId, nodeId) => onNavigate(`/projects/${projectId}${nodeId ? `?node=${nodeId}` : ''}`)} onSchedule={scheduleWork} onCreateChild={(item) => { setSelectedId(null); openCreateChild(item); }} onDelete={removeItem} onDuplicate={duplicateItem} onFollow={followItem} onSplit={splitItem} onMerge={mergeItem} />}
  </main>;
}
