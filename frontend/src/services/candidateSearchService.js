import { API_BASE_URL } from '../constants/api.js';

export async function parseCandidateQuery(query) {
  const res = await fetch(`${API_BASE_URL}/ai/parse_candidate_query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error('Failed to parse query');
  return res.json();
}

export async function searchInternalCandidates({ tools = [], location = '', title = '' }) {
  const params = new URLSearchParams();
  if (tools.length) params.set('tools', tools.join(','));
  if (location) params.set('location', location);
  if (title) params.set('title', title);

  const res = await fetch(`${API_BASE_URL}/search/candidates?${params.toString()}`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error('Failed to search candidates');
  return res.json();
}

export async function coresignalSearch({ parsed, page = 1, locationOverride = null }) {
  const body = {
    title: parsed?.title || '',
    skills: (parsed?.tools || [])
      .map((skill) => String(skill).toLowerCase().trim())
      .filter(Boolean),
    location: locationOverride || parsed?.location || '',
    years_min: parsed?.years_experience ?? null,
    page,
    debug: true,
    allow_fallback: true,
  };

  const res = await fetch(`${API_BASE_URL}/ext/coresignal/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Failed to search Coresignal');
  return res.json();
}

export async function coresignalCollect(employeeId) {
  const res = await fetch(`${API_BASE_URL}/ext/coresignal/collect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ employee_id: employeeId }),
  });
  if (!res.ok) throw new Error('Failed to collect Coresignal profile');
  return res.json();
}
