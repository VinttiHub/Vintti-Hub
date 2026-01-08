import { useEffect, useMemo, useState } from 'react';
import SidebarLayout from '../../components/layout/SidebarLayout.jsx';
import usePageStylesheet from '../../hooks/usePageStylesheet.js';
import LogoutFab from '../../components/common/LogoutFab.jsx';
import {
  createOpportunity,
  fetchAccounts,
  fetchLatestSourcingDate,
  fetchOpportunities,
  fetchUsers,
  linkCandidateHire,
  postInterviewingEntry,
  postSourcingEntry,
  searchCandidates,
  updateOpportunityFields,
  updateOpportunityStage,
} from '../../services/opportunitiesService.js';
import { API_BASE_URL } from '../../constants/api.js';
import { resolveAvatar } from '../../utils/avatars.js';

function normalizeEmail(value) {
  return String(value || '').trim().toLowerCase();
}

const STAGE_OPTIONS = [
  'Close Win',
  'Closed Lost',
  'Negotiating',
  'Interviewing',
  'Sourcing',
  'NDA Sent',
  'Deep Dive',
];

const STAGE_ORDER = [
  'Negotiating',
  'Interviewing',
  'Sourcing',
  'NDA Sent',
  'Deep Dive',
  'Close Win',
  'Closed Lost',
];

const HR_ALLOWED_EMAILS = new Set(
  [
    'pilar@vintti.com',
    'pilar.fernandez@vintti.com',
    'jazmin@vintti.com',
    'agostina@vintti.com',
    'agustina.barbero@vintti.com',
    'agustina.ferrari@vintti.com',
    'josefina@vintti.com',
    'constanza@vintti.com',
    'julieta@vintti.com',
  ].map(normalizeEmail),
);

const SALES_ALLOWED_EMAILS = new Set(
  [
    'agustin@vintti.com',
    'bahia@vintti.com',
    'lara@vintti.com',
    'mariano@vintti.com',
  ].map(normalizeEmail),
);

function formatDaysAgo(dateStr) {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  if (Number.isNaN(date)) return '-';
  const now = new Date();
  const diffTime = now - date;
  return Math.max(0, Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1);
}

function calculateDaysBetween(startStr, endStr) {
  if (!startStr || !endStr) return '-';
  const start = new Date(startStr);
  const end = new Date(endStr);
  if (Number.isNaN(start) || Number.isNaN(end)) return '-';
  return Math.floor((end - start) / (1000 * 60 * 60 * 24));
}

function stageColor(stage) {
  if (!stage) return '';
  return `stage-color-${String(stage).toLowerCase().replace(/\s+/g, '-')}`;
}

function initialsFromName(value) {
  return (String(value || '')
    .trim()
    .split(/\s+/)
    .map((chunk) => chunk[0] || '')
    .join('')
    .slice(0, 2) || '—').toUpperCase();
}

function initialForSales(key) {
  const lower = String(key || '').toLowerCase();
  if (lower.includes('bahia')) return 'BL';
  if (lower.includes('lara')) return 'LR';
  if (lower.includes('marian')) return 'MS';
  if (lower.includes('agustin')) return 'AM';
  return '--';
}

function badgeClassForSales(key) {
  const lower = String(key || '').toLowerCase();
  if (lower.includes('bahia')) return 'bl';
  if (lower.includes('lara')) return 'lr';
  if (lower.includes('marian')) return 'ms';
  if (lower.includes('agustin')) return 'am';
  return '';
}

function useAllowedUsers() {
  const [sales, setSales] = useState([]);
  const [hr, setHr] = useState([]);

  useEffect(() => {
    let ignore = false;
    async function loadUsers() {
      try {
        const users = await fetchUsers();
        if (ignore) return;
        const normalizedUsers = (Array.isArray(users) ? users : []).map((user) => ({
          ...user,
          email_vintti: normalizeEmail(user.email_vintti),
        }));
        setSales(
          normalizedUsers
            .filter((u) => SALES_ALLOWED_EMAILS.has(u.email_vintti))
            .sort((a, b) => (a.user_name || '').localeCompare(b.user_name || '')),
        );
        setHr(normalizedUsers.filter((u) => HR_ALLOWED_EMAILS.has(u.email_vintti)));
      } catch (error) {
        console.error('Failed to load users', error);
      }
    }
    loadUsers();
    return () => {
      ignore = true;
    };
  }, []);

  return { sales, hr };
}

function OpportunityBadge({ email, label }) {
  const normalizedEmail = normalizeEmail(email);
  const key = String(normalizedEmail || label || '').toLowerCase();
  const initials = initialForSales(key);
  const bubble = badgeClassForSales(key);
  const avatar = resolveAvatar(normalizedEmail || key);
  const tip = label || normalizedEmail || 'Assign Sales Lead';
  return (
    <div className="sales-lead lead-tip" data-tip={tip}>
      <span className={`lead-bubble ${bubble}`}>{initials}</span>
      {avatar ? <img className="lead-avatar" src={avatar} alt="" /> : null}
    </div>
  );
}

function HRBadge({ email, label }) {
  const normalizedEmail = normalizeEmail(email);
  const initials = initialsFromName(label || normalizedEmail);
  const avatar = resolveAvatar(normalizedEmail);
  const name = label || normalizedEmail || 'Assign HR Lead';
  return (
    <div className="hr-lead lead-tip" data-tip={name}>
      <span className="lead-bubble">{initials}</span>
      {avatar ? <img className="lead-avatar" src={avatar} alt="" /> : null}
    </div>
  );
}

function OpportunitiesPage() {
  usePageStylesheet('/assets/css/opportunities.css');
  const { sales, hr } = useAllowedUsers();
  const [accounts, setAccounts] = useState([]);
  const [opps, setOpps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stageFilters, setStageFilters] = useState(() => new Set(STAGE_OPTIONS.filter((s) => s !== 'Close Win' && s !== 'Closed Lost')));
  const [salesFilters, setSalesFilters] = useState(new Set());
  const [hrFilters, setHrFilters] = useState(new Set());
  const [searchText, setSearchText] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [toast, setToast] = useState('');
  const [stageModal, setStageModal] = useState({ type: null, opportunity: null });
  const [closeWinSearch, setCloseWinSearch] = useState({ results: [], selected: null, term: '' });
  const [replacementCandidates, setReplacementCandidates] = useState([]);

  useEffect(() => {
    let ignore = false;
    async function loadAccounts() {
      try {
        const list = await fetchAccounts();
        if (!ignore) setAccounts(list || []);
      } catch (error) {
        console.error('Failed to load accounts', error);
      }
    }
    loadAccounts();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (sales.length && salesFilters.size === 0) {
      setSalesFilters(new Set(['Unassigned', ...sales.map((user) => user.user_name)]));
    }
  }, [sales, salesFilters.size]);

  useEffect(() => {
    if (hr.length && hrFilters.size === 0) {
      setHrFilters(new Set(['Assign HR Lead', ...hr.map((user) => user.user_name)]));
    }
  }, [hr, hrFilters.size]);

  useEffect(() => {
    let ignore = false;
    async function loadOpportunities() {
      setLoading(true);
      try {
        const data = await fetchOpportunities();
        const enriched = await Promise.all(
          data.map(async (opp) => {
            let latest = null;
            if (opp.opp_stage === 'Sourcing') {
              try {
                const result = await fetchLatestSourcingDate(opp.opportunity_id);
                latest = result?.latest_sourcing_date || null;
              } catch {
                latest = null;
              }
            }
            const days = computeDaysForStage(opp);
            const batchDays = latest
              ? computeDaysSince(new Date(latest))
              : opp.nda_signature_or_start_date
                ? computeDaysSince(new Date(opp.nda_signature_or_start_date))
                : null;
            return {
              ...opp,
              latest_sourcing_date: latest,
              daysOpen: days,
              daysSinceBatch: batchDays,
            };
          }),
        );
        if (!ignore) setOpps(enriched);
      } catch (error) {
        console.error('Failed to load opportunities', error);
      } finally {
        if (!ignore) setLoading(false);
      }
    }
    loadOpportunities();
    return () => {
      ignore = true;
    };
  }, []);

  const grouped = useMemo(() => {
    const byStage = {};
    opps.forEach((opp) => {
      if (!byStage[opp.opp_stage]) byStage[opp.opp_stage] = [];
      byStage[opp.opp_stage].push(opp);
    });
    STAGE_ORDER.forEach((stage) => {
      if (byStage[stage]) {
        byStage[stage].sort((a, b) => {
          if (stage === 'Sourcing') {
            return (b.daysSinceBatch ?? -Infinity) - (a.daysSinceBatch ?? -Infinity);
          }
          const aDate = a.nda_signature_or_start_date ? new Date(a.nda_signature_or_start_date) : new Date(0);
          const bDate = b.nda_signature_or_start_date ? new Date(b.nda_signature_or_start_date) : new Date(0);
          return bDate - aDate;
        });
      }
    });
    return byStage;
  }, [opps]);

  const filteredRows = useMemo(() => {
    const rows = [];
    STAGE_ORDER.forEach((stage) => {
      const stageRows = grouped[stage] || [];
      stageRows.forEach((opp) => {
        if (stageFilters.size && !stageFilters.has(opp.opp_stage)) return;
        if (salesFilters.size) {
          const label = displayNameForSales(opp, sales);
          if (!salesFilters.has(label)) return;
        }
        if (hrFilters.size) {
          const label = displayNameForHR(opp.opp_hr_lead, hr);
          if (!hrFilters.has(label)) return;
        }
        if (searchText) {
          const haystack = `${opp.client_name} ${opp.opp_position_name}`.toLowerCase();
          if (!haystack.includes(searchText.toLowerCase())) return;
        }
        rows.push(opp);
      });
    });
    return rows;
  }, [grouped, stageFilters, salesFilters, hrFilters, searchText]);

  function handleStageChange(opp, newStage) {
    if (['Sourcing', 'Interviewing', 'Close Win', 'Closed Lost'].includes(newStage)) {
      setStageModal({ type: newStage, opportunity: opp });
      return;
    }
    patchStage(opp.opportunity_id, newStage);
  }

  async function patchStage(opportunityId, newStage) {
    try {
      await updateOpportunityStage(opportunityId, newStage);
      setOpps((prev) => prev.map((opp) => (opp.opportunity_id === opportunityId ? { ...opp, opp_stage: newStage } : opp)));
      setToast('✨ Stage updated!');
      setTimeout(() => setToast(''), 2500);
      if (newStage === 'Negotiating') {
        sendNegotiatingReminder(opportunityId);
      }
    } catch (error) {
      alert(error.message);
    }
  }

  async function handleSalesLeadChange(opp, value) {
    const normalizedValue = normalizeEmail(value);
    try {
      await updateOpportunityFields(opp.opportunity_id, { opp_sales_lead: normalizedValue || null });
      const selected = sales.find((user) => user.email_vintti === normalizedValue);
      setOpps((prev) => prev.map((row) => (row.opportunity_id === opp.opportunity_id
        ? {
            ...row,
            opp_sales_lead: normalizedValue || null,
            sales_lead: normalizedValue || null,
            sales_lead_name: selected?.user_name || '',
          }
        : row)));
    } catch (error) {
      alert(error.message || 'Failed to update Sales Lead');
    }
  }

  async function handleHRLeadChange(opp, value) {
    const normalizedValue = normalizeEmail(value);
    try {
      await updateOpportunityFields(opp.opportunity_id, { opp_hr_lead: normalizedValue || null });
      setOpps((prev) => prev.map((row) => (row.opportunity_id === opp.opportunity_id
        ? { ...row, opp_hr_lead: normalizedValue || null }
        : row)));
      await sendHRLeadAssignmentEmail(opp.opportunity_id, normalizedValue);
    } catch (error) {
      alert(error.message || 'Failed to update HR Lead');
    }
  }

  async function sendHRLeadAssignmentEmail(opportunityId, email) {
    if (!email) return;
    try {
      await fetch(`${API_BASE_URL}/send_email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          to: [email],
          subject: 'You’ve been assigned a new search – Vintti Hub',
          body: 'New opportunity assigned',
          html: true,
          content_type: 'text/html',
        }),
      });
    } catch (error) {
      console.error('Failed to send HR assignment email', error);
    }
  }

  async function sendNegotiatingReminder(opportunityId) {
    try {
      const opportunity = await fetch(`${API_BASE_URL}/opportunities/${opportunityId}`, { credentials: 'include' }).then((res) => res.json());
      const hrEmail = normalizeEmail(opportunity.opp_hr_lead);
      if (!hrEmail) return;
      await fetch(`${API_BASE_URL}/send_email`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          to: [hrEmail, 'angie@vintti.com'],
          subject: `You’ve been assigned a new search – ${opportunity.client_name || 'Client'}`,
          body: `
            <div style="font-family: Inter, Arial, sans-serif;">
              <p>Hi there,</p>
              <p>You’ve been assigned a new search for ${opportunity.client_name || 'a client'}.</p>
              <p><strong>Role:</strong> ${opportunity.opp_position_name || 'Role'}</p>
              <p><strong>Model:</strong> ${opportunity.opp_model || 'Model'}</p>
            </div>
          `,
          html: true,
          content_type: 'text/html',
        }),
      });
    } catch (error) {
      console.error('Failed to send negotiating reminder', error);
    }
  }

  async function handleCommentBlur(opp, comment) {
    try {
      await updateOpportunityFields(opp.opportunity_id, { comments: comment });
    } catch (error) {
      console.error('Failed to save comment', error);
    }
  }

  function closeStageModal() {
    setStageModal({ type: null, opportunity: null });
    setCloseWinSearch({ results: [], selected: null, term: '' });
  }

  async function handleSourcingSubmit(date) {
    const opportunity = stageModal.opportunity;
    if (!opportunity) return;
    try {
      if (!opportunity.nda_signature_or_start_date) {
        await updateOpportunityFields(opportunity.opportunity_id, { nda_signature_or_start_date: date });
      } else {
        if (!opportunity.opp_hr_lead) throw new Error('HR Lead is required.');
        await postSourcingEntry({
          opportunity_id: opportunity.opportunity_id,
          user_id: opportunity.opp_hr_lead,
          since_sourcing: date,
        });
      }
      await patchStage(opportunity.opportunity_id, 'Sourcing');
    } catch (error) {
      alert(error.message);
    } finally {
      closeStageModal();
    }
  }

  async function handleInterviewingSubmit(date) {
    const opportunity = stageModal.opportunity;
    if (!opportunity) return;
    try {
      await postInterviewingEntry({
        opportunity_id: opportunity.opportunity_id,
        since_interviewing: date,
      });
      await patchStage(opportunity.opportunity_id, 'Interviewing');
    } catch (error) {
      alert(error.message);
    } finally {
      closeStageModal();
    }
  }

  async function handleCloseLostSubmit({ date, reason, details }) {
    const opportunity = stageModal.opportunity;
    if (!opportunity) return;
    try {
      await updateOpportunityFields(opportunity.opportunity_id, {
        opp_close_date: date,
        motive_close_lost: reason,
        ...(details ? { details_close_lost: details } : {}),
      });
      await patchStage(opportunity.opportunity_id, 'Closed Lost');
    } catch (error) {
      alert(error.message);
    } finally {
      closeStageModal();
    }
  }

  async function handleCloseWinSubmit({ date }) {
    const opportunity = stageModal.opportunity;
    if (!opportunity || !closeWinSearch.selected) return;
    try {
      await updateOpportunityFields(opportunity.opportunity_id, {
        opp_close_date: date,
        candidato_contratado: closeWinSearch.selected.candidate_id,
      });
      await linkCandidateHire(closeWinSearch.selected.candidate_id, opportunity.opportunity_id);
      await patchStage(opportunity.opportunity_id, 'Close Win');
      window.location.href = `/candidates/${closeWinSearch.selected.candidate_id}#hire`;
    } catch (error) {
      alert(error.message);
    } finally {
      closeStageModal();
    }
  }

  async function handleCreateOpportunity(formData) {
    try {
      await createOpportunity(formData);
      setShowCreateModal(false);
      window.location.reload();
    } catch (error) {
      alert(error.message);
    }
  }

  const stageOptions = STAGE_OPTIONS;

  return (
    <SidebarLayout>
      <div className="page-wrapper opportunities-page">
        <header className="page-header">
          <h1 className="page-title">Opportunities</h1>
          <button className="new-btn" type="button" onClick={() => setShowCreateModal(true)}>New</button>
        </header>

        <section className="filters-top-bar" aria-label="Filters">
          <div className="multi-filter">
            <div className="filter-header filter-toggle" data-target="filterStage">
              <label>Stage</label>
            </div>
            <div className="multi-select">
              {stageOptions.map((stage) => (
                <label key={stage} className="checkbox-line">
                  <input
                    type="checkbox"
                    checked={stageFilters.has(stage)}
                    onChange={(event) => {
                      setStageFilters((prev) => {
                        const next = new Set(prev);
                        if (event.target.checked) next.add(stage);
                        else next.delete(stage);
                        return next;
                      });
                    }}
                  />
                  {stage}
                </label>
              ))}
            </div>
          </div>

          <div className="multi-filter">
            <div className="filter-header filter-toggle">
              <label>Sales Lead</label>
            </div>
            <div className="multi-select">
              {['Unassigned', ...sales.map((user) => user.user_name)].map((label) => (
                <label key={label} className="checkbox-line">
                  <input
                    type="checkbox"
                    checked={salesFilters.has(label)}
                    onChange={(event) => {
                      setSalesFilters((prev) => {
                        const next = new Set(prev);
                        if (event.target.checked) next.add(label);
                        else next.delete(label);
                        return next;
                      });
                    }}
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>

          <div className="multi-filter">
            <div className="filter-header filter-toggle">
              <label>HR Lead</label>
            </div>
            <div className="multi-select">
              {['Assign HR Lead', ...hr.map((user) => user.user_name)].map((label) => (
                <label key={label} className="checkbox-line">
                  <input
                    type="checkbox"
                    checked={hrFilters.has(label)}
                    onChange={(event) => {
                      setHrFilters((prev) => {
                        const next = new Set(prev);
                        if (event.target.checked) next.add(label);
                        else next.delete(label);
                        return next;
                      });
                    }}
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>

          <div className="text-filter">
            <input
              type="text"
              placeholder="Search account..."
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
            />
          </div>
        </section>

        <section className="table-card" aria-label="Opportunities table">
          {loading ? (
            <p>Loading opportunities…</p>
          ) : (
            <div className="table-scroll-wrapper">
              <table id="opportunityTable" style={{ minWidth: '1400px', width: 'max-content' }}>
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Account</th>
                    <th>Position</th>
                    <th>Type</th>
                    <th>Model</th>
                    <th>Sales Lead</th>
                    <th>HR Lead</th>
                    <th>Comment</th>
                    <th>Days</th>
                    <th>Days Since Batch</th>
                  </tr>
                </thead>
                <tbody id="opportunityTableBody">
                  {filteredRows.map((opp) => (
                    <tr key={opp.opportunity_id}>
                      <td>
                        <select
                          className={`stage-dropdown ${stageColor(opp.opp_stage)}`}
                          value={opp.opp_stage}
                          disabled={['Close Win', 'Closed Lost'].includes(opp.opp_stage)}
                          onChange={(event) => handleStageChange(opp, event.target.value)}
                        >
                          {STAGE_OPTIONS.map((stage) => (
                            <option key={stage} value={stage}>{stage}</option>
                          ))}
                        </select>
                      </td>
                      <td>{opp.client_name || ''}</td>
                      <td>{opp.opp_position_name || ''}</td>
                      <td>{opp.opp_type}</td>
                      <td>{opp.opp_model}</td>
                      <td className="sales-lead-cell">
                        <div className="sales-lead-cell-wrap">
                          <OpportunityBadge
                            email={normalizeEmail(opp.opp_sales_lead || opp.sales_lead)}
                            label={displayNameForSales(opp, sales)}
                          />
                          <select
                            className="sales-lead-dropdown"
                            value={normalizeEmail(opp.opp_sales_lead || opp.sales_lead)}
                            onChange={(event) => handleSalesLeadChange(opp, event.target.value)}
                          >
                            <option value="">Assign Sales Lead</option>
                            {sales.map((user) => (
                              <option key={user.email_vintti} value={user.email_vintti}>
                                {user.user_name}
                              </option>
                            ))}
                          </select>
                        </div>
                      </td>
                      <td className="hr-lead-cell">
                        <div className="hr-lead-cell-wrap">
                          <HRBadge email={opp.opp_hr_lead} label={displayNameForHR(opp.opp_hr_lead, hr)} />
                          <select
                            className="hr-lead-dropdown"
                            value={normalizeEmail(opp.opp_hr_lead)}
                            onChange={(event) => handleHRLeadChange(opp, event.target.value)}
                          >
                            <option value="">Assign HR Lead</option>
                            {hr.map((user) => (
                              <option key={user.email_vintti} value={user.email_vintti}>
                                {user.user_name}
                              </option>
                            ))}
                          </select>
                        </div>
                      </td>
                      <td>
                        <input
                          type="text"
                          className="comment-input"
                          defaultValue={opp.comments || ''}
                          onBlur={(event) => handleCommentBlur(opp, event.target.value)}
                        />
                      </td>
                      <td>{formatDaysCell(opp)}</td>
                      <td>{renderBatchCell(opp)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {toast ? <div id="stage-toast" className="sparkle-show">{toast}</div> : null}
      </div>
      <LogoutFab />
      {showCreateModal && (
        <CreateOpportunityModal
          accounts={accounts}
          salesUsers={sales}
          replacementCandidates={replacementCandidates}
          onReplacementSearch={async (term) => {
            if (!term || term.length < 2) return;
            try {
              const results = await searchCandidates(term);
              setReplacementCandidates(results);
            } catch (error) {
              console.error('Replacement search failed', error);
            }
          }}
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateOpportunity}
        />
      )}
      {stageModal.type && (
        <StageModal
          stage={stageModal.type}
          opportunity={stageModal.opportunity}
          closeWinSearch={closeWinSearch}
          setCloseWinSearch={setCloseWinSearch}
          onClose={closeStageModal}
          onSourcingSubmit={handleSourcingSubmit}
          onInterviewingSubmit={handleInterviewingSubmit}
          onCloseLostSubmit={handleCloseLostSubmit}
          onCloseWinSubmit={handleCloseWinSubmit}
        />
      )}
    </SidebarLayout>
  );
}

function computeDaysSince(date) {
  const now = new Date();
  return Math.ceil((now - date) / (1000 * 60 * 60 * 24)) - 1;
}

function computeDaysForStage(opp) {
  if (['Close Win', 'Closed Lost'].includes(opp.opp_stage)) {
    if (opp.nda_signature_or_start_date && opp.opp_close_date) {
      return calculateDaysBetween(opp.nda_signature_or_start_date, opp.opp_close_date);
    }
  }
  if (opp.nda_signature_or_start_date) {
    return formatDaysAgo(opp.nda_signature_or_start_date);
  }
  return '-';
}

function formatDaysCell(opp) {
  if (typeof opp.daysOpen === 'number') return opp.daysOpen;
  if (typeof opp.daysOpen === 'string') return opp.daysOpen;
  return '-';
}

function renderBatchCell(opp) {
  if (opp.opp_stage !== 'Sourcing') return opp.daysSinceBatch ?? '-';
  if (opp.daysSinceBatch == null) return '-';
  const n = opp.daysSinceBatch;
  if (n >= 6) return `${n} ⚠️`;
  if (n >= 3) return `${n} ⏳`;
  if (n >= 0) return `${n} 🌱`;
  return '-';
}

function CreateOpportunityModal({
  accounts,
  salesUsers,
  replacementCandidates,
  onReplacementSearch,
  onClose,
  onSubmit,
}) {
  const [form, setForm] = useState({
    client_name: '',
    opp_model: 'Staffing',
    position_name: '',
    sales_lead: '',
    opp_type: 'New',
    replacement_of: '',
    replacement_end_date: '',
  });

  function handleChange(event) {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  function isValid() {
    const basic = form.client_name && form.opp_model && form.position_name && form.sales_lead && form.opp_type;
    if (!basic) return false;
    if (form.opp_type === 'Replacement') {
      return form.replacement_of && form.replacement_end_date;
    }
    return true;
  }

  function handleSubmit(event) {
    event.preventDefault();
    const payload = {
      client_name: form.client_name.trim(),
      opp_model: form.opp_model,
      position_name: form.position_name.trim(),
      sales_lead: form.sales_lead,
      opp_type: form.opp_type,
      opp_stage: 'Deep Dive',
    };
    if (form.opp_type === 'Replacement') {
      const id = parseInt(String(form.replacement_of).split(' - ')[0], 10);
      if (!Number.isFinite(id)) {
        alert('Please select a valid candidate to replace.');
        return;
      }
      payload.replacement_of = id;
      payload.replacement_end_date = form.replacement_end_date;
    }
    onSubmit(payload);
  }

  return (
    <div className="popup-overlay" style={{ display: 'flex' }}>
      <div className="popup-content">
        <button className="close-btn" type="button" onClick={onClose} aria-label="Close">&times;</button>
        <h2 className="popup-title">New Opportunity</h2>
        <form onSubmit={handleSubmit} className="popup-form">
          <div className="popup-row">
            <div className="popup-field">
              <label htmlFor="client_name">Client Name</label>
              <div className="input-with-button">
                <input
                  type="text"
                  id="client_name"
                  name="client_name"
                  list="accountList"
                  value={form.client_name}
                  onChange={handleChange}
                  placeholder="Search by name..."
                  autoComplete="off"
                />
                <datalist id="accountList">
                  {accounts.map((account) => (
                    <option key={account.account_id || account.account_name} value={account.account_name} />
                  ))}
                </datalist>
              </div>
            </div>
            <div className="popup-field">
              <label htmlFor="opp_model">Model</label>
              <select id="opp_model" name="opp_model" value={form.opp_model} onChange={handleChange}>
                <option value="Staffing">Staffing</option>
                <option value="Recruiting">Recruiting</option>
              </select>
            </div>
          </div>

          <div className="popup-field">
            <label htmlFor="position_name">Position Name</label>
            <input
              type="text"
              id="position_name"
              name="position_name"
              placeholder="E.g. Senior Accountant"
              value={form.position_name}
              onChange={handleChange}
            />
          </div>

          <div className="popup-field">
            <label htmlFor="sales_lead">Sales Lead</label>
            <select id="sales_lead" name="sales_lead" value={form.sales_lead} onChange={handleChange}>
              <option value="" disabled>Select Sales Lead</option>
              {salesUsers.map((user) => (
                <option key={user.email_vintti} value={user.email_vintti}>
                  {user.user_name}
                </option>
              ))}
            </select>
          </div>

          <div className="popup-field">
            <label htmlFor="opp_type">Opportunity type</label>
            <select id="opp_type" name="opp_type" value={form.opp_type} onChange={handleChange}>
              <option value="New">New</option>
              <option value="Replacement">Replacement</option>
            </select>
          </div>

          {form.opp_type === 'Replacement' && (
            <div id="replacementFields">
              <div className="popup-field">
                <label htmlFor="replacementCandidate">Candidate to replace</label>
                <input
                  type="text"
                  id="replacementCandidate"
                  name="replacement_of"
                  list="replacementCandidates"
                  value={form.replacement_of}
                  onChange={(event) => {
                    handleChange(event);
                    onReplacementSearch(event.target.value);
                  }}
                />
                <datalist id="replacementCandidates">
                  {replacementCandidates.map((candidate) => (
                    <option
                      key={candidate.candidate_id}
                      value={`${candidate.candidate_id} - ${candidate.name}`}
                    />
                  ))}
                </datalist>
              </div>
              <div className="popup-field">
                <label htmlFor="replacementEndDate">Replacement end date</label>
                <input
                  type="date"
                  id="replacementEndDate"
                  name="replacement_end_date"
                  value={form.replacement_end_date}
                  onChange={handleChange}
                />
              </div>
            </div>
          )}

          <button type="submit" className="create-btn" disabled={!isValid()}>Create</button>
        </form>
      </div>
    </div>
  );
}

function StageModal({
  stage,
  opportunity,
  closeWinSearch,
  setCloseWinSearch,
  onClose,
  onSourcingSubmit,
  onInterviewingSubmit,
  onCloseLostSubmit,
  onCloseWinSubmit,
}) {
  const [formValue, setFormValue] = useState({
    date: '',
    reason: '',
    details: '',
  });

  useEffect(() => {
    setFormValue({ date: '', reason: '', details: '' });
  }, [stage, opportunity]);

  if (!opportunity) return null;

  const modalTitle = {
    Sourcing: 'Set Sourcing Date',
    Interviewing: 'Interviewing start date',
    'Close Win': 'Set Close Win Info',
    'Closed Lost': 'Closed Lost Details',
  }[stage];

  return (
    <div className="popup-overlay" style={{ display: 'flex' }}>
      <div className="popup-content">
        <button className="close-btn" type="button" onClick={onClose} aria-label="Close">&times;</button>
        <h2>{modalTitle}</h2>
        {stage === 'Sourcing' && (
          <>
            <label htmlFor="sourcingDate">{opportunity.nda_signature_or_start_date ? 'Since last sourcing' : 'Start date'}</label>
            <input
              type="date"
              id="sourcingDate"
              value={formValue.date}
              onChange={(event) => setFormValue((prev) => ({ ...prev, date: event.target.value }))}
            />
            <button
              type="button"
              onClick={() => {
                if (!formValue.date) {
                  alert('Please select a date.');
                  return;
                }
                onSourcingSubmit(formValue.date);
              }}
            >
              Save
            </button>
          </>
        )}

        {stage === 'Interviewing' && (
          <>
            <label htmlFor="interviewingDate">Start date</label>
            <input
              type="date"
              id="interviewingDate"
              value={formValue.date}
              onChange={(event) => setFormValue((prev) => ({ ...prev, date: event.target.value }))}
            />
            <button
              type="button"
              onClick={() => {
                if (!formValue.date) {
                  alert('Please select a date.');
                  return;
                }
                onInterviewingSubmit(formValue.date);
              }}
            >
              Save
            </button>
          </>
        )}

        {stage === 'Closed Lost' && (
          <>
            <div className="popup-field">
              <label htmlFor="closeLostDate">Close Date</label>
              <input
                type="date"
                id="closeLostDate"
                value={formValue.date}
                onChange={(event) => setFormValue((prev) => ({ ...prev, date: event.target.value }))}
              />
            </div>
            <div className="popup-field">
              <label htmlFor="closeLostReason">Reason</label>
              <select
                id="closeLostReason"
                value={formValue.reason}
                onChange={(event) => setFormValue((prev) => ({ ...prev, reason: event.target.value }))}
              >
                <option value="">Select reason</option>
                <option value="Ghosting">Ghosting</option>
                <option value="Pricing">Pricing</option>
                <option value="Shopping">Shopping</option>
                <option value="Competencia">Competencia</option>
                <option value="Timing">Timing</option>
                <option value="Vinttis Fault">Vintti’s Fault</option>
                <option value="Other">Other</option>
              </select>
            </div>
            <div className="popup-field">
              <label htmlFor="closeLostDetails">Details</label>
              <textarea
                id="closeLostDetails"
                rows={3}
                value={formValue.details}
                onChange={(event) => setFormValue((prev) => ({ ...prev, details: event.target.value }))}
              />
            </div>
            <button
              type="button"
              onClick={() => {
                if (!formValue.date || !formValue.reason) {
                  alert('Please fill in both date and reason.');
                  return;
                }
                onCloseLostSubmit({
                  date: formValue.date,
                  reason: formValue.reason,
                  details: formValue.details,
                });
              }}
            >
              Save
            </button>
          </>
        )}

        {stage === 'Close Win' && (
          <>
            <label htmlFor="closeWinHireInput">Hire</label>
            <input
              type="text"
              id="closeWinHireInput"
              value={closeWinSearch.term}
              onChange={async (event) => {
                const term = event.target.value;
                setCloseWinSearch((prev) => ({ ...prev, term }));
                if (term.trim().length < 2) {
                  setCloseWinSearch({ term, results: [], selected: null });
                  return;
                }
                try {
                  const results = await searchCandidates(term);
                  setCloseWinSearch({ term, results, selected: null });
                } catch (error) {
                  console.error('Close Win search failed', error);
                }
              }}
            />
            <div className="autocomplete-list" style={{ display: closeWinSearch.results.length ? 'block' : 'none' }}>
              {closeWinSearch.results.map((candidate) => (
                <div
                  key={candidate.candidate_id}
                  className="autocomplete-item"
                  role="button"
                  onClick={() => setCloseWinSearch((prev) => ({ ...prev, selected: candidate, term: `${candidate.candidate_id} - ${candidate.name}`, results: [] }))}
                >
                  {candidate.candidate_id} - {candidate.name}
                </div>
              ))}
            </div>
            <label htmlFor="closeWinDate">Close Date</label>
            <input
              type="date"
              id="closeWinDate"
              value={formValue.date}
              onChange={(event) => setFormValue((prev) => ({ ...prev, date: event.target.value }))}
            />
            <button
              type="button"
              onClick={() => {
                if (!formValue.date || !closeWinSearch.selected) {
                  alert('Please select a hire and date.');
                  return;
                }
                onCloseWinSubmit({ date: formValue.date });
              }}
            >
              Save
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default OpportunitiesPage;
function displayNameForSales(opp, salesList) {
  const email = normalizeEmail(opp.opp_sales_lead || opp.sales_lead);
  if (!email) return 'Unassigned';
  const user = salesList.find((u) => u.email_vintti === email);
  return user?.user_name || opp.sales_lead_name || email;
}

function displayNameForHR(email, hrList) {
  const normalized = normalizeEmail(email);
  if (!normalized) return 'Assign HR Lead';
  const user = hrList.find((u) => u.email_vintti === normalized);
  return user?.user_name || normalized;
}
