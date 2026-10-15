import React, { useMemo, useState } from 'react';
import { UserSelect } from './UserPicker';

function EditableName({ value, disabled, ariaLabel, onCommit }) {
  const [draft, setDraft] = useState(value);
  const commit = () => {
    const next = draft.trim();
    if (!next) setDraft(value);
    else if (next !== value) onCommit(next);
  };
  return <input className="workflow-sheet-name-input" aria-label={ariaLabel} value={draft}
    disabled={disabled} maxLength="160" onChange={(event) => setDraft(event.target.value)}
    onBlur={commit} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} />;
}

function statusLabel(status) {
  return status.replace('_', ' ');
}

export default function WorkflowSheet({
  nodes = [], tasks = [], deliverables = [], contacts = [], currentUser,
  connected = false, canManage = false, onCreateTask = () => {},
  onUpdateTask = () => {}, onCreateDeliverable = () => {},
  onUpdateDeliverable = () => {}, onSelectNode = () => {},
}) {
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortBy, setSortBy] = useState('step');
  const [showCompleted, setShowCompleted] = useState(true);
  const [collapsed, setCollapsed] = useState(new Set());
  const [visibleGroupLimit, setVisibleGroupLimit] = useState(100);
  const [formulaColumns, setFormulaColumns] = useState(() => {
    try { return JSON.parse(localStorage.getItem(`flowforge:${currentUser?.id}:sheet-formulas`) || '[]'); } catch { return []; }
  });
  const [draft, setDraft] = useState({
    type: 'task', title: '', owner_id: '', due_date: '', node_id: '', priority: 'medium',
  });
  const setDraftValue = (name, value) => setDraft((current) => ({ ...current, [name]: value }));
  const members = useMemo(() => Array.from(new Map([
    { ...currentUser, color: currentUser?.color || '#5B4BE7' },
    ...contacts.map((contact) => contact.user || contact),
  ].filter((member) => member?.id).map((member) => [member.id, member])).values()), [contacts, currentUser]);
  const deliverableById = useMemo(
    () => Object.fromEntries(deliverables.map((item) => [item.id, item])), [deliverables]
  );
  const resolvedNodeId = (task) => task.node_id || deliverableById[task.deliverable_id]?.node_id || null;
  const groups = useMemo(() => {
    const result = nodes.map((node, index) => ({
      id: node.id,
      index,
      label: node.data?.label || node.id,
      deliverables: deliverables.filter((item) => item.node_id === node.id),
      tasks: tasks.filter((task) => resolvedNodeId(task) === node.id),
    }));
    const unlinkedDeliverables = deliverables.filter((item) => !item.node_id);
    const unlinkedTasks = tasks.filter((task) => !resolvedNodeId(task));
    if (unlinkedDeliverables.length || unlinkedTasks.length) {
      result.push({
        id: 'project-wide', index: result.length, label: 'Project-wide work',
        deliverables: unlinkedDeliverables, tasks: unlinkedTasks,
      });
    }
    return result;
  // deliverableById participates through resolvedNodeId.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deliverables, nodes, tasks, deliverableById]);

  const normalizedQuery = query.trim().toLowerCase();
  const includeItem = (item, type) => {
    if (typeFilter !== 'all' && typeFilter !== type) return false;
    if (statusFilter !== 'all' && item.status !== statusFilter) return false;
    if (!showCompleted && item.status === 'done') return false;
    return !normalizedQuery || [item.title, item.description, item.details, item.owner?.display_name,
      item.assignee?.display_name].filter(Boolean).some((value) => value.toLowerCase().includes(normalizedQuery));
  };
  const sortItems = (items) => [...items].sort((left, right) => {
    if (sortBy === 'name') return left.title.localeCompare(right.title);
    if (sortBy === 'owner') return (left.owner?.display_name || left.assignee?.display_name || 'zzz')
      .localeCompare(right.owner?.display_name || right.assignee?.display_name || 'zzz');
    if (sortBy === 'date') return (left.due_date || left.target_date || '9999-12-31')
      .localeCompare(right.due_date || right.target_date || '9999-12-31');
    if (sortBy === 'status') return left.status.localeCompare(right.status);
    return 0;
  });
  const visibleGroups = groups.map((group) => ({
    ...group,
    deliverables: sortItems(group.deliverables.filter((item) => includeItem(item, 'deliverable'))),
    tasks: sortItems(group.tasks.filter((item) => includeItem(item, 'task'))),
  })).filter((group) => group.deliverables.length || group.tasks.length || (
    typeFilter === 'all' && (!normalizedQuery || group.label.toLowerCase().includes(normalizedQuery))
  ));
  const renderedGroups = visibleGroups.slice(0, visibleGroupLimit);
  const formulaValue = (item, formula) => {
    if (formula === 'days_remaining') {
      const value = item.due_date || item.target_date;
      return value ? Math.ceil((new Date(`${value}T23:59:59`) - new Date()) / 86400000) : '—';
    }
    if (formula === 'completion') return item.status === 'done' ? '100%' : item.status === 'in_progress' ? '50%' : '0%';
    if (formula === 'owner_load') {
      const ownerId = item.assignee?.id || item.owner?.id;
      return ownerId ? [...tasks, ...deliverables].filter((candidate) => (candidate.assignee?.id || candidate.owner?.id) === ownerId && candidate.status !== 'done').length : '—';
    }
    return '—';
  };
  const formulaLabel = (formula) => ({ days_remaining: 'Days remaining', completion: 'Completion', owner_load: 'Owner load' }[formula] || formula);
  const addFormula = (formula) => {
    if (!formula || formulaColumns.includes(formula)) return;
    const next = [...formulaColumns, formula]; setFormulaColumns(next);
    localStorage.setItem(`flowforge:${currentUser?.id}:sheet-formulas`, JSON.stringify(next));
  };
  const doneCount = tasks.filter((task) => task.status === 'done').length
    + deliverables.filter((item) => item.status === 'done').length;
  const totalCount = tasks.length + deliverables.length;
  const overdueCount = [...tasks.map((item) => ({ ...item, date: item.due_date })),
    ...deliverables.map((item) => ({ ...item, date: item.target_date }))]
    .filter((item) => item.date && item.date < new Date().toISOString().slice(0, 10) && item.status !== 'done').length;

  const toggleGroup = (id) => setCollapsed((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const exportCsv = () => {
    const quote = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
    const rows = [['Step', 'Type', 'Name', 'Owner', 'Status', 'Priority', 'Due date']];
    visibleGroups.forEach((group) => {
      group.deliverables.forEach((item) => rows.push([group.label, 'Deliverable', item.title, item.owner?.display_name, item.status, '', item.target_date]));
      group.tasks.forEach((item) => rows.push([group.label, 'Task', item.title, item.assignee?.display_name, item.status, item.priority, item.due_date]));
    });
    const url = URL.createObjectURL(new Blob([rows.map((row) => row.map(quote).join(',')).join('\n')], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'workflow-sheet.csv'; anchor.click();
    URL.revokeObjectURL(url);
  };

  const submit = (event) => {
    event.preventDefault();
    if (!draft.title.trim() || !connected) return;
    if (draft.type === 'task') {
      onCreateTask({
        title: draft.title.trim(), details: '', assignee_id: draft.owner_id,
        priority: draft.priority, due_date: draft.due_date, deliverable_id: '', node_id: draft.node_id,
      });
    } else {
      onCreateDeliverable({
        title: draft.title.trim(), description: '', owner_id: draft.owner_id,
        target_date: draft.due_date, node_id: draft.node_id,
      });
    }
    setDraft((current) => ({ ...current, title: '', due_date: '' }));
  };

  const ownerPicker = (item, type) => <UserSelect label="Owner" ariaLabel={`${type} owner for ${item.title}`}
    users={members} value={(type === 'task' ? item.assignee : item.owner)?.id || ''}
    onChange={(ownerId) => type === 'task'
      ? onUpdateTask(item.id, { assignee_id: ownerId })
      : onUpdateDeliverable(item.id, { owner_id: ownerId })}
    emptyLabel="Unassigned" disabled={!canManage || !connected} />;

  return <section className="workflow-sheet" aria-label="Workflow project sheet">
    <header className="workflow-sheet-header"><div><p className="eyebrow">Live project grid</p><h2>Workflow sheet</h2>
      <span>Track the same steps and delivery work beside the diagram.</span></div>
      <div className="workflow-sheet-metrics"><span><strong>{totalCount}</strong><small>Work items</small></span>
        <span><strong>{totalCount ? Math.round((doneCount / totalCount) * 100) : 0}%</strong><small>Complete</small></span>
        <span className={overdueCount ? 'attention' : ''}><strong>{overdueCount}</strong><small>Overdue</small></span></div></header>
    <div className="workflow-sheet-toolbar"><label><span>⌕</span><input type="search" aria-label="Search workflow sheet"
      placeholder="Search work, owner, or step" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <select aria-label="Filter workflow sheet records" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
        <option value="all">All records</option><option value="deliverable">Deliverables</option><option value="task">Tasks</option>
      </select><select aria-label="Filter workflow sheet status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
        <option value="all">All statuses</option>{Array.from(new Set([...tasks, ...deliverables].map((item) => item.status))).map((status) => <option value={status} key={status}>{statusLabel(status)}</option>)}
      </select><select aria-label="Sort workflow sheet" value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
        <option value="step">Step order</option><option value="name">Name</option><option value="owner">Owner</option><option value="date">Due date</option><option value="status">Status</option>
      </select><button type="button" className="workflow-sheet-export" onClick={exportCsv}>↓ CSV</button><label className="workflow-sheet-toggle"><input type="checkbox" checked={showCompleted}
        onChange={(event) => setShowCompleted(event.target.checked)} />Show completed</label>
      <select aria-label="Add computed column" value="" onChange={(event) => addFormula(event.target.value)}><option value="">+ Formula column</option><option value="days_remaining">Days remaining</option><option value="completion">Completion</option><option value="owner_load">Owner load</option></select>
      <span className={`workflow-sheet-live ${connected ? 'connected' : ''}`}><i />{connected ? 'Live sync' : 'Reconnecting'}</span></div>
    <div className="workflow-sheet-grid-wrap"><div className={`workflow-sheet-grid ${formulaColumns.length ? 'has-formulas' : ''}`} style={{ '--formula-count': formulaColumns.length }} role="table" aria-label="Workflow tracking grid">
      <div className="workflow-sheet-grid-head" role="row"><span role="columnheader">Work item</span><span role="columnheader">Type</span>
        <span role="columnheader">Owner</span><span role="columnheader">Status</span><span role="columnheader">Priority</span>
        <span role="columnheader">Due / target</span><span role="columnheader">Workflow step</span>{formulaColumns.map((formula) => <span role="columnheader" key={formula}>{formulaLabel(formula)} <button aria-label={`Remove ${formulaLabel(formula)}`} onClick={() => { const next = formulaColumns.filter((value) => value !== formula); setFormulaColumns(next); localStorage.setItem(`flowforge:${currentUser?.id}:sheet-formulas`, JSON.stringify(next)); }}>×</button></span>)}</div>
      {renderedGroups.map((group) => {
        const groupItems = [...group.deliverables, ...group.tasks];
        const groupDone = groupItems.filter((item) => item.status === 'done').length;
        const isCollapsed = collapsed.has(group.id);
        return <React.Fragment key={group.id}><div className="workflow-sheet-group" role="row">
          <span role="cell"><button aria-label={`${isCollapsed ? 'Expand' : 'Collapse'} ${group.label}`} onClick={() => toggleGroup(group.id)}>{isCollapsed ? '▸' : '▾'}</button>
            <b>{String(group.index + 1).padStart(2, '0')}</b><strong>{group.label}</strong></span>
          <span role="cell"><em>step</em></span><span role="cell" /><span role="cell"><small>{groupDone}/{groupItems.length} complete</small></span>
          <span role="cell" /><span role="cell" /><span role="cell">{group.id !== 'project-wide' && <button onClick={() => onSelectNode(group.id)}>Open in diagram ↗</button>}</span>{formulaColumns.map((formula) => <span role="cell" key={formula}>—</span>)}
        </div>{!isCollapsed && group.deliverables.map((item) => <div className="workflow-sheet-row deliverable" role="row" key={`deliverable-${item.id}`}>
          <span role="cell"><i>◎</i><EditableName value={item.title} disabled={!canManage || !connected}
            ariaLabel={`Deliverable name ${item.title}`} onCommit={(title) => onUpdateDeliverable(item.id, { title })} /></span>
          <span role="cell"><em>deliverable</em></span><span role="cell">{ownerPicker(item, 'deliverable')}</span>
          <span role="cell"><select aria-label={`Sheet status for ${item.title}`} value={item.status} disabled={!canManage || !connected}
            onChange={(event) => onUpdateDeliverable(item.id, { status: event.target.value })}>
            {['planned', 'in_progress', 'blocked', 'done'].map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}</select></span>
          <span role="cell"><small>—</small></span><span role="cell"><input aria-label={`Target date for ${item.title}`} type="date" value={item.target_date || ''}
            disabled={!canManage || !connected} onChange={(event) => onUpdateDeliverable(item.id, { target_date: event.target.value })} /></span>
          <span role="cell"><select aria-label={`Workflow step for ${item.title}`} value={item.node_id || ''} disabled={!canManage || !connected}
            onChange={(event) => onUpdateDeliverable(item.id, { node_id: event.target.value })}><option value="">Project-wide</option>
            {nodes.map((node) => <option key={node.id} value={node.id}>{node.data?.label || node.id}</option>)}</select></span>{formulaColumns.map((formula) => <span className="formula-cell" role="cell" key={formula}>{formulaValue(item, formula)}</span>)}
        </div>)}{!isCollapsed && group.tasks.map((item) => <div className="workflow-sheet-row task" role="row" key={`task-${item.id}`}>
          <span role="cell"><i>✓</i><EditableName value={item.title} disabled={!canManage || !connected}
            ariaLabel={`Task name ${item.title}`} onCommit={(title) => onUpdateTask(item.id, { title })} /></span>
          <span role="cell"><em>task</em></span><span role="cell">{ownerPicker(item, 'task')}</span>
          <span role="cell"><select aria-label={`Sheet status for ${item.title}`} value={item.status} disabled={!canManage || !connected}
            onChange={(event) => onUpdateTask(item.id, { status: event.target.value })}>
            {['todo', 'in_progress', 'done'].map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}</select></span>
          <span role="cell"><select aria-label={`Priority for ${item.title}`} value={item.priority} disabled={!canManage || !connected}
            onChange={(event) => onUpdateTask(item.id, { priority: event.target.value })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></span>
          <span role="cell"><input aria-label={`Due date for ${item.title}`} type="date" value={item.due_date || ''} disabled={!canManage || !connected}
            onChange={(event) => onUpdateTask(item.id, { due_date: event.target.value })} /></span>
          <span role="cell"><select aria-label={`Workflow step for ${item.title}`} value={item.node_id || ''} disabled={!canManage || !connected}
            onChange={(event) => onUpdateTask(item.id, { node_id: event.target.value })}><option value="">Project-wide</option>
            {nodes.map((node) => <option key={node.id} value={node.id}>{node.data?.label || node.id}</option>)}</select></span>{formulaColumns.map((formula) => <span className="formula-cell" role="cell" key={formula}>{formulaValue(item, formula)}</span>)}
        </div>)}</React.Fragment>;
      })}
      {visibleGroups.length === 0 && <div className="workflow-sheet-empty"><span>▦</span><strong>No matching work</strong><p>Clear the filters or add the first tracked item below.</p></div>}
      {visibleGroups.length > renderedGroups.length && <button className="workflow-sheet-load-more" onClick={() => setVisibleGroupLimit((value) => value + 100)}>Load next 100 groups · {renderedGroups.length} of {visibleGroups.length}</button>}
    </div></div>
    {canManage && <form className="workflow-sheet-add" onSubmit={submit}><strong>＋ Add row</strong>
      <select aria-label="New sheet row type" value={draft.type} onChange={(event) => setDraftValue('type', event.target.value)}>
        <option value="task">Task</option><option value="deliverable">Deliverable</option></select>
      <input aria-label="New sheet row name" maxLength="160" value={draft.title} onChange={(event) => setDraftValue('title', event.target.value)} placeholder="Name the work item" />
      <UserSelect label="Owner" ariaLabel="New sheet row owner" users={members} value={draft.owner_id}
        onChange={(ownerId) => setDraftValue('owner_id', ownerId)} emptyLabel="Unassigned" />
      <select aria-label="New sheet row workflow step" value={draft.node_id} onChange={(event) => setDraftValue('node_id', event.target.value)}>
        <option value="">Project-wide</option>{nodes.map((node) => <option value={node.id} key={node.id}>{node.data?.label || node.id}</option>)}</select>
      <input aria-label="New sheet row due date" type="date" value={draft.due_date} onChange={(event) => setDraftValue('due_date', event.target.value)} />
      <button className="button primary" disabled={!draft.title.trim() || !connected}>Add</button></form>}
  </section>;
}
