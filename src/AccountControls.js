import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from './AuthProvider';
import { useTheme } from './ThemeProvider';
import TeamManagement from './TeamManagement';
import CommunicationCenter from './CommunicationCenter';
import WorkspaceAssistant from './WorkspaceAssistant';
import IdentityManagement from './IdentityManagement';
import {
  confirmMfa, disableMfa, enrollMfa, getAuthenticationPolicy, getSecuritySummary,
  revokeAuthSession, revokeOtherSessions, updateAuthenticationPolicy,
} from './authService';

const DEFAULT_PREFERENCES = {
  productUpdates: true,
  saveReminders: true,
};

function loadStored(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) || fallback;
  } catch {
    return fallback;
  }
}

function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'FF';
}

function SecuritySettings({ user, onSignedOut, onSecurityChanged }) {
  const [security, setSecurity] = useState(null);
  const [policyState, setPolicyState] = useState(null);
  const [policyDraft, setPolicyDraft] = useState(null);
  const [enrollment, setEnrollment] = useState(null);
  const [recoveryCodes, setRecoveryCodes] = useState([]);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    try {
      const [summary, policy] = await Promise.all([getSecuritySummary(), getAuthenticationPolicy()]);
      setSecurity(summary); setPolicyState(policy); setPolicyDraft(policy.policy);
    }
    catch (requestError) { setError(requestError.message); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const perform = async (action) => {
    setBusy(true); setError('');
    try { await action(); }
    catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  const beginMfa = (event) => {
    event.preventDefault();
    perform(async () => { setEnrollment(await enrollMfa(password)); setPassword(''); });
  };
  const finishMfa = (event) => {
    event.preventDefault();
    perform(async () => {
      const result = await confirmMfa(code);
      setRecoveryCodes(result.recovery_codes || []); setEnrollment(null); setCode(''); await load();
    });
  };
  const turnOffMfa = (event) => {
    event.preventDefault();
    perform(async () => { await disableMfa(password, code); setPassword(''); setCode(''); await load(); });
  };
  const savePolicy = (event) => {
    event.preventDefault();
    perform(async () => {
      const next = await updateAuthenticationPolicy({
        ...policyDraft,
        session_lifetime_hours: Number(policyDraft.session_lifetime_hours),
        idle_timeout_minutes: Number(policyDraft.idle_timeout_minutes),
      });
      setPolicyState(next); setPolicyDraft(next.policy); await load(); await onSecurityChanged();
    });
  };

  if (!security) return <div className="security-settings"><p>{error || 'Loading account security…'}</p></div>;
  return <div className="security-settings">
    <section><header><div><strong>Multi-factor authentication</strong><small>Protect sign-in with an authenticator app and one-time recovery codes.</small></div><span className={security.mfa_enabled ? 'enabled' : ''}>{security.mfa_enabled ? 'Enabled' : 'Not enabled'}</span></header>
      {!security.mfa_enabled && !enrollment && !recoveryCodes.length && <form onSubmit={beginMfa}><label>Confirm current password<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><button className="button primary" disabled={busy}>Set up authenticator</button></form>}
      {enrollment && <form onSubmit={finishMfa}><div className="mfa-setup-key"><small>Enter this setup key in your authenticator app</small><code>{enrollment.secret}</code><p>Time-based · 6 digits · refreshes every 30 seconds</p></div><label>Verification code<input required autoComplete="one-time-code" inputMode="numeric" value={code} onChange={(event) => setCode(event.target.value)} placeholder="123456" /></label><button className="button primary" disabled={busy}>Verify and enable</button></form>}
      {!!recoveryCodes.length && <div className="mfa-recovery-codes"><strong>Save these recovery codes now</strong><p>Each code works once. Store them outside this workspace.</p><div>{recoveryCodes.map((item) => <code key={item}>{item}</code>)}</div><button className="button secondary" onClick={() => setRecoveryCodes([])}>I saved these codes</button></div>}
      {security.mfa_enabled && !recoveryCodes.length && <form onSubmit={turnOffMfa}><p className="security-help">{security.recovery_codes_remaining} recovery codes remaining</p><label>Current password<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><label>Authenticator or recovery code<input required autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} /></label><button className="button danger" disabled={busy}>Disable MFA</button></form>}
    </section>
    <section><header><div><strong>Active sessions</strong><small>Review signed-in browsers and revoke access you do not recognize.</small></div><button className="button secondary" disabled={busy || security.sessions.length < 2} onClick={() => perform(async () => { await revokeOtherSessions(); await load(); })}>Sign out other sessions</button></header>
      {security.legacy_session && <div className="security-legacy-note">This browser predates device tracking. Sign out and back in to register it as a managed session.</div>}
      <div className="security-session-list">{security.sessions.map((item) => <article key={item.id}><span>◉</span><div><strong>{item.device}{item.current ? ' · This browser' : ''}</strong><small>Signed in {new Date(item.created_at).toLocaleString()} · Expires {new Date(item.expires_at).toLocaleDateString()}</small></div><button disabled={busy} onClick={() => perform(async () => { await revokeAuthSession(item.id); if (item.current) await onSignedOut(); else await load(); })}>Revoke</button></article>)}{!security.sessions.length && <p>No managed sessions yet.</p>}</div>
    </section>
    {user.role === 'admin' && policyDraft && <section className="authentication-policy"><header><div><strong>Workspace authentication policy</strong><small>Require MFA and bound managed-session exposure for every member.</small></div><span className={policyDraft.mfa_requirement !== 'optional' ? 'enabled' : ''}>{policyDraft.mfa_requirement === 'optional' ? 'Optional' : 'Enforced'}</span></header>
      <form onSubmit={savePolicy}><label>MFA requirement<select value={policyDraft.mfa_requirement} onChange={(event) => setPolicyDraft({ ...policyDraft, mfa_requirement: event.target.value })}><option value="optional">Optional for everyone</option><option value="admins">Required for administrators</option><option value="all">Required for all members</option></select></label><div className="security-policy-grid"><label>Maximum session lifetime<input type="number" min="1" max="720" required value={policyDraft.session_lifetime_hours} onChange={(event) => setPolicyDraft({ ...policyDraft, session_lifetime_hours: event.target.value })} /><small>Hours · maximum 30 days</small></label><label>Idle timeout<input type="number" min="5" max="10080" required value={policyDraft.idle_timeout_minutes} onChange={(event) => setPolicyDraft({ ...policyDraft, idle_timeout_minutes: event.target.value })} /><small>Minutes · maximum 7 days</small></label></div><button className="button primary" disabled={busy}>Save authentication policy</button></form>
      {policyState?.compliance && <div className="security-compliance"><div><strong>{policyState.compliance.enrolled_users}/{policyState.compliance.total_users}</strong><span>MFA enrolled</span></div><div><strong>{policyState.compliance.required_users}</strong><span>Users in scope</span></div><div><strong>{policyState.compliance.required_not_enrolled.length}</strong><span>Action required</span></div>{!!policyState.compliance.required_not_enrolled.length && <ul>{policyState.compliance.required_not_enrolled.slice(0, 6).map((member) => <li key={member.id}><span>{member.display_name}<small>{member.email}</small></span><em>{member.role}</em></li>)}</ul>}</div>}
    </section>}
    {user.role === 'admin' && <IdentityManagement />}
    {error && <div className="auth-error" role="alert">{error}</div>}
  </div>;
}

export default function AccountControls({ showIdentity = false, onNavigate, active = 'home' }) {
  const { user, updateProfile, logout, refresh } = useAuth();
  const { preference: themePreference, setThemePreference } = useTheme();
  const preferencesKey = `flowforge:preferences:${user.id}`;
  const [preferences, setPreferences] = useState(() => ({
    ...DEFAULT_PREFERENCES,
    theme: themePreference,
    ...loadStored(preferencesKey, {}),
  }));
  const profile = {
    name: user.display_name,
    email: user.email,
    role: user.role === 'admin' ? 'Admin' : user.role === 'guest' ? 'Guest' : 'Basic user',
    entityName: user.entity_name || 'Workspace',
    ...preferences,
  };
  const [draft, setDraft] = useState(profile);
  const [openMenu, setOpenMenu] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState('profile');
  const [settingsError, setSettingsError] = useState('');
  const [savingSettings, setSavingSettings] = useState(false);
  const controlsRef = useRef(null);

  useEffect(() => {
    const closeMenus = (event) => {
      if (!controlsRef.current?.contains(event.target)) setOpenMenu(null);
    };
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') {
        setOpenMenu(null);
        setSettingsOpen(false);
      }
    };
    document.addEventListener('mousedown', closeMenus);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeMenus);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, []);

  useEffect(() => {
    setThemePreference(preferences.theme || 'system');
  }, [preferences.theme, setThemePreference]);

  useEffect(() => {
    if (user.role !== 'admin' && settingsTab === 'team') setSettingsTab('profile');
  }, [settingsTab, user.role]);

  const toggleMenu = (menu) => setOpenMenu((current) => current === menu ? null : menu);

  const openSettings = (tab) => {
    setDraft(profile);
    setSettingsTab(tab);
    setSettingsError('');
    setSettingsOpen(true);
    setOpenMenu(null);
  };

  useEffect(() => {
    const openRequestedSettings = (event) => {
      const requested = event.detail?.tab;
      const tab = ['profile', 'preferences', 'security', 'team'].includes(requested) ? requested : 'preferences';
      setDraft({
        name: user.display_name,
        email: user.email,
        role: user.role === 'admin' ? 'Admin' : user.role === 'guest' ? 'Guest' : 'Basic user',
        entityName: user.entity_name || 'Workspace',
        ...preferences,
      });
      setSettingsTab(user.role === 'admin' || tab !== 'team' ? tab : 'profile');
      setSettingsError('');
      setSettingsOpen(true);
      setOpenMenu(null);
    };
    window.addEventListener('workspace:open-settings', openRequestedSettings);
    return () => window.removeEventListener('workspace:open-settings', openRequestedSettings);
  }, [preferences, user.display_name, user.email, user.entity_name, user.role]);

  const saveSettings = async (event) => {
    event.preventDefault();
    setSavingSettings(true);
    setSettingsError('');
    try {
      await updateProfile(draft.name.trim(), draft.email.trim());
      const updatedPreferences = {
        productUpdates: draft.productUpdates,
        saveReminders: draft.saveReminders,
        theme: draft.theme,
      };
      setPreferences(updatedPreferences);
      setThemePreference(updatedPreferences.theme);
      localStorage.setItem(preferencesKey, JSON.stringify(updatedPreferences));
      setSettingsOpen(false);
    } catch (error) {
      setSettingsError(error.message);
    } finally {
      setSavingSettings(false);
    }
  };

  return <>
    <div className="account-controls" ref={controlsRef}>
      <WorkspaceAssistant currentUser={user} active={active} onNavigate={onNavigate} />
      <CommunicationCenter currentUser={user} onNavigate={onNavigate} />

      <button className="account-button" aria-label="Open account menu" aria-expanded={openMenu === 'account'}
        onClick={() => toggleMenu('account')}>
        <span className="account-avatar">{initials(profile.name)}</span>
        {showIdentity && <span className="account-identity"><strong>{profile.name}</strong><small>{profile.role}</small></span>}
        <span className="account-chevron">⌄</span>
      </button>

      {openMenu === 'account' && <div className="account-popover profile-popover">
        <div className="profile-summary"><span className="account-avatar large">{initials(profile.name)}</span>
          <div><strong>{profile.name}</strong><span>{profile.email}</span><small>Active account</small></div>
        </div>
        <div className="profile-menu-list">
          <button onClick={() => openSettings('profile')}><span>◎</span><div><strong>Profile</strong><small>Name and email</small></div></button>
          <button onClick={() => openSettings('preferences')}><span>⚙</span><div><strong>Settings</strong><small>Notifications and workspace</small></div></button>
          <button className="profile-signout" onClick={() => logout()}><span>↪</span><div><strong>Sign out</strong><small>Sign out of Workspace</small></div></button>
        </div>
        <div className="workspace-account-note"><span className="status-dot" /> {profile.entityName} · {profile.role}</div>
      </div>}
    </div>

    {settingsOpen && <div className="settings-backdrop" role="presentation"
      onMouseDown={(event) => { if (event.target === event.currentTarget) setSettingsOpen(false); }}>
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header><div><p className="eyebrow">Account</p><h2 id="settings-title">Profile & settings</h2></div>
          <button className="icon-button" aria-label="Close settings" onClick={() => setSettingsOpen(false)}>×</button>
        </header>
        <div className="settings-layout">
          <nav aria-label="Settings sections">
            <button className={settingsTab === 'profile' ? 'active' : ''} onClick={() => setSettingsTab('profile')}>Profile</button>
            <button className={settingsTab === 'preferences' ? 'active' : ''} onClick={() => setSettingsTab('preferences')}>Preferences</button>
            <button className={settingsTab === 'security' ? 'active' : ''} onClick={() => setSettingsTab('security')}>Security</button>
            {user.role === 'admin' && <button className={settingsTab === 'team' ? 'active' : ''} onClick={() => setSettingsTab('team')}>Entity & contacts</button>}
          </nav>
          {settingsTab === 'team' ? <div className="team-settings-panel"><TeamManagement /></div> : settingsTab === 'security' ? <SecuritySettings user={user} onSignedOut={logout} onSecurityChanged={refresh} /> : <form onSubmit={saveSettings}>
            {settingsTab === 'profile' ? <>
              <div className="settings-avatar-row"><span className="account-avatar settings-avatar">{initials(draft.name)}</span>
                <div><strong>Profile details</strong><small>Shown across your Workspace account.</small></div></div>
              <label>Full name<input value={draft.name} autoFocus
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
              <label>Email address<input type="email" value={draft.email}
                onChange={(event) => setDraft((current) => ({ ...current, email: event.target.value }))} /></label>
              <label>Workspace role<input value={draft.role} disabled /></label>
            </> : <>
              <fieldset className="theme-fieldset"><legend>Appearance</legend><small>Choose a theme or follow your device setting.</small>
                <div className="theme-options">
                  {[['system', '◐', 'System'], ['light', '☀', 'Light'], ['dark', '☾', 'Dark']].map(([value, icon, label]) =>
                    <button key={value} type="button" aria-pressed={draft.theme === value}
                      className={draft.theme === value ? 'selected' : ''}
                      onClick={() => setDraft((current) => ({ ...current, theme: value }))}>
                      <span>{icon}</span><strong>{label}</strong>
                    </button>)}
                </div>
              </fieldset>
              <div className="settings-section-heading"><strong>Notifications</strong><small>Choose which reminders you want to receive.</small></div>
              <label className="settings-toggle"><span><strong>Product updates</strong><small>Show updates about new Workspace features.</small></span>
                <input type="checkbox" checked={draft.productUpdates}
                  onChange={(event) => setDraft((current) => ({ ...current, productUpdates: event.target.checked }))} /></label>
              <label className="settings-toggle"><span><strong>Save reminders</strong><small>Remind me when a workflow has unsaved changes.</small></span>
                <input type="checkbox" checked={draft.saveReminders}
                  onChange={(event) => setDraft((current) => ({ ...current, saveReminders: event.target.checked }))} /></label>
              <div className="preferences-note"><span className="status-dot" /><div><strong>Personal preferences</strong><small>Customize how Workspace looks and keeps you informed.</small></div></div>
            </>}
            {settingsError && <div className="auth-error" role="alert">{settingsError}</div>}
            <footer><button type="button" className="button secondary" onClick={() => setSettingsOpen(false)}>Cancel</button>
              <button type="submit" className="button primary" disabled={savingSettings}>{savingSettings ? 'Saving…' : 'Save changes'}</button></footer>
          </form>}
        </div>
      </section>
    </div>}
  </>;
}
