import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { acceptInvitation, discoverFederatedLogout, getCurrentUser, loginAccount, logoutAccount, updateAccount } from './authService';
import { API_BASE_URL } from './apiClient';
import AuthScreen from './AuthScreen';
import InviteAcceptScreen from './InviteAcceptScreen';
import SecurityGate from './SecurityGate';

const AuthContext = createContext(null);

function AuthLoading() {
  return <main className="auth-shell auth-loading"><div className="auth-brand"><span className="brand-mark">W</span><span>Workspace</span></div>
    <div><span className="spinner dark" /><p>Securing your workspace…</p></div></main>;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined);
  const [startupError, setStartupError] = useState('');
  const inviteToken = window.location.pathname === '/accept-invite'
    ? new URLSearchParams(window.location.search).get('token')
    : null;

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .catch((error) => { setStartupError(error.message); setUser(null); });
  }, []);

  useEffect(() => {
    const expireSession = () => setUser(null);
    window.addEventListener('flowforge:unauthorized', expireSession);
    return () => window.removeEventListener('flowforge:unauthorized', expireSession);
  }, []);

  const auth = useMemo(() => ({
    user,
    login: async (email, password, mfaCode = '') => {
      const authenticated = await loginAccount(email, password, mfaCode);
      setUser(authenticated);
      setStartupError('');
      return authenticated;
    },
    updateProfile: async (displayName, email) => {
      const updated = await updateAccount(displayName, email);
      setUser(updated);
      return updated;
    },
    refresh: async () => {
      const current = await getCurrentUser();
      setUser(current);
      return current;
    },
    acceptInvite: async (token, password) => {
      const authenticated = await acceptInvitation(token, password);
      window.history.replaceState({}, '', '/');
      setUser(authenticated);
      setStartupError('');
      return authenticated;
    },
    logout: async () => {
      const federation = await discoverFederatedLogout().catch(() => null);
      if (federation?.available) {
        const separator = federation.logout_url.includes('?') ? '&' : '?';
        window.location.assign(`${API_BASE_URL}${federation.logout_url}${separator}return_to=${encodeURIComponent('/')}`);
        return;
      }
      await logoutAccount();
      setUser(null);
      window.history.replaceState({}, '', '/');
    },
  }), [user]);

  if (user === undefined) return <AuthLoading />;
  if (!user && inviteToken) return <InviteAcceptScreen token={inviteToken} auth={auth} />;
  if (!user) return <AuthScreen auth={auth} startupError={startupError} />;
  if (user.security_status && user.security_status !== 'compliant') {
    return <SecurityGate user={user} onRefresh={auth.refresh} onLogout={auth.logout} />;
  }
  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error('useAuth must be used within AuthProvider');
  return auth;
}
