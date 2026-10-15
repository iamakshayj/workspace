import React, { useState } from 'react';
import { discoverSso } from './authService';
import { API_BASE_URL } from './apiClient';

function GoogleLikeShield() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 5 6v5c0 4.8 2.8 8.2 7 10 4.2-1.8 7-5.2 7-10V6l-7-3Z" /><path d="m9 12 2 2 4-4" /></svg>;
}

export default function AuthScreen({ auth, startupError = '' }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(startupError);
  const [submitting, setSubmitting] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaCode, setMfaCode] = useState('');
  const [ssoProvider, setSsoProvider] = useState(null);
  const [discoveringSso, setDiscoveringSso] = useState(false);

  const findSso = async () => {
    if (!email.includes('@')) return;
    setDiscoveringSso(true);
    try {
      const result = await discoverSso(email);
      setSsoProvider(result.available ? result : null);
    } catch { /* Password sign-in remains available when discovery is temporarily unavailable. */ }
    finally { setDiscoveringSso(false); }
  };

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      if (mfaRequired) await auth.login(email, password, mfaCode);
      else await auth.login(email, password);
    } catch (requestError) {
      if (requestError.status === 428) {
        setMfaRequired(true);
        setError('Enter the six-digit code from your authenticator app or a recovery code.');
      } else if (requestError.details?.code === 'sso_required') {
        setSsoProvider(requestError.details);
        setError(requestError.message);
      } else setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="auth-shell">
    <section className="auth-form-panel">
      <div className="auth-brand"><span className="brand-mark">W</span><span>Workspace</span></div>
      <div className="auth-form-wrap">
        <div className="auth-heading"><span className="auth-security-icon"><GoogleLikeShield /></span>
          <p className="eyebrow">Workspace access</p>
          <h1>Welcome back</h1>
          <p>Sign in to continue to your team’s workspace.</p>
        </div>
        <form className="auth-form" onSubmit={submit}>
          <label>Email address<input required type="email" autoComplete="email" value={email}
            onBlur={findSso} onChange={(event) => { setEmail(event.target.value); setSsoProvider(null); }} placeholder="you@company.com" /></label>
          <label>Password<input required type="password" autoComplete="current-password" value={password}
            onChange={(event) => setPassword(event.target.value)} placeholder="Your password" /></label>
          {mfaRequired && <label>Verification code<input required autoFocus autoComplete="one-time-code" value={mfaCode}
            onChange={(event) => setMfaCode(event.target.value)} placeholder="123456 or recovery code" /></label>}
          {error && <div className="auth-error" role="alert">{error}</div>}
          {ssoProvider && <button type="button" className="button secondary auth-submit" onClick={() => {
            const loginUrl = ssoProvider.login_url.startsWith('http') ? ssoProvider.login_url : `${API_BASE_URL}${ssoProvider.login_url}`;
            window.location.assign(`${loginUrl}?return_to=${encodeURIComponent(window.location.pathname + window.location.search)}`);
          }}>Continue with {ssoProvider.provider_name}</button>}
          {!ssoProvider && <button type="button" className="auth-sso-discover" disabled={discoveringSso || !email.includes('@')} onClick={findSso}>{discoveringSso ? 'Finding your provider…' : 'Use company SSO'}</button>}
          <button className="button primary auth-submit" disabled={submitting}>
            {submitting ? <><span className="spinner" /> Please wait…</> : mfaRequired ? 'Verify and sign in' : 'Sign in'}
          </button>
        </form>
        <p className="auth-provisioning-note"><strong>Need access?</strong> Contact your workspace administrator for an invitation.</p>
        <div className="auth-security-note"><GoogleLikeShield /><span><strong>Protected workspace</strong>
          Access is limited to authorized members of your organization.</span></div>
      </div>
    </section>
    <aside className="auth-visual-panel">
      <div className="auth-visual-copy"><p className="eyebrow">From words to workflows</p><h2>Map your process.<br />Keep it yours.</h2>
        <p>Turn complex processes into clear, collaborative workflows your team can act on.</p></div>
      <div className="auth-flow-preview">
        <span className="auth-preview-node start">Request received</span>
        <span className="auth-preview-line line-one" />
        <span className="auth-preview-node decision">Ready?</span>
        <span className="auth-preview-line line-two" />
        <span className="auth-preview-node finish">Ship workflow</span>
        <span className="auth-preview-label yes">Yes</span><span className="auth-preview-label no">No</span>
      </div>
      <div className="auth-trust-row"><span>✓ Role-based access</span><span>✓ Team collaboration</span><span>✓ Guided workflows</span></div>
    </aside>
  </main>;
}
