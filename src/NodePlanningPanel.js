import React, { useMemo, useState } from 'react';
import { createNodeWorkItem, updateNodePlanning } from './workService';
import { UserSelect } from './UserPicker';

const DELIVERY_TYPES = ['epic', 'story', 'task', 'bug', 'milestone'];

function itemLabel(item) {
  return `${item.key} · ${item.summary}`;
}

function PlanningProgress({ plan }) {
  if (!plan?.item_count) return <p className="node-plan-empty-copy">No delivery work has been added yet.</p>;
  return <div className="node-plan-progress" aria-label={`${plan.progress}% complete`}>
    <span><strong>{plan.progress}% complete</strong><small>{plan.done_count}/{plan.item_count} items · {plan.done_points}/{plan.total_points || 0} points</small></span>
    <i><b style={{ width: `${plan.progress}%` }} /></i>
  </div>;
}

export default function NodePlanningPanel({ projectId, node, planning, canManage, onPlanningChange, onNavigate }) {
  const plan = planning?.nodes?.[node.id] || null;
  const primary = plan?.primary_item || null;
  const [createMode, setCreateMode] = useState(null);
  const [createType, setCreateType] = useState('epic');
  const [summary, setSummary] = useState(node.data?.label || '');
  const [storyPoints, setStoryPoints] = useState('');
  const [assigneeId, setAssigneeId] = useState('');
  const [existingId, setExistingId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const availableItems = useMemo(() => (planning?.items || []).filter((item) => item.id !== primary?.id), [planning?.items, primary?.id]);
  const childItems = (plan?.items || []).filter((item) => item.id !== primary?.id);

  const changeBinding = async (changes) => {
    if (!projectId || !canManage) return;
    setBusy(true); setError('');
    try {
      const next = await updateNodePlanning(projectId, node.id, {
        expected_revision: plan?.revision || 0,
        ...changes,
      });
      onPlanningChange(next);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  const startCreate = (mode, type) => {
    setCreateMode(mode); setCreateType(type); setSummary(mode === 'child' ? '' : node.data?.label || ''); setStoryPoints(''); setAssigneeId(''); setError('');
  };

  const createItem = async (event) => {
    event.preventDefault();
    if (!summary.trim() || !projectId) return;
    setBusy(true); setError('');
    try {
      const next = await createNodeWorkItem(projectId, node.id, {
        summary: summary.trim(), item_type: createType, priority: 'medium',
        description: node.data?.description || '', acceptance_criteria: '',
        assignee_id: assigneeId || null,
        parent_id: createMode === 'child' ? primary?.id || null : null,
        story_points: storyPoints === '' ? null : Number(storyPoints),
        due_date: null, set_primary: createMode !== 'child',
      });
      onPlanningChange(next); setCreateMode(null); setSummary(node.data?.label || '');
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  if (!projectId) return <details className="inspector-section node-planning-section" open>
    <summary>Delivery planning</summary>
    <div className="node-plan-unsaved"><span>◇</span><strong>Save this workflow first</strong><p>Saved nodes can own epics, stories, sprints, and sub-workflows.</p></div>
  </details>;

  if (!planning) return <details className="inspector-section node-planning-section" open>
    <summary>Delivery planning</summary><div className="node-plan-loading">Loading delivery context…</div>
  </details>;

  if (planning.error) return <details className="inspector-section node-planning-section" open>
    <summary>Delivery planning</summary><div className="node-plan-error" role="alert">{planning.error}</div>
  </details>;

  if (planning && !plan) return <details className="inspector-section node-planning-section" open>
    <summary>Delivery planning</summary>
    <div className="node-plan-unsaved"><span>↻</span><strong>Save the canvas to plan this node</strong><p>This new step must be saved before it can own delivery work.</p></div>
  </details>;

  return <details className="inspector-section node-planning-section" open>
    <summary>Delivery planning {plan?.planning_kind && <span className={`node-plan-kind ${plan.planning_kind}`}>{plan.planning_kind}</span>}</summary>
    {error && <div className="node-plan-error" role="alert">{error}</div>}
    {primary ? <div className="node-plan-primary">
      <button type="button" onClick={() => onNavigate(`/work?project=${projectId}&node=${node.id}&item=${primary.id}`)}>
        <span className={`node-plan-type ${primary.item_type}`}>{primary.item_type}</span>
        <strong>{primary.key} · {primary.summary}</strong><small>{primary.status.replace('_', ' ')} · Open in Work ↗</small>
      </button>
      <PlanningProgress plan={plan} />
      {canManage && <button type="button" className="node-plan-text-button" disabled={busy} onClick={() => changeBinding({ primary_work_item_id: null })}>Clear primary selection</button>}
    </div> : <div className="node-plan-empty">
      <p>Make this step part of delivery work. Its status will update directly on the canvas.</p>
      {canManage && <div className="node-plan-create-buttons">
        <button type="button" onClick={() => startCreate('primary', 'epic')}>＋ Epic</button>
        <button type="button" onClick={() => startCreate('primary', 'story')}>＋ Story</button>
        <button type="button" onClick={() => startCreate('primary', 'task')}>＋ Task</button>
      </div>}
    </div>}

    {createMode && <form className="node-plan-create-form" onSubmit={createItem}>
      <div><label>Type<select value={createType} onChange={(event) => setCreateType(event.target.value)}>{(createMode === 'child' ? ['story', 'task', 'bug'] : DELIVERY_TYPES).map((type) => <option key={type}>{type}</option>)}</select></label>
        <label>Points<input type="number" min="0" value={storyPoints} onChange={(event) => setStoryPoints(event.target.value)} placeholder="5" /></label></div>
      <label>Summary<input autoFocus required maxLength="180" value={summary} onChange={(event) => setSummary(event.target.value)} placeholder={createMode === 'child' ? 'What must be delivered?' : 'Delivery outcome'} /></label>
      <UserSelect label="Assignee" ariaLabel="Node work assignee" users={planning?.members || []}
        value={assigneeId} onChange={setAssigneeId} emptyLabel="Unassigned" />
      <footer><button type="button" onClick={() => setCreateMode(null)}>Cancel</button><button className="button primary" disabled={busy || !summary.trim()}>{busy ? 'Creating…' : `Create ${createType}`}</button></footer>
    </form>}

    {primary?.item_type === 'epic' && <section className="node-plan-children">
      <header><span><strong>Epic scope</strong><small>{childItems.length} linked stories, tasks, and subtasks</small></span>{canManage && !createMode && <button type="button" onClick={() => startCreate('child', 'story')}>＋ Add story</button>}</header>
      {childItems.slice(0, 5).map((item) => <button type="button" key={item.id} onClick={() => onNavigate(`/work?project=${projectId}&node=${node.id}&item=${item.id}`)}><i className={item.status} /><span><strong>{item.key}</strong>{item.summary}</span><small>{item.story_points ?? '—'} pt</small></button>)}
      {childItems.length > 5 && <small className="node-plan-more">+{childItems.length - 5} more in Work</small>}
    </section>}

    {canManage && !primary && !createMode && <div className="node-plan-link-existing">
      <label>Or link existing work<select value={existingId} onChange={(event) => setExistingId(event.target.value)}><option value="">Choose an epic, story, or task…</option>{availableItems.map((item) => <option key={item.id} value={item.id}>{itemLabel(item)}</option>)}</select></label>
      <button type="button" disabled={!existingId || busy} onClick={() => changeBinding({ primary_work_item_id: existingId })}>Link</button>
    </div>}

    <section className="node-plan-context">
      <label>Sprint context<select disabled={!canManage || busy} value={plan?.sprint?.id || ''} onChange={(event) => changeBinding({ sprint_id: event.target.value || null })}>
        <option value="">No sprint represented</option>{(planning?.sprints || []).filter((sprint) => !['completed', 'cancelled'].includes(sprint.status) || sprint.id === plan?.sprint?.id).map((sprint) => <option key={sprint.id} value={sprint.id}>{sprint.name} · {sprint.progress}%</option>)}
      </select></label>
      {plan?.sprint && <small>{plan.sprint.done_count}/{plan.sprint.item_count} sprint items complete</small>}
      <label>Sub-workflow<select disabled={!canManage || busy} value={plan?.subflow?.id || ''} onChange={(event) => changeBinding({ subflow_project_id: event.target.value || null })}>
        <option value="">No child workflow</option>{(planning?.projects || []).map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}
      </select></label>
      {plan?.subflow && <button type="button" className="node-plan-open-subflow" onClick={() => onNavigate(`/projects/${plan.subflow.id}`)}>Open {plan.subflow.title} ↗</button>}
    </section>
    {(primary || plan?.sprint || plan?.subflow) && <button type="button" className="button secondary node-plan-open-work" onClick={() => onNavigate(`/work?tab=stories&project=${projectId}&node=${node.id}${primary ? `&item=${primary.id}` : ''}`)}>View story hierarchy in Work</button>}
  </details>;
}
