import { API_BASE_URL } from '../constants/api.js';

export async function fetchAccountsLight() {
  const res = await fetch(`${API_BASE_URL}/data/light`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load accounts');
  return res.json();
}

export async function fetchAccountsList() {
  const res = await fetch(`${API_BASE_URL}/accounts`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load accounts');
  return res.json();
}

export async function patchAccount(accountId, body) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Failed to update account');
  return res.json();
}

export async function createAccount(payload) {
  const res = await fetch(`${API_BASE_URL}/accounts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || 'Failed to create account');
  }
  return res.json();
}
