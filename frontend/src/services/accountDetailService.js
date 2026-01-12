import { API_BASE_URL } from '../constants/api.js';

export async function fetchAccount(accountId) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load account');
  return res.json();
}

export async function updateAccount(accountId, body) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Failed to update account');
  return res.json();
}

export async function fetchAccountOpportunities(accountId) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/opportunities`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load opportunities');
  return res.json();
}

export async function fetchAccountCandidates(accountId) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/opportunities/candidates`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load candidates');
  return res.json();
}

export async function listAccountPdfs(accountId) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/pdfs`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load PDFs');
  return res.json();
}

export async function uploadAccountPdfs(accountId, files) {
  await Promise.all(
    files.map(async (file) => {
      const formData = new FormData();
      formData.append('pdf', file);
      const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/upload_pdf`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) throw new Error('Failed to upload PDF');
      return res.json();
    }),
  );
}

export async function renameAccountPdf(accountId, key, newName) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/pdfs`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, new_name: newName }),
  });
  if (!res.ok) throw new Error('Failed to rename PDF');
  return res.json();
}

export async function deleteAccountPdf(accountId, key) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/pdfs`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key }),
  });
  if (!res.ok) throw new Error('Failed to delete PDF');
  return res.json();
}

export async function suggestAccountSalesLead(accountId) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/sales-lead/suggest`, { credentials: 'include' });
  if (!res.ok) return null;
  return res.json();
}

const HIRE_FIELDS = new Set([
  'discount_dolar',
  'discount_daterange',
  'referral_dolar',
  'referral_daterange',
  'buyout_dolar',
  'buyout_daterange',
  'start_date',
  'end_date',
]);

export async function updateCandidateField(candidateId, field, value, opportunityId) {
  if (HIRE_FIELDS.has(field)) {
    if (!opportunityId) throw new Error('Missing opportunity id');
    const body = { [field]: value, opportunity_id: opportunityId };
    const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/hire`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`Failed to update ${field}`);
    return res.json();
  }

  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [field]: value }),
  });
  if (!res.ok) throw new Error(`Failed to update ${field}`);
  return res.json();
}

export async function notifyCandidateInactive(payload) {
  const res = await fetch(`${API_BASE_URL}/send_email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to send notification');
  return res.json();
}
