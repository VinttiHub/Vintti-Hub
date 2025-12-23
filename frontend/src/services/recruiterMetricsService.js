import { API_BASE_URL } from '../constants/api.js';

export async function fetchRecruiterMetrics(params = {}) {
  const url = new URL(`${API_BASE_URL}/recruiter-metrics`);
  if (params.start) url.searchParams.set('start', params.start);
  if (params.end) url.searchParams.set('end', params.end);

  const res = await fetch(url.toString(), { credentials: 'include' });
  if (!res.ok) throw new Error(`Failed to load recruiter metrics: ${res.status}`);
  return res.json();
}

export async function fetchProfile() {
  const res = await fetch(`${API_BASE_URL}/profile/me`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load profile');
  return res.json();
}
