// Client for the new login screen's backend (webapi/session_routes.py),
// which bridges to app/services/session_store_service.py's per-user session
// JSON files (data/sessions/<NAME>.json) -- same store the legacy Streamlit
// app already used for this, not a new one.

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

async function postJSON(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.detail ? String(payload.detail) : `Request failed (${res.status})`);
  }
  return res.json();
}

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

// Resumes the named user's most recent session, or starts a new one.
export const loginSession = (name) => postJSON('/api/session/login', { name });

// Pre-fills the login screen with whoever last logged in, anywhere.
export const getLastDisplayName = () => getJSON('/api/session/last-name');

export const logSessionAction = (userNorm, sessionId, type, payload) =>
  postJSON('/api/session/action', { user_norm: userNorm, session_id: sessionId, type, payload });

export const logoutSession = (userNorm, sessionId) =>
  postJSON('/api/session/logout', { user_norm: userNorm, session_id: sessionId });
