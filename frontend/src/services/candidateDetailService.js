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

export async function fetchCandidateTests(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/tests`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load candidate tests');
  return res.json();
}

export async function uploadCandidateTests(candidateId, filesOrFormData) {
  let body = filesOrFormData;
  if (!(body instanceof FormData)) {
    body = new FormData();
    const files = Array.isArray(filesOrFormData) || filesOrFormData instanceof FileList
      ? Array.from(filesOrFormData)
      : [];
    files.forEach((file) => body.append('files', file));
  }
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/tests`, {
    method: 'POST',
    body,
    credentials: 'include',
  });
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(errorText || 'Failed to upload test files');
  }
  return res.json();
}

export async function deleteCandidateTest(candidateId, key) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/tests`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ key }),
  });
  if (!res.ok) {
    const message = await res.text();
    throw new Error(message || 'Failed to delete test file');
  }
  return res.json();
}

export async function updateCandidateScrap(candidateId, payload) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to save candidate data');
  return res.json();
}

export async function fetchCandidateCvs(candidateId) {
  const res = await fetch(`${API_BASE_URL}/candidates/${candidateId}/cvs`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load candidate CVs');
  return res.json();
}

export async function fetchResumeRecord(candidateId) {
  const res = await fetch(`${API_BASE_URL}/resumes/${candidateId}`, { credentials: 'include' });
  if (!res.ok) throw new Error('Failed to load resume');
  return res.json();
}

export async function generateResumeFields(candidateId, payload) {
  const res = await fetch(`${API_BASE_URL}/generate_resume_fields`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_id: candidateId, ...payload }),
  });
  if (!res.ok) throw new Error('Failed to generate resume');
  return res.json();
}

export async function improveAbout(candidateId, prompt) {
  return genericImprove('/ai/improve_about', candidateId, prompt);
}

export async function improveEducation(candidateId, prompt) {
  return genericImprove('/ai/improve_education', candidateId, prompt);
}

export async function improveWorkExperience(candidateId, prompt) {
  return genericImprove('/ai/improve_work_experience', candidateId, prompt);
}

export async function improveTools(candidateId, prompt) {
  return genericImprove('/ai/improve_tools', candidateId, prompt);
}

async function genericImprove(path, candidateId, prompt) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_id: candidateId, user_prompt: prompt }),
  });
  if (!res.ok) throw new Error('Failed to improve resume section');
  return res.json();
}
