import { API_BASE_URL } from '../constants/api.js';

export async function fetchOpportunities() {
  const res = await fetch(`${API_BASE_URL}/opportunities/light`, { credentials: 'include' });
  if (!res.ok) throw new Error(`Failed to load opportunities: ${res.status}`);
  return res.json();
}

export async function fetchLatestSourcingDate(opportunityId) {
  const res = await fetch(`${API_BASE_URL}/opportunities/${opportunityId}/latest_sourcing_date`, { credentials: 'include' });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchOpportunity(opportunityId) {
  const res = await fetch(`${API_BASE_URL}/opportunities/${opportunityId}`, { credentials: 'include' });
  if (!res.ok) throw new Error(`Failed to load opportunity ${opportunityId}`);
  return res.json();
}

export async function updateOpportunityStage(opportunityId, newStage) {
  const res = await fetch(`${API_BASE_URL}/opportunities/${opportunityId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ opp_stage: newStage }),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(payload.error || 'Failed to update stage');
  return payload;
}

export async function updateOpportunityFields(opportunityId, fields) {
  const res = await fetch(`${API_BASE_URL}/opportunities/${opportunityId}/fields`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(text || 'Failed to update fields');
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function createOpportunity(payload) {
  const res = await fetch(`${API_BASE_URL}/opportunities`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || 'Failed to create opportunity');
  return data;
}

export async function postSourcingEntry(payload) {
  const res = await fetch(`${API_BASE_URL}/sourcing`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || 'Failed to create sourcing entry');
  }
}

export async function postInterviewingEntry(payload) {
  const res = await fetch(`${API_BASE_URL}/interviewing`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || 'Failed to create interviewing entry');
  }
}

export async function fetchAccounts() {
  const res = await fetch(`${API_BASE_URL}/accounts`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load accounts');
  return res.json();
}

export async function fetchUsers() {
  const res = await fetch(`${API_BASE_URL}/users`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load users');
  return res.json();
}

export async function searchCandidates(term) {
  const res = await fetch(`${API_BASE_URL}/candidates?search=${encodeURIComponent(term)}`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to search candidates');
  return res.json();
}

export async function linkCandidateHire(candidateId, opportunityId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ opportunity_id: Number(opportunityId) }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || 'Failed to link candidate hire');
  }
}
