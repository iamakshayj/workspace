import React, { useEffect, useState } from 'react';
import { API_BASE_URL } from './apiClient';

async function guestRequest(token, path = '', options = {}) {
  const response = await fetch(`${API_BASE_URL}/api/v1/public/guest/${encodeURIComponent(token)}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'This shared link is unavailable.');
  return payload;
}

function formatDate(value) {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—';
}

export default function GuestPortal({ token }) {
  const [data, setData] = useState(null);
  const [state, setState] = useState('loading');
  const [error, setError] = useState('');
  const [comment, setComment] = useState('');
  const [sending, setSending] = useState(false);
  const [success, setSuccess] = useState('');

  const load = () => {
    setState('loading'); setError('');
    guestRequest(token).then((result) => { setData(result); setState('ready'); })
      .catch((requestError) => { setError(requestError.message); setState('error'); });
  };
  useEffect(load, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (action, body = '') => {
    setSending(true); setError(''); setSuccess('');
    try {
      await guestRequest(token, '/actions', { method: 'POST', body: JSON.stringify({ action, body }) });
      setComment(''); setSuccess(action === 'approve' ? 'Approval recorded.' : 'Comment added.');
      await load();
    } catch (requestError) { setError(requestError.message); }
    finally { setSending(false); }
  };

  return <main className="guest-portal-shell">
    <header className="guest-portal-header"><div className="auth-brand"><span className="brand-mark">W</span><span>Workspace</span></div><span>Secure guest portal</span></header>
    <section className="guest-portal-page">
      {state === 'loading' && <div className="guest-portal-state"><span className="spinner dark" /><strong>Opening shared item…</strong></div>}
      {state === 'error' && <div className="guest-portal-state error"><span>!</span><h1>Link unavailable</h1><p>{error}</p><button className="button secondary" onClick={load}>Try again</button></div>}
      {state === 'ready' && data && <>
        <header className="guest-resource-heading"><div><p className="eyebrow">Shared {data.resource.type}</p><h1>{data.resource.title}</h1><p>{data.resource.description || 'No description was provided.'}</p></div><aside><span>Shared with</span><strong>{data.guest.name || data.guest.email}</strong><small>Access expires {formatDate(data.expires_at)}</small></aside></header>
        {error && <div className="notice error" role="alert">{error}</div>}{success && <div className="notice success" role="status">{success}</div>}
        <div className="guest-resource-grid"><article className="guest-resource-card"><h2>Details</h2><dl><div><dt>Type</dt><dd>{data.resource.type.replaceAll('_', ' ')}</dd></div><div><dt>Status</dt><dd>{data.resource.status?.replaceAll('_', ' ') || 'Not set'}</dd></div><div><dt>Permissions</dt><dd>{data.permissions.join(', ')}</dd></div></dl></article>
          <article className="guest-resource-card activity"><h2>Guest activity</h2>{data.activity.length === 0 && <p>No guest activity yet.</p>}{data.activity.map((item) => <div key={item.id}><span>{item.action === 'approve' ? '✓' : '◌'}</span><div><strong>{item.action === 'approve' ? 'Approved' : 'Comment'}</strong>{item.body && <p>{item.body}</p>}<small>{formatDate(item.created_at)}</small></div></div>)}</article></div>
        {(data.permissions.includes('comment') || data.permissions.includes('approve')) && <section className="guest-response-card"><header><div><h2>Respond</h2><p>Your response is recorded in the workspace audit history.</p></div>{data.permissions.includes('approve') && <button className="button secondary" disabled={sending} onClick={() => act('approve')}>Approve</button>}</header>
          {data.permissions.includes('comment') && <form onSubmit={(event) => { event.preventDefault(); if (comment.trim()) act('comment', comment.trim()); }}><label>Comment<textarea required value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Add context, a question, or an update" /></label><button className="button primary" disabled={sending || !comment.trim()}>{sending ? 'Sending…' : 'Send comment'}</button></form>}</section>}
      </>}
    </section>
  </main>;
}
