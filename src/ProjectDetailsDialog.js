import React, { useEffect, useMemo, useState } from 'react';
import {
  decideProjectApproval,
  getProjectGovernance,
  requestProjectApproval,
  restoreProjectRevision,
  updateProjectGovernance,
} from './flowchartService';
import { UserMultiSelect, UserSelect } from './UserPicker';
import { getObjectHistory, getRelatedItems } from './workGraphService';

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || '?';
}

function formatDate(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  }).format(new Date(value));
}

function actionLabel(action = '') {
  return action.replace(/^project\./, '').replaceAll('_', ' ');
}

const ACCESS_OPTIONS = [
  ['none', 'No project role'],
  ['viewer', 'Viewer'],
  ['commenter', 'Commenter'],
  ['editor', 'Editor'],
  ['approver', 'Approver'],
];
const EMPTY_PROFILE = {
  key: '', sponsor_id: '', department: '', team: '', program: '', priority: 'medium',
  health: 'unknown', start_date: '', target_date: '', progress: '',
  classification: 'internal', tags: [], template: 'blank',
};
const PROJECT_TEMPLATES = [
  ['blank', 'Blank'], ['software', 'Software project'], ['general', 'General project'],
  ['research', 'Research project'], ['transformation', 'Transformation initiative'],
  ['infrastructure', 'Infrastructure project'], ['compliance', 'Compliance project'],
];

export default function ProjectDetailsDialog({
  open,
  onClose,
  onSave,
  canManage,
  currentUser,
  currentUserAccess = 'viewer',
  contacts = [],
  description = '',
  status = 'active',
  profile = EMPTY_PROFILE,
  ownerId,
  collaboratorIds = [],
  persisted = false,
  projectId = null,
  onGovernanceChange = () => {},
  onRestored = () => {},
}) {
  const [section, setSection] = useState('details');
  const [draft, setDraft] = useState({ description, status, owner_id: ownerId, collaborator_ids: collaboratorIds, profile: { ...EMPTY_PROFILE, ...profile } });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [governance, setGovernance] = useState(null);
  const [governanceState, setGovernanceState] = useState('idle');
  const [governanceDraft, setGovernanceDraft] = useState({ visibility: 'workspace', roles: {} });
  const [approvalNote, setApprovalNote] = useState('');
  const [decisionNote, setDecisionNote] = useState('');
  const [governanceSearch, setGovernanceSearch] = useState('');
  const [compareVersions, setCompareVersions] = useState([]);
  const [relatedDepth, setRelatedDepth] = useState(1);
  const [relatedState, setRelatedState] = useState('idle');
  const [relatedGraph, setRelatedGraph] = useState({ nodes: [], edges: [], truncated: false });
  const [objectHistory, setObjectHistory] = useState([]);

  const members = useMemo(() => {
    const all = [
      { ...currentUser, color: currentUser.color || '#5B4BE7' },
      ...contacts.map((contact) => contact.user || contact),
    ];
    return Array.from(new Map(all.filter((member) => member?.id).map((member) => [member.id, member])).values());
  }, [contacts, currentUser]);
  const filteredGovernanceMembers = useMemo(() => {
    const query = governanceSearch.trim().toLocaleLowerCase();
    if (!query) return members;
    return members.filter((member) => [member.display_name, member.email, member.handle, member.role]
      .filter(Boolean).join(' ').toLocaleLowerCase().includes(query));
  }, [governanceSearch, members]);

  const applyGovernance = (next) => {
    setGovernance(next);
    setGovernanceDraft({
      visibility: next.visibility,
      roles: Object.fromEntries(next.access_entries.map((entry) => [entry.user.id, entry.access_role])),
    });
    onGovernanceChange(next);
  };

  useEffect(() => {
    if (!open) return;
    setSection('details');
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const normalizedOwner = ownerId || currentUser.id;
    setDraft({
      description: description || '',
      status: status || 'active',
      owner_id: normalizedOwner,
      collaborator_ids: Array.from(new Set([...(collaboratorIds || []), normalizedOwner])),
      profile: { ...EMPTY_PROFILE, ...(profile || {}) },
    });
    setError('');
    setApprovalNote('');
    setDecisionNote('');
    setGovernanceSearch('');
    setCompareVersions([]);
  }, [collaboratorIds, currentUser.id, description, open, ownerId, profile, status]);

  useEffect(() => {
    if (!open || !persisted || !projectId) {
      setGovernance(null);
      setGovernanceState('idle');
      return;
    }
    let active = true;
    setGovernanceState('loading');
    getProjectGovernance(projectId)
      .then((next) => {
        if (!active) return;
        applyGovernance(next);
        setGovernanceState('ready');
      })
      .catch((requestError) => {
        if (!active) return;
        setError(requestError.message || 'Governance information could not be loaded.');
        setGovernanceState('error');
      });
    return () => { active = false; };
    // applyGovernance intentionally uses the latest callback without reloading for callback identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, persisted, projectId]);

  useEffect(() => {
    if (!open || !persisted || !projectId || section !== 'relationships') return undefined;
    let active = true;
    setRelatedState('loading');
    Promise.all([
      getRelatedItems('project', projectId, { depth: relatedDepth, direction: 'both', limit: 150 }),
      getObjectHistory('project', projectId, 30),
    ]).then(([graph, history]) => {
      if (!active) return;
      setRelatedGraph(graph); setObjectHistory(history.events || []); setRelatedState('ready');
    }).catch((requestError) => {
      if (!active) return;
      setError(requestError.message || 'Related items could not be loaded.'); setRelatedState('error');
    });
    return () => { active = false; };
  }, [open, persisted, projectId, relatedDepth, section]);

  if (!open) return null;

  const access = governance?.current_user_access || currentUserAccess;
  const canManageGovernance = ['admin', 'owner'].includes(access);
  const canRequestApproval = ['admin', 'owner', 'editor'].includes(access);
  const canApprove = ['admin', 'approver'].includes(access);

  const changeOwner = (nextOwnerId) => setDraft((current) => ({
    ...current,
    owner_id: nextOwnerId,
    collaborator_ids: Array.from(new Set([...current.collaborator_ids, nextOwnerId])),
  }));

  const submit = async (event) => {
    event.preventDefault();
    if (!canManage || saving) return;
    setSaving(true); setError('');
    try {
      await onSave({
        ...draft,
        description: draft.description.trim(),
        collaborator_ids: Array.from(new Set([...draft.collaborator_ids, draft.owner_id])),
        profile: {
          ...draft.profile,
          key: draft.profile.key.trim().toUpperCase(),
          sponsor_id: draft.profile.sponsor_id || null,
          start_date: draft.profile.start_date || null,
          target_date: draft.profile.target_date || null,
          progress: draft.profile.progress === '' ? null : Number(draft.profile.progress),
          tags: Array.isArray(draft.profile.tags) ? draft.profile.tags : draft.profile.tags.split(',').map((tag) => tag.trim()).filter(Boolean),
        },
      });
      onClose();
    } catch (requestError) {
      setError(requestError.message || 'Project details could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const runGovernanceAction = async (action) => {
    if (saving) return;
    setSaving(true); setError('');
    try {
      const result = await action();
      applyGovernance(result);
      setApprovalNote('');
      setDecisionNote('');
    } catch (requestError) {
      setError(requestError.message || 'The governance action could not be completed.');
    } finally {
      setSaving(false);
    }
  };

  const saveGovernance = () => runGovernanceAction(() => updateProjectGovernance(
    projectId,
    governanceDraft.visibility,
    members
      .map((member) => ({ user_id: member.id, access_role: governanceDraft.roles[member.id] || 'none' }))
      .filter((entry) => entry.access_role !== 'none'),
  ));

  const restoreRevision = async (revision) => {
    if (saving) return;
    setSaving(true); setError('');
    try {
      const project = await restoreProjectRevision(projectId, revision.id);
      onRestored(project);
      const next = await getProjectGovernance(projectId);
      applyGovernance(next);
    } catch (requestError) {
      setError(requestError.message || 'The revision could not be restored.');
    } finally {
      setSaving(false);
    }
  };

  return <div className="project-details-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section className="project-details-dialog governance-dialog" role="dialog" aria-modal="true" aria-label="Project details">
      <header><div><p className="eyebrow">Workflow workspace</p><h2>Project details</h2>
        <p>Ownership, access, approval, and change history in one place.</p></div>
        <button className="icon-button" aria-label="Close project details" onClick={onClose}>×</button></header>
      <nav className="project-details-tabs" aria-label="Project detail sections">
        <button className={section === 'details' ? 'active' : ''} onClick={() => setSection('details')}>Details</button>
        <button className={section === 'planning' ? 'active' : ''} onClick={() => setSection('planning')}>Planning</button>
        <button className={section === 'governance' ? 'active' : ''} disabled={!persisted}
          onClick={() => setSection('governance')}>Governance{persisted && governance && <span>{governance.approval_status}</span>}</button>
        <button className={section === 'relationships' ? 'active' : ''} disabled={!persisted}
          onClick={() => setSection('relationships')}>Related items</button>
      </nav>

      {section === 'details' && <form onSubmit={submit}>
        <div className="project-details-grid">
          <label className="project-description-field">Description
            <textarea aria-label="Project description" maxLength="2000" disabled={!canManage}
              value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
              placeholder="What process does this workflow document, and when should the team use it?" />
            <small>{draft.description.length}/2000</small>
          </label>
          <label>Status
            <select aria-label="Project status" disabled={!canManage} value={draft.status}
              onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value }))}>
              <option value="draft">Draft</option><option value="active">Active</option><option value="archived">Archived</option>
            </select>
            <small>Draft for work in progress, active for current processes, archived for historical reference.</small>
          </label>
          <div className="project-owner-field"><UserSelect label="Owner" ariaLabel="Project owner" disabled={!canManage}
            users={members} value={draft.owner_id} onChange={changeOwner} />
            <small>The accountable person. Owners are always included as collaborators.</small>
          </div>
        </div>
        <section className="project-collaborators">
          <p>People actively contributing to this workflow. Their exact access role is set under Governance.</p>
          <UserMultiSelect label="Collaborators" ariaLabel="Project collaborators" users={members}
            disabled={!canManage} value={draft.collaborator_ids}
            requiredIds={draft.owner_id ? [draft.owner_id] : []}
            onChange={(collaboratorIds) => setDraft((current) => ({ ...current, collaborator_ids: collaboratorIds }))} />
        </section>
        {error && <div className="notice error" role="alert">{error}</div>}
        <footer><span>{persisted ? 'Changes create a new saved revision.' : 'Details will be stored when the workflow is first saved.'}</span>
          <div><button type="button" className="button secondary" onClick={onClose}>{canManage ? 'Cancel' : 'Done'}</button>
            {canManage && <button className="button primary" disabled={saving}>{saving ? 'Saving…' : persisted ? 'Save details' : 'Apply details'}</button>}</div></footer>
      </form>}

      {section === 'planning' && <form onSubmit={submit} className="project-planning-form">
        <div className="project-profile-summary">
          <span><small>Health</small><strong className={`project-health ${draft.profile.health}`}>{draft.profile.health.replaceAll('_', ' ')}</strong></span>
          <span><small>Priority</small><strong>{draft.profile.priority}</strong></span>
          <span><small>Progress</small><strong>{draft.profile.progress === '' || draft.profile.progress == null ? 'Auto' : `${draft.profile.progress}%`}</strong></span>
          <span><small>Classification</small><strong>{draft.profile.classification}</strong></span>
        </div>
        <div className="project-planning-grid">
          <label>Project key<input maxLength="20" disabled={!canManage} value={draft.profile.key}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, key: event.target.value.toUpperCase().replace(/[^A-Z0-9-]/g, '') } }))}
            placeholder="OPS-2026" /></label>
          <label>Template<select disabled={!canManage} value={draft.profile.template}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, template: event.target.value } }))}>
            {PROJECT_TEMPLATES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <UserSelect label="Sponsor" ariaLabel="Project sponsor" disabled={!canManage} users={members}
            value={draft.profile.sponsor_id || ''} emptyLabel="No sponsor"
            onChange={(sponsorId) => setDraft((current) => ({ ...current, profile: { ...current.profile, sponsor_id: sponsorId } }))} />
          <label>Program<input maxLength="160" disabled={!canManage} value={draft.profile.program}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, program: event.target.value } }))} placeholder="Customer operations" /></label>
          <label>Department<input maxLength="120" disabled={!canManage} value={draft.profile.department}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, department: event.target.value } }))} placeholder="Operations" /></label>
          <label>Team<input maxLength="120" disabled={!canManage} value={draft.profile.team}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, team: event.target.value } }))} placeholder="Service delivery" /></label>
          <label>Priority<select disabled={!canManage} value={draft.profile.priority}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, priority: event.target.value } }))}>
            <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label>
          <label>Health<select disabled={!canManage} value={draft.profile.health}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, health: event.target.value } }))}>
            <option value="unknown">Not reported</option><option value="on_track">On track</option><option value="at_risk">At risk</option><option value="off_track">Off track</option></select></label>
          <label>Start date<input type="date" disabled={!canManage} value={draft.profile.start_date || ''}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, start_date: event.target.value } }))} /></label>
          <label>Target date<input type="date" disabled={!canManage} min={draft.profile.start_date || undefined} value={draft.profile.target_date || ''}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, target_date: event.target.value } }))} /></label>
          <label>Progress<input type="number" min="0" max="100" disabled={!canManage} value={draft.profile.progress ?? ''}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, progress: event.target.value } }))} placeholder="Auto from work" /></label>
          <label>Classification<select disabled={!canManage} value={draft.profile.classification}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, classification: event.target.value } }))}>
            <option value="public">Public</option><option value="internal">Internal</option><option value="confidential">Confidential</option><option value="restricted">Restricted</option></select></label>
          <label className="project-tags-field">Tags<input aria-label="Project tags" maxLength="500" disabled={!canManage}
            value={Array.isArray(draft.profile.tags) ? draft.profile.tags.join(', ') : draft.profile.tags}
            onChange={(event) => setDraft((current) => ({ ...current, profile: { ...current.profile, tags: event.target.value } }))}
            placeholder="automation, customer, compliance" /><small>Comma separated; up to 20 tags.</small></label>
        </div>
        {error && <div className="notice error" role="alert">{error}</div>}
        <footer><span>Planning metadata is included in revision history and approval evidence.</span><div>
          <button type="button" className="button secondary" onClick={onClose}>{canManage ? 'Cancel' : 'Done'}</button>
          {canManage && <button className="button primary" disabled={saving}>{saving ? 'Saving…' : persisted ? 'Save planning' : 'Apply planning'}</button>}
        </div></footer>
      </form>}

      {section === 'governance' && <div className="governance-body">
        {governanceState === 'loading' && <div className="governance-loading">Loading governance controls…</div>}
        {governance && <>
          <div className="governance-summary">
            <div><span>Approval</span><strong className={`approval-state ${governance.approval_status}`}>{governance.approval_status.replace('_', ' ')}</strong></div>
            <div><span>Current revision</span><strong>v{governance.current_revision}</strong></div>
            <div><span>Your access</span><strong>{governance.current_user_access}</strong></div>
            <div><span>Visibility</span><strong>{governance.visibility}</strong></div>
          </div>

          <section className="governance-card">
            <div className="governance-card-heading"><div><h3>Access</h3><p>Workspace visibility and explicit project roles are enforced by the API.</p></div>
              {canManageGovernance && <button className="button secondary compact" disabled={saving} onClick={saveGovernance}>Save access</button>}</div>
            <label className="visibility-control">Visibility
              <select aria-label="Project visibility" disabled={!canManageGovernance} value={governanceDraft.visibility}
                onChange={(event) => setGovernanceDraft((current) => ({ ...current, visibility: event.target.value }))}>
                <option value="workspace">Workspace — every member can view</option>
                <option value="restricted">Restricted — explicit members only</option>
              </select>
            </label>
            <label className="governance-member-search">Find a workspace member
              <input type="search" value={governanceSearch} onChange={(event) => setGovernanceSearch(event.target.value)}
                placeholder="Search name, email, username, or role…" />
            </label>
            <div className="governance-access-list">{filteredGovernanceMembers.map((member) => {
              const isOwner = member.id === ownerId;
              return <div key={member.id}>
                <span className="project-member-avatar" style={{ '--avatar-color': member.color || '#667085' }}>{initials(member.display_name)}</span>
                <span><strong>{member.display_name}</strong><small>{member.email}</small></span>
                <select aria-label={`Project access for ${member.display_name}`} disabled={!canManageGovernance || isOwner}
                  value={isOwner ? 'editor' : governanceDraft.roles[member.id] || 'none'}
                  onChange={(event) => setGovernanceDraft((current) => ({
                    ...current, roles: { ...current.roles, [member.id]: event.target.value },
                  }))}>
                  {ACCESS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{isOwner && value === 'editor' ? 'Owner' : label}</option>)}
                </select>
              </div>;
            })}{filteredGovernanceMembers.length === 0 && <p className="governance-no-members">No workspace members match your search.</p>}</div>
          </section>

          <section className="governance-card approval-card">
            <div className="governance-card-heading"><div><h3>Approval</h3><p>Decisions apply to a specific immutable revision.</p></div></div>
            {governance.approval && <div className="approval-record">
              <strong>Revision v{governance.approval.revision_version} · {governance.approval.status.replace('_', ' ')}</strong>
              <span>Requested by {governance.approval.requested_by.display_name} {formatDate(governance.approval.requested_at)}</span>
              {governance.approval.request_note && <p>{governance.approval.request_note}</p>}
              {governance.approval.reviewer && <span>Decided by {governance.approval.reviewer.display_name}</span>}
              {governance.approval.decision_note && <p>{governance.approval.decision_note}</p>}
            </div>}
            {governance.approval_status !== 'pending' && canRequestApproval && <div className="approval-actions">
              <textarea aria-label="Approval request note" maxLength="2000" value={approvalNote}
                onChange={(event) => setApprovalNote(event.target.value)} placeholder="Optional context for the approver" />
              <button className="button primary" disabled={saving}
                onClick={() => runGovernanceAction(() => requestProjectApproval(projectId, approvalNote))}>Request approval</button>
            </div>}
            {governance.approval_status === 'pending' && canApprove && <div className="approval-actions">
              <textarea aria-label="Approval decision note" maxLength="2000" value={decisionNote}
                onChange={(event) => setDecisionNote(event.target.value)} placeholder="Decision note; required when requesting changes" />
              <div><button className="button secondary" disabled={saving || !decisionNote.trim()}
                onClick={() => runGovernanceAction(() => decideProjectApproval(projectId, 'changes_requested', decisionNote))}>Request changes</button>
                <button className="button primary" disabled={saving}
                  onClick={() => runGovernanceAction(() => decideProjectApproval(projectId, 'approved', decisionNote))}>Approve revision</button></div>
            </div>}
          </section>

          <div className="governance-columns">
            <section className="governance-card"><div className="governance-card-heading"><div><h3>Revision history</h3><p>Restoring creates a new version.</p></div></div>
              {governance.revisions.length > 1 && <div className="revision-compare"><strong>Compare versions</strong><select aria-label="Compare older revision" value={compareVersions[0] || ''} onChange={(event) => setCompareVersions([event.target.value, compareVersions[1] || ''])}><option value="">Older…</option>{governance.revisions.map((revision) => <option key={revision.id} value={revision.id}>v{revision.version}</option>)}</select><select aria-label="Compare newer revision" value={compareVersions[1] || ''} onChange={(event) => setCompareVersions([compareVersions[0] || '', event.target.value])}><option value="">Newer…</option>{governance.revisions.map((revision) => <option key={revision.id} value={revision.id}>v{revision.version}</option>)}</select>{compareVersions.every(Boolean) && (() => { const older = governance.revisions.find((revision) => revision.id === compareVersions[0]); const newer = governance.revisions.find((revision) => revision.id === compareVersions[1]); return older && newer ? <span><b>{newer.node_count - older.node_count >= 0 ? '+' : ''}{newer.node_count - older.node_count} nodes</b><b>{newer.edge_count - older.edge_count >= 0 ? '+' : ''}{newer.edge_count - older.edge_count} connections</b><b>{older.status} → {newer.status}</b></span> : null; })()}</div>}
              <div className="governance-timeline">{governance.revisions.map((revision) => <div key={revision.id}>
                <span className="timeline-dot" /><span><strong>v{revision.version} · {revision.change_summary}</strong>
                  <small>{revision.created_by.display_name} · {formatDate(revision.created_at)}</small></span>
                {canManageGovernance && revision.version !== governance.current_revision && <button disabled={saving}
                  onClick={() => restoreRevision(revision)}>Restore</button>}
              </div>)}</div>
            </section>
            <section className="governance-card"><div className="governance-card-heading"><div><h3>Audit activity</h3><p>Recent governance events.</p></div></div>
              <div className="governance-timeline audit-timeline">{governance.audit_events.map((event) => <div key={event.id}>
                <span className="timeline-dot" /><span><strong>{actionLabel(event.action)}</strong>
                  <small>{event.actor?.display_name || 'System'} · {formatDate(event.created_at)}</small></span>
              </div>)}</div>
            </section>
          </div>
        </>}
        {error && <div className="notice error" role="alert">{error}</div>}
        <footer><span>Governance records remain attached to this workflow.</span>
          <button className="button secondary" onClick={onClose}>Done</button></footer>
      </div>}

      {section === 'relationships' && <div className="project-relationships-body">
        <header><div><h3>Enterprise work graph</h3><p>Every item connected to this project, filtered to what you are allowed to view.</p></div>
          <label>Traversal depth<select aria-label="Project relationship depth" value={relatedDepth}
            onChange={(event) => setRelatedDepth(Number(event.target.value))}>
            <option value="1">Direct links</option><option value="2">2 hops</option><option value="3">3 hops</option><option value="4">4 hops</option><option value="5">5 hops</option>
          </select></label></header>
        {relatedState === 'loading' && <div className="governance-loading">Loading permission-filtered relationships…</div>}
        {relatedState === 'ready' && <div className="project-relationship-layout">
          <section><header><h4>Related objects</h4><span>{relatedGraph.nodes.length}</span></header>
            <div className="project-related-list">{relatedGraph.nodes.map((item) => <a href={item.url} key={`${item.type}:${item.id}`}>
              <span>{item.depth}</span><div><strong>{item.title}</strong><small>{item.type.replaceAll('_', ' ')}{item.status ? ` · ${item.status.replaceAll('_', ' ')}` : ''}</small></div><b>›</b>
            </a>)}{!relatedGraph.nodes.length && <p>No related objects are visible to you.</p>}</div>
            {relatedGraph.truncated && <p className="relationship-truncated">Additional objects were omitted. Reduce the traversal depth or filter relationship types through the API.</p>}
          </section>
          <section><header><h4>Relationship history</h4><span>{objectHistory.length}</span></header>
            <div className="project-relationship-history">{objectHistory.map((item) => <article key={item.id}><i /><div><strong>{item.action.replaceAll('.', ' ')}</strong><small>{formatDate(item.created_at)}</small></div></article>)}
              {!objectHistory.length && <p>No relationship changes have been recorded yet.</p>}</div>
          </section>
        </div>}
        {error && <div className="notice error" role="alert">{error}</div>}
        <footer><span>Incoming and outgoing links share the same canonical graph record.</span><button className="button secondary" onClick={onClose}>Done</button></footer>
      </div>}
    </section>
  </div>;
}
