import { API_BASE_URL } from '../constants/api.js';

export async function fetchCandidate(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load candidate');
  return res.json();
}

export async function updateCandidate(candidateId, patch) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error('Failed to update candidate');
  return res.json();
}

export async function fetchHire(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/hire`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load hire data');
  return res.json();
}

export async function fetchHireOpportunity(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/hire_opportunity`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load hire opportunity');
  return res.json();
}

export async function fetchSalaryUpdates(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/salary_updates`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load salary updates');
  return res.json();
}

export async function createSalaryUpdate(candidateId, payload) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/salary_updates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to create salary update');
  return res.json();
}

export async function updateHire(candidateId, payload) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to update hire');
  return res.json();
}

export async function fetchCandidateOpportunities(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/opportunities`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load candidate opportunities');
  return res.json();
}

export async function fetchCandidateEquipments(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/equipments`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load equipments');
  return res.json();
}
