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
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const message = data?.error || data?.message || text || 'Failed to create candidate';
    const error = new Error(message);
    if (data) error.details = data;
    throw error;
  }
  return data ?? text;
}
