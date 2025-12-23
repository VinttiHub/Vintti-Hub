import { API_BASE_URL } from '../constants/api.js';

export async function fetchCandidatesLight() {
  const res = await fetch(`${API_BASE_URL}/candidates/light_fast`, { cache: 'no-store', credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load candidates');
  return res.json();
}

export async function fetchCandidateById(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}`, { cache: 'no-store', credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load candidate');
  return res.json();
}

export async function createCandidate(payload) {
  const res = await fetch(`${API_BASE_URL}/candidates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(text || 'Failed to create candidate');
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
