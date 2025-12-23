import { useEffect, useMemo, useRef, useState } from 'react';
import SidebarLayout from '../../components/layout/SidebarLayout.jsx';
import LogoutFab from '../../components/common/LogoutFab.jsx';
import usePageStylesheet from '../../hooks/usePageStylesheet.js';
import { createCandidate, fetchCandidateById, fetchCandidatesLight } from '../../services/candidatesService.js';

const PHONE_CODE_BY_COUNTRY = {
  Argentina: '54',
  Bolivia: '591',
  Brazil: '55',
  Chile: '56',
  Colombia: '57',
  'Costa Rica': '506',
  Cuba: '53',
  Ecuador: '593',
  'El Salvador': '503',
  Guatemala: '502',
  Honduras: '504',
  Mexico: '52',
  Nicaragua: '505',
  Panama: '507',
  Paraguay: '595',
  Peru: '51',
  'Puerto Rico': '1',
  'Dominican Republic': '1',
  Uruguay: '598',
  Venezuela: '58',
  'United States': '1',
};

const STATUS_OPTIONS = [
  { value: '', label: 'Status: All' },
  { value: 'active', label: 'Active' },
  { value: 'unhired', label: 'Unhired' },
];

const MODEL_OPTIONS = [
  { value: '', label: 'Model: All' },
  { value: 'Recruiting', label: 'Recruiting' },
  { value: 'Staffing', label: 'Staffing' },
];

const DEFAULT_FORM = {
  name: '',
  email: '',
  country: '',
  phoneCode: '54',
  phone: '',
  linkedin: '',
};

function CandidatesPage() {
  usePageStylesheet('/assets/css/candidates.css');
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [modelFilter, setModelFilter] = useState('');
  const [searchValue, setSearchValue] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [formState, setFormState] = useState(DEFAULT_FORM);
  const [formError, setFormError] = useState('');
  const [duplicateInfo, setDuplicateInfo] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState('');
  const audioRef = useRef(null);
  const searchDebounceRef = useRef();

  useEffect(() => {
    loadCandidates();
  }, []);

  async function loadCandidates() {
    setLoading(true);
    try {
      const data = await fetchCandidatesLight();
      setCandidates(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error('Failed to load candidates', error);
      setCandidates([]);
    } finally {
      setLoading(false);
    }
  }

  const filteredCandidates = useMemo(() => {
    return (candidates || []).filter((candidate) => {
      const status = (candidate.status || 'unhired').toLowerCase();
      const model = (candidate.opp_model || '').trim();
      if (statusFilter && status !== statusFilter) return false;
      if (modelFilter && model !== modelFilter) return false;
      if (searchValue) {
        const haystack = `${candidate.name || ''}`.toLowerCase();
        if (!haystack.includes(searchValue.toLowerCase())) return false;
      }
      return true;
    });
  }, [candidates, statusFilter, modelFilter, searchValue]);

  const totalCount = candidates.length;
  const filteredCount = filteredCandidates.length;

  function handleRowClick(candidateId) {
    if (!candidateId) return;
    const audio = audioRef.current;
    if (audio) {
      try {
        audio.currentTime = 0;
        audio.play();
      } catch {
        // ignore
      }
      setTimeout(() => {
        window.location.href = `/candidates/${candidateId}`;
      }, 120);
    } else {
      window.location.href = `/candidates/${candidateId}`;
    }
  }

  function handleWhatsappClick(event, phoneDigits) {
    event.stopPropagation();
    if (!phoneDigits) return;
    window.open(`https://wa.me/${phoneDigits}`, '_blank');
  }

  function handleLinkedinClick(event, url) {
    event.stopPropagation();
    if (!url) return;
    window.open(url, '_blank');
  }

  function openModal() {
    setFormState(DEFAULT_FORM);
    setFormError('');
    setDuplicateInfo(null);
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
    setFormError('');
    setDuplicateInfo(null);
  }

  function handleFormChange(event) {
    const { name, value } = event.target;
    setFormState((prev) => {
      if (name === 'country') {
        const nextCode = PHONE_CODE_BY_COUNTRY[value] || prev.phoneCode;
        return { ...prev, country: value, phoneCode: nextCode };
      }
      return { ...prev, [name]: value };
    });
    setFormError('');
    setDuplicateInfo(null);
  }

  function normalizeForm() {
    const phoneDigits = normalizePhoneDigits(formState.phone, formState.phoneCode);
    const linkedinNormalized = normalizeLinkedin(formState.linkedin);
    const linkedinSubmit = formatLinkedinForSubmit(formState.linkedin);
    return {
      ...formState,
      phoneDigits,
      linkedinNormalized,
      linkedinSubmit,
    };
  }

  function validateForm(state) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!state.email || !emailRegex.test(state.email)) {
      return 'Enter a valid email address.';
    }
    if (!state.phoneDigits) {
      return 'Enter a valid phone number.';
    }
    if (!state.linkedinNormalized.includes('linkedin.com')) {
      return 'LinkedIn URL must point to linkedin.com.';
    }
    return '';
  }

  function findDuplicate(state) {
    for (const candidate of candidates) {
      const matches = [];
      if (state.name && normalizeName(candidate.name) === normalizeName(state.name)) {
        matches.push('name');
      }
      const storedPhone = normalizeStoredPhone(candidate.phone, candidate.country);
      if (state.phoneDigits && storedPhone && state.phoneDigits === storedPhone) {
        matches.push('phone');
      }
      if (state.linkedinNormalized && normalizeLinkedin(candidate.linkedin) === state.linkedinNormalized) {
        matches.push('linkedin');
      }
      if (matches.length) {
        return { candidate, fields: matches };
      }
    }
    return null;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setFormError('');
    setDuplicateInfo(null);
    const normalized = normalizeForm();
    const validation = validateForm(normalized);
    if (validation) {
      setFormError(validation);
      return;
    }

    const duplicate = findDuplicate(normalized);
    if (duplicate) {
      try {
        const details = await fetchCandidateById(duplicate.candidate.candidate_id);
        setDuplicateInfo({
          candidate: { ...duplicate.candidate, ...details },
          fields: duplicate.fields,
        });
      } catch (error) {
        console.error('Failed to fetch duplicate details', error);
        setDuplicateInfo({
          candidate: duplicate.candidate,
          fields: duplicate.fields,
        });
      }
      return;
    }

    await submitCandidate(normalized);
  }

  async function submitCandidate(values) {
    setSubmitting(true);
    try {
      await createCandidate({
        name: values.name || null,
        email: values.email,
        phone: values.phoneDigits,
        linkedin: values.linkedinSubmit,
        country: values.country || null,
        stage: 'Contactado',
        created_by: (localStorage.getItem('user_email') || '').toLowerCase(),
      });
      setToast('Candidate created!');
      setTimeout(() => setToast(''), 2500);
      closeModal();
      loadCandidates();
    } catch (error) {
      setFormError(error.message || 'Failed to create candidate.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <SidebarLayout>
      <audio id="click-sound" ref={audioRef} src="/assets/sounds/transition_tables.mp3" preload="auto" />
      <div className="filters-top-bar">
        <h1 className="page-title">Candidates</h1>
        <button className="new-btn" type="button" onClick={openModal}>
          New
        </button>
      </div>

      <div className="table-controls-wrapper" role="region" aria-label="Table controls">
        <div className="left-controls">
          <div className="datatable-summary">
            Showing {filteredCount} of {totalCount} candidates
          </div>
        </div>
        <div className="filters-bar">
          <label className="sr-only" htmlFor="statusFilter">Status</label>
          <select
            id="statusFilter"
            className="filter-select"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="modelFilter">Model</label>
          <select
            id="modelFilter"
            className="filter-select"
            value={modelFilter}
            onChange={(event) => setModelFilter(event.target.value)}
          >
            {MODEL_OPTIONS.map((option) => (
              <option key={option.value || 'all-models'} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="right-controls">
          <label htmlFor="searchByName" className="sr-only">Search by name</label>
          <input
            type="text"
            id="searchByName"
            placeholder="Search by name..."
            className="name-search-input"
            onChange={(event) => {
              const value = event.target.value;
              clearTimeout(searchDebounceRef.current);
              searchDebounceRef.current = setTimeout(() => setSearchValue(value), 150);
            }}
          />
        </div>
      </div>

      <div className="table-container" role="region" aria-label="Candidates table">
        {loading ? (
          <p>Loading candidates…</p>
        ) : (
          <table id="candidatesTable">
            <thead>
              <tr>
                <th>Condition</th>
                <th>Full Name</th>
                <th>Country</th>
                <th>Whatsapp</th>
                <th>LinkedIn</th>
              </tr>
            </thead>
            <tbody id="candidatesTableBody">
              {filteredCandidates.length === 0 && (
                <tr>
                  <td colSpan={5}>No data available</td>
                </tr>
              )}
              {filteredCandidates.map((candidate) => {
                const status = (candidate.status || 'unhired').toLowerCase();
                const chipClass = status === 'active' ? 'status-active' : 'status-unhired';
                const phoneDigits = normalizeStoredPhone(candidate.phone, candidate.country);
                return (
                  <tr key={candidate.candidate_id} onClick={() => handleRowClick(candidate.candidate_id)}>
                    <td className="condition-cell">
                      <span className={`status-chip ${chipClass}`}>{status || 'unhired'}</span>
                    </td>
                    <td>{candidate.name || '—'}</td>
                    <td>{candidate.country || '—'}</td>
                    <td>
                      {phoneDigits ? (
                        <button
                          type="button"
                          className="icon-button whatsapp"
                          onClick={(event) => handleWhatsappClick(event, phoneDigits)}
                        >
                          <i className="fab fa-whatsapp" aria-hidden="true" />
                        </button>
                      ) : '—'}
                    </td>
                    <td>
                      {candidate.linkedin ? (
                        <button
                          type="button"
                          className="icon-button linkedin"
                          onClick={(event) => handleLinkedinClick(event, candidate.linkedin)}
                        >
                          <i className="fab fa-linkedin-in" aria-hidden="true" />
                        </button>
                      ) : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {modalOpen && (
        <CandidateModal
          formState={formState}
          submitting={submitting}
          formError={formError}
          duplicateInfo={duplicateInfo}
          onChange={handleFormChange}
          onClose={closeModal}
          onSubmit={handleSubmit}
        />
      )}

      {toast && (
        <div id="candidateCreateToast" className="candidate-toast" role="status">
          {toast}
        </div>
      )}

      <LogoutFab />
    </SidebarLayout>
  );
}

function CandidateModal({ formState, submitting, formError, duplicateInfo, onChange, onClose, onSubmit }) {
  return (
    <div id="candidateCreateModal" className="candidate-modal-overlay" role="dialog" aria-modal="true">
      <div className="candidate-modal">
        <button className="modal-close-btn" id="candidateModalCloseBtn" type="button" aria-label="Close" onClick={onClose}>
          &times;
        </button>
        <h2 id="candidateModalTitle">Add Candidate</h2>
        <p className="modal-description">Create a new candidate and make them available to every pipeline.</p>
        {formError ? <div id="candidateFormError" className="candidate-form-error">{formError}</div> : null}
        {duplicateInfo && (
          <div id="candidateDuplicateBox" className="candidate-duplicate-box">
            <strong>A candidate with this information already exists.</strong>
            <div id="candidateDuplicateFields" className="duplicate-fields">
              {duplicateInfo.fields?.length ? (
                <p>Matched on: {duplicateInfo.fields.join(', ')}</p>
              ) : null}
              <p>Name: {duplicateInfo.candidate?.name || '—'}</p>
              <p>Email: {duplicateInfo.candidate?.email || '—'}</p>
              <p>Phone: {duplicateInfo.candidate?.phone || '—'}</p>
              <p>LinkedIn: {duplicateInfo.candidate?.linkedin || '—'}</p>
            </div>
            <button
              type="button"
              className="duplicate-link"
              id="openExistingCandidateBtn"
              onClick={() => {
                if (duplicateInfo?.candidate?.candidate_id) {
                  window.location.href = `/candidates/${encodeURIComponent(duplicateInfo.candidate.candidate_id)}`;
                }
              }}
            >
              Open existing candidate
            </button>
          </div>
        )}

        <form id="candidateCreateForm" className="candidate-form" onSubmit={onSubmit}>
          <label className="candidate-field">
            <span>Full name</span>
            <input
              type="text"
              id="candidateFullName"
              name="name"
              placeholder="Full name"
              value={formState.name}
              onChange={onChange}
              autoComplete="name"
            />
          </label>

          <label className="candidate-field required">
            <span>Email <span className="required-marker">*</span></span>
            <input
              type="email"
              id="candidateEmail"
              name="email"
              placeholder="Email *"
              value={formState.email}
              onChange={onChange}
              autoComplete="email"
              required
            />
          </label>

          <label className="candidate-field">
            <span>Country</span>
            <select
              id="candidateCountry"
              name="country"
              value={formState.country}
              onChange={onChange}
            >
              <option value="">Select country…</option>
              {Object.keys(PHONE_CODE_BY_COUNTRY).map((country) => (
                <option key={country} value={country}>
                  {country}
                </option>
              ))}
            </select>
          </label>

          <div className="candidate-field">
            <span>Phone <span className="required-marker">*</span></span>
            <div className="phone-split">
              <select
                id="candidatePhoneCode"
                name="phoneCode"
                value={formState.phoneCode}
                onChange={onChange}
              >
                {Object.entries(PHONE_CODE_BY_COUNTRY).map(([country, code]) => (
                  <option key={country} value={code}>
                    {country} +{code}
                  </option>
                ))}
              </select>
              <input
                type="tel"
                id="candidatePhone"
                name="phone"
                placeholder="Phone number *"
                value={formState.phone}
                onChange={onChange}
                autoComplete="tel"
                required
              />
            </div>
          </div>

          <label className="candidate-field required">
            <span>LinkedIn URL <span className="required-marker">*</span></span>
            <input
              type="url"
              id="candidateLinkedin"
              name="linkedin"
              placeholder="https://linkedin.com/in/username *"
              value={formState.linkedin}
              onChange={onChange}
              autoComplete="url"
              required
            />
          </label>

          <button type="submit" id="candidateModalSubmit" className="create-btn" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create Candidate'}
          </button>
        </form>
      </div>
    </div>
  );
}

function normalizeName(name) {
  return (name || '').toString().trim().toLowerCase();
}

function normalizeLinkedin(url) {
  if (!url) return '';
  let clean = url.trim().toLowerCase();
  clean = clean.replace(/^https?:\/\//, '');
  clean = clean.replace(/^www\./, '');
  clean = clean.replace(/\/+$/, '');
  return clean;
}

function formatLinkedinForSubmit(url) {
  if (!url) return '';
  let clean = url.trim();
  if (!/^https?:\/\//i.test(clean)) {
    clean = `https://${clean.replace(/^\/+/, '')}`;
  }
  return clean;
}

function normalizePhoneDigits(rawPhone, phoneCode) {
  const digits = (rawPhone || '').replace(/\D/g, '');
  if (!digits) return '';
  const code = (phoneCode || '').replace(/\D/g, '');
  if (code && !digits.startsWith(code)) {
    return code + digits;
  }
  return digits;
}

function normalizeStoredPhone(phone, country) {
  const digits = (phone || '').toString().replace(/\D/g, '');
  if (!digits) return '';
  const code = PHONE_CODE_BY_COUNTRY[country] || '';
  if (code && !digits.startsWith(code) && digits.length <= 11) {
    return code + digits;
  }
  return digits;
}

export default CandidatesPage;
