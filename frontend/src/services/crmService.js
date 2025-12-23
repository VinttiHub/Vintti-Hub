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

export async function fetchStatusSummary(accountIds = []) {
  const res = await fetch(`${API_BASE_URL}/accounts/status/summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_ids: accountIds }),
  });
  if (!res.ok) throw new Error('Failed to fetch status summary');
  return res.json();
}

export async function fetchAccountOpportunities(accountId) {
  const [opps, hires] = await Promise.all([
    fetch(`${API_BASE_URL}/accounts/${accountId}/opportunities`, { credentials: 'include' }).then((r) => r.json()),
    fetch(`${API_BASE_URL}/accounts/${accountId}/opportunities/candidates`, { credentials: 'include' }).then((r) => r.json()),
  ]);
  return { opps, hires };
}

export async function bulkUpdateStatuses(updates) {
  const res = await fetch(`${API_BASE_URL}/accounts/status/bulk_update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      updates: updates.map((update) => ({
        account_id: update.account_id,
        calculated_status: update.status,
      })),
    }),
  });
  if (!res.ok) throw new Error('Failed to bulk update statuses');
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

export async function fetchSalesLeadSuggestion(accountId) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/sales-lead/suggest`, { credentials: 'include' });
  if (!res.ok) return null;
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
