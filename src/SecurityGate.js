import React, { useState } from 'react';
import { confirmMfa, enrollMfa, stepUpMfa } from './authService';

export default function SecurityGate({ user, onRefresh, onLogout }) {
  const needsSetup = user.security_status === 'setup_required';
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [enrollment, setEnrollment] = useState(null);
  const [recoveryCodes, setRecoveryCodes] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const perform = async (action) => {
    setBusy(true); setError('');
    try { await action(); }
    catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  const submit = (event) => {
    event.preventDefault();
    perform(async () => {
      if (needsSetup && !enrollment) {
        setEnrollment(await enrollMfa(password)); setPassword(''); return;
      }
      if (needsSetup) {
        const result = await confirmMfa(code);
        setRecoveryCodes(result.recovery_codes || []); setEnrollment(null); setCode(''); return;
      }
      await stepUpMfa(code);
      await onRefresh();
    });
  };

  return <main className="auth-shell security-gate-shell">
    <section className="security-gate-card">
      <div className="auth-brand"><span className="brand-mark">W</span><span>Workspace</span></div>
      <span className="security-gate-icon">✓</span>
      <p className="eyebrow">Workspace security</p>
      <h1>{needsSetup ? 'Secure your account' : 'Verify it’s you'}</h1>
      <p>{needsSetup
        ? 'Your workspace requires multi-factor authentication. Set up an authenticator before continuing.'
        : 'Your workspace now requires an MFA-verified session. Enter a current authenticator or recovery code.'}</p>

      {!!recoveryCodes.length ? <div className="mfa-recovery-codes security-gate-recovery">
        <strong>Save your recovery codes</strong><p>Each code works once. Store them outside this workspace.</p>
        <div>{recoveryCodes.map((item) => <code key={item}>{item}</code>)}</div>
        <button className="button primary" onClick={() => perform(onRefresh)} disabled={busy}>I saved them — continue</button>
      </div> : <form className="auth-form" onSubmit={submit}>
        {needsSetup && !enrollment && <label>Current password<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>}
        {enrollment && <><div className="mfa-setup-key"><small>Add this setup key to your authenticator</small><code>{enrollment.secret}</code><p>Time-based · 6 digits · refreshes every 30 seconds</p></div><label>Verification code<input required autoFocus inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} /></label></>}
        {!needsSetup && <label>Authenticator or recovery code<input required autoFocus autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} /></label>}
        {error && <div className="auth-error" role="alert">{error}</div>}
        <button className="button primary auth-submit" disabled={busy}>{busy ? 'Checking…' : needsSetup && !enrollment ? 'Start setup' : needsSetup ? 'Enable MFA' : 'Verify and continue'}</button>
      </form>}
      <button className="security-gate-signout" onClick={onLogout}>Sign out instead</button>
    </section>
  </main>;
}
