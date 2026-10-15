import React, { useEffect, useMemo, useState } from 'react';
import {
  applyChangeProposal, createChangeProposal, decideChangeProposal,
  getChangeProposals, rollbackChangeProposal,
} from './changeProposalService';

const RELATIONSHIPS = ['parent_of', 'blocks', 'depends_on', 'supports', 'related_to', 'documented_by', 'discussed_in'];
const TARGET_TYPES = ['work_item', 'project', 'document', 'meeting', 'risk', 'decision', 'release', 'sprint'];

function dateLabel(value) {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(value));
}

function key() {
  return `graph:${window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
}

function ProposalCard({ item, busy, onAction }) {
  const changes = item.preview?.changes || [];
  return <article className="change-proposal-card">
    <header><div><span className={`change-proposal-status ${item.status}`}>{item.status.replaceAll('_', ' ')}</span><h3>{item.title}</h3></div><time>{dateLabel(item.updated_at)}</time></header>
    <p>{item.rationale || 'No rationale supplied.'}</p>
    <div className="change-proposal-preview">{changes.map((change, index) => <div key={`${change.action}-${index}`}>
      <b>{change.action}</b><span>{change.source.title}</span><code>{change.relationship_type}</code><span>{change.target.title}</span>
    </div>)}</div>
    <footer><span>Proposed by <b>{item.created_by.display_name}</b>{item.reviewed_by ? ` · reviewed by ${item.reviewed_by.display_name}` : ''} · {item.evidence.length} evidence source{item.evidence.length === 1 ? '' : 's'}</span>
      <div>{item.can_review && <><button disabled={busy} onClick={() => onAction('approved', item)}>Approve</button><button className="danger" disabled={busy} onClick={() => onAction('rejected', item)}>Reject</button></>}
        {item.can_apply && <button disabled={busy} onClick={() => onAction('apply', item)}>Apply approved change</button>}
        {item.can_rollback && <button className="secondary" disabled={busy} onClick={() => onAction('rollback', item)}>Roll back</button>}</div>
    </footer>
  </article>;
}

export default function ChangeProposalPanel({ projects = [], selectedProjectId = '', overview = {}, workItems = [] }) {
  const [items, setItems] = useState([]);
  const [state, setState] = useState('loading');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);
  const [form, setForm] = useState({
    title: '', rationale: '', source_id: selectedProjectId || projects[0]?.id || '',
    target_type: 'project', target_id: '', relationship_type: 'supports',
  });
  const targetCatalog = useMemo(() => ({
    project: projects.map((item) => ({ id: item.id, label: item.title })),
    work_item: workItems.map((item) => ({ id: item.id, label: `${item.key || 'Work'} · ${item.summary || item.title}` })),
    risk: (overview.risks || []).map((item) => ({ id: item.id, label: item.title })),
    decision: (overview.decisions || []).map((item) => ({ id: item.id, label: item.title })),
    meeting: (overview.meetings || []).map((item) => ({ id: item.id, label: item.title })),
  }), [overview.decisions, overview.meetings, overview.risks, projects, workItems]);
  const availableTargetTypes = TARGET_TYPES.filter((type) => targetCatalog[type]?.length);
  const targetOptions = targetCatalog[form.target_type] || [];

  const load = async () => {
    setState('loading');
    try { const result = await getChangeProposals(); setItems(result.items || []); setState('ready'); }
    catch (requestError) { setError(requestError.message); setState('error'); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (selectedProjectId) setForm((current) => ({ ...current, source_id: selectedProjectId }));
  }, [selectedProjectId]);

  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await createChangeProposal({
        title: form.title, rationale: form.rationale, idempotency_key: key(), evidence: [],
        operations: [{
          action: 'create', source_type: 'project', source_id: form.source_id,
          target_type: form.target_type, target_id: form.target_id,
          relationship_type: form.relationship_type, metadata: { proposed_from: 'governance_center' },
        }],
      });
      setCreating(false); setForm((current) => ({ ...current, title: '', rationale: '', target_id: '' })); await load();
    } catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };

  const act = async () => {
    if (!pendingAction) return;
    const { action, item } = pendingAction;
    setBusy(true); setError('');
    try {
      if (action === 'approved' || action === 'rejected') await decideChangeProposal(item.id, action);
      if (action === 'apply') await applyChangeProposal(item.id);
      if (action === 'rollback') await rollbackChangeProposal(item.id);
      setPendingAction(null);
      await load();
    } catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  };

  const actionCopy = pendingAction && ({
    approved: ['Approve this proposal?', 'Approval makes this graph change eligible to be applied.'],
    rejected: ['Reject this proposal?', 'The proposal will remain in the audit history and will not be applied.'],
    apply: ['Apply this graph change?', 'This updates canonical relationships and can affect related-item views across the workspace.'],
    rollback: ['Roll back this graph change?', 'This reverses the applied relationship change and records the rollback.'],
  }[pendingAction.action]);

  return <section className="change-proposal-panel">
    <header><div><p className="eyebrow">Controlled execution</p><h2>Governed graph changes</h2><p>Preview, independently approve, safely apply, and reverse canonical relationship changes.</p></div><button className="button primary" onClick={() => setCreating((value) => !value)}>{creating ? 'Close' : '+ Propose change'}</button></header>
    {error && <div className="notice error" role="alert"><strong>Change not completed</strong><span>{error}</span></div>}
    {creating && <form className="change-proposal-form" onSubmit={submit}>
      <label>Proposal title<input required minLength="3" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="Connect launch work to delivery workflow" /></label>
      <label>Rationale<textarea value={form.rationale} onChange={(event) => setForm({ ...form, rationale: event.target.value })} placeholder="Why this change is needed and what evidence supports it" /></label>
      <div><label>Source workflow<select required value={form.source_id} onChange={(event) => setForm({ ...form, source_id: event.target.value })}><option value="">Select workflow</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>
        <label>Relationship<select value={form.relationship_type} onChange={(event) => setForm({ ...form, relationship_type: event.target.value })}>{RELATIONSHIPS.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></label></div>
      <div><label>Target type<select value={form.target_type} onChange={(event) => setForm({ ...form, target_type: event.target.value, target_id: '' })}>{availableTargetTypes.map((value) => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}</select></label>
        <label>Target<select required value={form.target_id} onChange={(event) => setForm({ ...form, target_id: event.target.value })}><option value="">Select an item</option>{targetOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label></div>
      <footer><small>Submitting creates a review request only. It does not modify the graph.</small><button className="button primary" disabled={busy || !form.source_id || !form.target_id}>{busy ? 'Submitting…' : 'Submit for review'}</button></footer>
    </form>}
    {state === 'loading' && <div className="enterprise-loading">Loading governed changes…</div>}
    {state === 'ready' && !items.length && <div className="enterprise-empty"><h3>No graph changes awaiting governance</h3><p>Proposals and their full execution history will appear here.</p></div>}
    <div className="change-proposal-list">{items.map((item) => <ProposalCard key={item.id} item={item} busy={busy} onAction={(action, proposal) => setPendingAction({ action, item: proposal })} />)}</div>
    {pendingAction && <div className="enterprise-modal-backdrop"><section className="enterprise-modal compact" role="dialog" aria-modal="true" aria-labelledby="change-action-title">
      <header><div><p className="eyebrow">Confirm governed action</p><h2 id="change-action-title">{actionCopy[0]}</h2></div><button type="button" aria-label="Close confirmation" onClick={() => setPendingAction(null)}>×</button></header>
      <p>{actionCopy[1]}</p><div className="change-confirm-summary"><strong>{pendingAction.item.title}</strong><span>Status: {pendingAction.item.status.replaceAll('_', ' ')}</span></div>
      <footer><button type="button" className="button secondary" disabled={busy} onClick={() => setPendingAction(null)}>Cancel</button><button type="button" className={`button ${pendingAction.action === 'rejected' || pendingAction.action === 'rollback' ? 'danger' : 'primary'}`} disabled={busy} onClick={act}>{busy ? 'Working…' : actionCopy[0].replace('?', '')}</button></footer>
    </section></div>}
  </section>;
}
