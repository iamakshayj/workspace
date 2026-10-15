import React, { useEffect, useMemo, useState } from 'react';
import WorkspaceTopNav from './WorkspaceTopNav';
import { UserSelect } from './UserPicker';
import { getWorkspaceTeam } from './entityService';
import {
  addServiceTicketComment, createGuestGrant, createServiceTicket, getGuestGrants,
  getOnCallSchedules, getServiceTicketComments, getServiceTickets, revokeGuestGrant, updateServiceTicket,
} from './serviceDeskService';

const EMPTY = { title: '', description: '', ticket_type: 'request', severity: 'normal', priority: 'medium', service: 'workspace', assignee_id: '' };
const time = (value) => value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—';

export default function ServiceDesk({ user, onNavigate, navigationKey = '' }) {
  const [tickets, setTickets] = useState([]); const [summary, setSummary] = useState({ total: 0, open: 0, sla_breached: 0 });
  const [members, setMembers] = useState([]); const [selectedId, setSelectedId] = useState(() => new URLSearchParams(window.location.search).get('ticket') || ''); const [comments, setComments] = useState([]);
  const [onCall, setOnCall] = useState([]); const [grants, setGrants] = useState([]); const [form, setForm] = useState(EMPTY);
  const [comment, setComment] = useState(''); const [filter, setFilter] = useState(''); const [search, setSearch] = useState('');
  const [showCreate, setShowCreate] = useState(false); const [state, setState] = useState('loading'); const [error, setError] = useState('');
  const [guestEmail, setGuestEmail] = useState(''); const [guestLink, setGuestLink] = useState('');
  const selected = tickets.find((item) => item.id === selectedId) || null;

  const load = async () => {
    try {
      const [ticketResult, team, schedules, guestGrants] = await Promise.all([getServiceTickets({ status: filter, search }), getWorkspaceTeam(), getOnCallSchedules(), user.role === 'admin' ? getGuestGrants() : Promise.resolve([])]);
      setTickets(ticketResult.items); setSummary(ticketResult.summary); setMembers(team.workspace_members || []); setOnCall(schedules); setGrants(guestGrants); setState('ready');
    } catch (requestError) { setError(requestError.message); setState('error'); }
  };
  useEffect(() => { load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSelectedId(new URLSearchParams(navigationKey).get('ticket') || ''); }, [navigationKey]);
  useEffect(() => {
    if (!selectedId) { setComments([]); return; }
    getServiceTicketComments(selectedId).then(setComments).catch((requestError) => setError(requestError.message));
  }, [selectedId]);
  const memberUsers = useMemo(() => members.map((item) => item.user || item).filter(Boolean), [members]);

  const submitTicket = async (event) => {
    event.preventDefault(); setError('');
    try { const created = await createServiceTicket({ ...form, assignee_id: form.assignee_id || null }); setForm(EMPTY); setShowCreate(false); await load(); setSelectedId(created.id); }
    catch (requestError) { setError(requestError.message); }
  };
  const update = async (payload) => {
    try { const saved = await updateServiceTicket(selected.id, payload); setTickets((items) => items.map((item) => item.id === saved.id ? saved : item)); await load(); }
    catch (requestError) { setError(requestError.message); }
  };
  const submitComment = async (event) => {
    event.preventDefault(); if (!comment.trim()) return;
    try { const created = await addServiceTicketComment(selected.id, { body: comment, internal: false }); setComments((items) => [...items, created]); setComment(''); }
    catch (requestError) { setError(requestError.message); }
  };
  const share = async () => {
    if (!guestEmail.trim()) return;
    try { const result = await createGuestGrant({ guest_email: guestEmail, resource_type: 'ticket', resource_id: selected.id, permissions: ['view', 'comment'], expires_in_hours: 168 }); setGuestLink(result.url); setGuestEmail(''); await load(); }
    catch (requestError) { setError(requestError.message); }
  };

  return <main id="workspace-main" className="service-desk-shell">
    <WorkspaceTopNav active="service" onNavigate={onNavigate} role={user.role} actions={<button className="button primary" onClick={() => setShowCreate(true)}>+ New request</button>} />
    <section className="service-desk-page">
      <header className="service-desk-hero"><div><p className="eyebrow">Operations</p><h1>Service desk</h1><p>Requests, incidents, ownership, SLA commitments, and customer collaboration in one queue.</p></div>
        <div className="service-kpis"><article><strong>{summary.open}</strong><span>Open</span></article><article><strong>{summary.sla_breached}</strong><span>SLA breached</span></article><article><strong>{onCall.filter((item) => item.active).length}</strong><span>On-call rotations</span></article></div></header>
      {error && <div className="notice error"><strong>Couldn’t complete that action</strong><span>{error}</span></div>}
      <div className="service-toolbar"><label><span>Search</span><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') load(); }} placeholder="Title, service, or description" /></label>
        <label><span>Status</span><select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="">All statuses</option>{['open', 'triage', 'in_progress', 'waiting', 'resolved', 'closed'].map((value) => <option key={value} value={value}>{value.replace('_', ' ')}</option>)}</select></label><button className="button secondary" onClick={load}>Search</button></div>
      <div className="service-layout"><section className="service-queue" aria-label="Service tickets">
        {state === 'loading' && <p>Loading service queue…</p>}
        {state === 'ready' && !tickets.length && <div className="service-empty"><strong>No matching requests</strong><span>Create a request or change the filters.</span></div>}
        {tickets.map((item) => <button key={item.id} className={item.id === selectedId ? 'selected' : ''} onClick={() => setSelectedId(item.id)}><span className={`service-severity ${item.severity}`}>{item.severity}</span><span><strong>{item.title}</strong><small>{item.ticket_type} · {item.service} · {item.assignee?.display_name || 'Unassigned'}</small></span><span><b>{item.status.replace('_', ' ')}</b><small className={item.response_breached || item.resolution_breached ? 'breached' : ''}>{item.response_breached || item.resolution_breached ? 'SLA breached' : `Due ${time(item.resolution_due_at)}`}</small></span></button>)}</section>
        <aside className="service-detail">{selected ? <>
          <header><div><span className={`service-severity ${selected.severity}`}>{selected.severity}</span><h2>{selected.title}</h2><p>{selected.description || 'No description provided.'}</p></div><button aria-label="Close ticket details" onClick={() => setSelectedId('')}>×</button></header>
          <div className="service-fields"><label>Status<select value={selected.status} onChange={(event) => update({ status: event.target.value })}>{['open', 'triage', 'in_progress', 'waiting', 'resolved', 'closed'].map((value) => <option key={value}>{value}</option>)}</select></label><UserSelect label="Assignee" users={memberUsers} value={selected.assignee?.id || ''} onChange={(value) => update({ assignee_id: value })} emptyLabel="Unassigned" /><div><span>Response due</span><strong>{time(selected.response_due_at)}</strong></div><div><span>Resolution due</span><strong>{time(selected.resolution_due_at)}</strong></div></div>
          <section className="service-comments"><h3>Activity</h3>{comments.map((item) => <article key={item.id}><strong>{item.author?.display_name || item.external_author || 'Guest'}</strong><time>{time(item.created_at)}</time><p>{item.body}</p></article>)}<form onSubmit={submitComment}><textarea aria-label="Add ticket comment" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Add an update or ask a question" /><button className="button primary">Comment</button></form></section>
          {user.role === 'admin' && <section className="guest-share"><h3>External collaboration</h3><p>Create an audited, seven-day link limited to this ticket.</p><div><input type="email" aria-label="Guest email" value={guestEmail} onChange={(event) => setGuestEmail(event.target.value)} placeholder="customer@example.com" /><button className="button secondary" onClick={share}>Share</button></div>{guestLink && <label>One-time link<input readOnly value={guestLink} onFocus={(event) => event.target.select()} /></label>}{grants.filter((item) => item.resource_id === selected.id && !item.revoked_at).map((item) => <div className="guest-grant" key={item.id}><span>{item.guest_email}<small>Expires {time(item.expires_at)}</small></span><button onClick={async () => { await revokeGuestGrant(item.id); await load(); }}>Revoke</button></div>)}</section>}
        </> : <div className="service-empty"><strong>Select a request</strong><span>Review ownership, SLA status, discussion, and guest sharing.</span></div>}</aside></div>
    </section>
    {showCreate && <div className="enterprise-modal-backdrop"><form className="enterprise-modal" onSubmit={submitTicket}><header><h2>New service request</h2><button type="button" aria-label="Close new request" onClick={() => setShowCreate(false)}>×</button></header><div className="enterprise-form-grid"><label className="wide">Title<input required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label>Type<select value={form.ticket_type} onChange={(event) => setForm({ ...form, ticket_type: event.target.value })}>{['request', 'incident', 'problem', 'change'].map((value) => <option key={value}>{value}</option>)}</select></label><label>Severity<select value={form.severity} onChange={(event) => setForm({ ...form, severity: event.target.value })}>{['critical', 'high', 'normal', 'low'].map((value) => <option key={value}>{value}</option>)}</select></label><label>Service<input value={form.service} onChange={(event) => setForm({ ...form, service: event.target.value })} /></label><UserSelect label="Assignee" users={memberUsers} value={form.assignee_id} onChange={(value) => setForm({ ...form, assignee_id: value })} emptyLabel="Unassigned" /><label className="wide">Description<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label></div><footer><button type="button" className="button secondary" onClick={() => setShowCreate(false)}>Cancel</button><button className="button primary">Create request</button></footer></form></div>}
  </main>;
}
