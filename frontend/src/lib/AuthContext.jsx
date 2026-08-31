import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { loginSession, logoutSession } from '@/lib/sessionApi';

// Real per-name session now (webapi/session_routes.py -> the same
// data/sessions/<NAME>.json history the legacy Streamlit app used), entered
// through the Landing page. Nothing here auto-logs-in: `user` starts null
// until `login(name)` resolves, so a page that requires it should route back
// to "/" when `isAuthenticated` is false.

const AuthContext = createContext(null);

const STORAGE_KEY = 'msl_session_identity';

function loadStoredIdentity() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveStoredIdentity(identity) {
  try {
    if (identity) localStorage.setItem(STORAGE_KEY, JSON.stringify(identity));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable — best effort only */
  }
}

// Shape kept compatible with the old fake-profile's `full_name`/`email` so
// Home.jsx's greeting and AppSidebar's logout button don't need changes.
function toUser(identity) {
  return {
    id: identity.user_norm,
    user_norm: identity.user_norm,
    session_id: identity.session_id,
    full_name: identity.display_name,
    email: null,
  };
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const stored = loadStoredIdentity();
    return stored ? toUser(stored) : null;
  });

  // Resumes (or starts) `name`'s session server-side, then remembers the
  // identity locally so a refresh on /download or /catalog-manager doesn't
  // lose the greeting/logout button — only the Landing page itself is what
  // requires clicking "Entra" again on every fresh visit to "/".
  const login = useCallback(async (name) => {
    const identity = await loginSession(name);
    saveStoredIdentity(identity);
    const nextUser = toUser(identity);
    setUser(nextUser);
    return nextUser;
  }, []);

  const logout = useCallback(() => {
    if (user) logoutSession(user.user_norm, user.session_id).catch(() => {});
    saveStoredIdentity(null);
    setUser(null);
  }, [user]);

  const value = useMemo(() => ({ user, isAuthenticated: Boolean(user), login, logout }), [user, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
}
