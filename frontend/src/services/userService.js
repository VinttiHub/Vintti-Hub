import { API_BASE_URL } from '../constants/api.js';

function safeLocalStorage() {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function userEmailFromStorage() {
  const storage = safeLocalStorage();
  if (!storage) return '';
  return (
    storage.getItem('user_email') ||
    window.sessionStorage?.getItem('user_email') ||
    ''
  ).toLowerCase().trim();
}

export async function getCurrentUserId({ force = false } = {}) {
  if (typeof window === 'undefined') return null;
  const storage = safeLocalStorage();
  if (!storage) return null;

  const email = userEmailFromStorage();
  if (!email) return null;

  const cachedUid = storage.getItem('user_id');
  const cachedOwner = storage.getItem('user_id_owner_email');

  if (force || (cachedOwner && cachedOwner !== email)) {
    storage.removeItem('user_id');
  } else if (cachedUid) {
    return Number(cachedUid);
  }

  try {
    const fast = await fetch(`${API_BASE_URL}/users?email=${encodeURIComponent(email)}`);
    if (fast.ok) {
      const arr = await fast.json();
      const hit = Array.isArray(arr) ? arr.find(u => (u.email_vintti || '').toLowerCase() === email) : null;
      if (hit?.user_id != null) {
        storage.setItem('user_id', String(hit.user_id));
        storage.setItem('user_id_owner_email', email);
        return Number(hit.user_id);
      }
    }
  } catch (error) {
    console.debug('users?email lookup failed, falling back to /users', error);
  }

  try {
    const res = await fetch(`${API_BASE_URL}/users`);
    if (!res.ok) return null;
    const users = await res.json();
    const me = (users || []).find(u => String(u.email_vintti || '').toLowerCase() === email);
    if (me?.user_id != null) {
      storage.setItem('user_id', String(me.user_id));
      storage.setItem('user_id_owner_email', email);
      return Number(me.user_id);
    }
  } catch (error) {
    console.error('Could not resolve current user_id:', error);
  }
  return null;
}
