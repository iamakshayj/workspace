import React, { useEffect, useState } from 'react';
import { getInvitation } from './authService';

function roleLabel(role) {
  return role === 'admin' ? 'Admin' : 'Basic user';
}

export default function InviteAcceptScreen({ token, auth }) {
  const [invitation, setInvitation] = useState(null);
  const [loadingError, setLoadingError] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getInvitation(token).then(setInvitation).catch((requestError) => setLoadingError(requestError.message));
  }, [token]);

  const submit = async (event) => {
    event.preventDefault();
    if (password !== confirmation) {
      setError('Passwords do not match.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      await auth.acceptInvite(token, password);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="auth-shell invite-shell">
    <section className="auth-form-panel">
      <div className="auth-brand"><span className="brand-mark">W</span><span>Workspace</span></div>
      <div className="auth-form-wrap">
        {loadingError ? <div className="invite-error-state"><p className="eyebrow">Invitation unavailable</p>
          <h1>This setup link can’t be used</h1><p>{loadingError}</p><a href="/">Return to sign in</a></div>
          : !invitation ? <div className="dashboard-message"><span className="spinner dark" /> Checking invitation…</div>
            : <><div className="auth-heading"><span className="invite-avatar">{invitation.display_name.slice(0, 1).toUpperCase()}</span>
              <p className="eyebrow">You’re invited</p><h1>Set up your account</h1>
              <p>Join <strong>{invitation.entity_name}</strong> as a {roleLabel(invitation.role)}.</p></div>
              <div className="invite-summary"><span><small>Name</small><strong>{invitation.display_name}</strong></span>
                <span><small>Email</small><strong>{invitation.email}</strong></span>
                <span><small>Access</small><strong>{roleLabel(invitation.role)}</strong></span></div>
              <form className="auth-form" onSubmit={submit}>
                <label>Create password<input required minLength="8" type="password" autoComplete="new-password"
                  value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters" /></label>
                <label>Confirm password<input required minLength="8" type="password" autoComplete="new-password"
                  value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder="Repeat your password" /></label>
                {error && <div className="auth-error" role="alert">{error}</div>}
                <button className="button primary auth-submit" disabled={submitting}>{submitting ? 'Creating account…' : 'Create account & join'}</button>
              </form></>}
      </div>
    </section>
    <aside className="auth-visual-panel invite-visual"><div className="auth-visual-copy"><p className="eyebrow">Shared workspace</p>
      <h2>One team.<br />One source of truth.</h2><p>Join your team to explore, manage, and improve the processes that keep work moving.</p></div></aside>
  </main>;
}
