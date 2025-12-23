import { API_BASE_URL } from '../constants/api.js';
import { getCurrentUserId } from './userService.js';

export async function loginRequest({ email, password }) {
  const res = await fetch(`${API_BASE_URL}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  const raw = await res.text();
  let data = {};
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error(`Unexpected login response: ${raw || res.status}`);
  }

  if (!res.ok || !data.success) {
    const message = data.message || data.error || `HTTP ${res.status}`;
    throw new Error(message);
  }

  return data;
}

export async function finalizeUserContext(email, payloadUserId) {
  const lowerEmail = email.toLowerCase();
  const storage = typeof window !== 'undefined' ? window.localStorage : null;
  if (!storage) return null;

  storage.setItem('user_email', lowerEmail);

  let finalUserId = typeof payloadUserId === 'number' ? payloadUserId : null;

  if (finalUserId == null) {
    finalUserId = (await getCurrentUserId({ force: true })) ?? null;
  }

  if (finalUserId != null) {
    storage.setItem('user_id', String(finalUserId));
    storage.setItem('user_id_owner_email', lowerEmail);
  }

  return finalUserId;
}

export async function requestPasswordReset(email) {
  const res = await fetch(`${API_BASE_URL}/password_reset_request`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });

  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(txt || 'Failed to send reset link.');
  }

  return true;
}
