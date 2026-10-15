import React, { useEffect, useRef, useState } from 'react';
import AccountControls from './AccountControls';
import EnterpriseSearch from './EnterpriseSearch';

const DESTINATIONS = [
  ['home', '/', 'Home'],
  ['work', '/work', 'Work'],
  ['calendar', '/calendar', 'Calendar'],
  ['workflows', '/workflows', 'Workflows'],
  ['knowledge', '/knowledge', 'Knowledge'],
  ['operations', '/operations', 'Operations'],
  ['admin', '/admin', 'Admin'],
];

export default function WorkspaceTopNav({
  active,
  onNavigate,
  context = null,
  actions = null,
  status = null,
  showIdentity = true,
  role = null,
}) {
  const [online, setOnline] = useState(() => navigator.onLine);
  const navRef = useRef(null);
  useEffect(() => {
    const refresh = () => setOnline(navigator.onLine);
    window.addEventListener('online', refresh);
    window.addEventListener('offline', refresh);
    return () => { window.removeEventListener('online', refresh); window.removeEventListener('offline', refresh); };
  }, []);
  useEffect(() => {
    navRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }, [active]);
  return <><a className="skip-link" href="#workspace-main">Skip to workspace content</a><header className="workspace-topnav">
    <button className="brand brand-button workspace-topnav-brand" onClick={() => onNavigate('/')}>
      <span className="brand-mark">W</span><span>Workspace</span>
    </button>
    <nav ref={navRef} aria-label="Primary navigation">{DESTINATIONS.filter(([id]) => (role !== 'guest' || id !== 'operations') && (id !== 'admin' || role === 'admin')).map(([id, path, label]) => <button key={id}
      className={active === id ? 'active' : ''} aria-current={active === id ? 'page' : undefined}
      onClick={() => onNavigate(path)}>{label}</button>)}</nav>
    <div className="workspace-topnav-context">{context}</div>
    <div className="topbar-actions workspace-topnav-actions">{status}{actions}<EnterpriseSearch onNavigate={onNavigate} /><AccountControls active={active} showIdentity={showIdentity} onNavigate={onNavigate} /></div>
  </header>{!online && <div className="offline-banner" role="status" aria-live="polite">You are offline. Existing content remains visible; changes will resume when the connection returns.</div>}</>;
}
