import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import SidebarLayout from '../../components/layout/SidebarLayout.jsx';
import LogoutFab from '../../components/common/LogoutFab.jsx';
import usePageStylesheet from '../../hooks/usePageStylesheet.js';
import {
  createSalaryUpdate,
  fetchCandidate,
  fetchCandidateEquipments,
  fetchCandidateOpportunities,
  fetchHire,
  fetchHireOpportunity,
  fetchSalaryUpdates,
  updateCandidate,
  updateHire,
} from '../../services/candidateDetailService.js';
import { formatCurrency } from '../../utils/format.js';
import AiAssistantModal from './components/AiAssistantModal.jsx';
import ResumeTab from './components/ResumeTab.jsx';

const TABS = ['overview', 'resume', 'opportunities', 'hire'];

function CandidateDetailPage() {
  usePageStylesheet('/assets/css/candidate-details.css');
  const { id } = useParams();
  const navigate = useNavigate();
  const candidateId = Number(id);

  const [candidate, setCandidate] = useState(null);
  const [tab, setTab] = useState('overview');
  const [hire, setHire] = useState(null);
  const [hireModel, setHireModel] = useState('');
  const [salaryUpdates, setSalaryUpdates] = useState([]);
  const [opportunities, setOpportunities] = useState([]);
  const [equipments, setEquipments] = useState([]);
  const [comments, setComments] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [resumeFrameKey, setResumeFrameKey] = useState(0);

  useEffect(() => {
    if (!candidateId) return;
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const [cand, hireData, hireOpp, opps, updates, gear] = await Promise.all([
          fetchCandidate(candidateId),
          fetchHire(candidateId),
          fetchHireOpportunity(candidateId),
          fetchCandidateOpportunities(candidateId),
          fetchSalaryUpdates(candidateId),
          fetchCandidateEquipments(candidateId),
        ]);
        setCandidate(cand);
        setComments(cand.comments || '');
        setHire(hireData);
        setHireModel((hireOpp?.opp_model || '').toLowerCase());
        setOpportunities(opps || []);
        setSalaryUpdates(updates || []);
        setEquipments(Array.isArray(gear) ? gear : []);
      } catch (err) {
        console.error(err);
        setError('Unable to load candidate.');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [candidateId]);

  async function handleCandidateUpdate(patch) {
    try {
      await updateCandidate(candidateId, patch);
      setCandidate((prev) => ({ ...(prev || {}), ...patch }));
    } catch (err) {
      console.error(err);
      alert('Failed to update candidate.');
    }
  }

  async function handleHireUpdate(patch) {
    try {
      const updated = await updateHire(candidateId, { ...patch, opportunity_id: hire?.opportunity_id });
      setHire(updated);
    } catch (err) {
      console.error(err);
      alert('Failed to update hire data.');
    }
  }

  async function handleSalaryUpdate(payload) {
    try {
      const body = { ...payload, opportunity_id: hire?.opportunity_id, model: hireModel };
      if (!body.date) {
        body.date = new Date().toISOString().slice(0, 10);
      }
      await createSalaryUpdate(candidateId, body);
      const updates = await fetchSalaryUpdates(candidateId);
      setSalaryUpdates(updates || []);
    } catch (err) {
      console.error(err);
      alert('Failed to create salary update.');
    }
  }

  const latestSalaryUpdate = useMemo(() => (salaryUpdates && salaryUpdates.length ? salaryUpdates[0] : null), [salaryUpdates]);

  if (!candidateId) {
    return (
      <SidebarLayout>
        <div className="main-content">
          <p>Missing candidate id.</p>
        </div>
        <LogoutFab />
      </SidebarLayout>
    );
  }

  return (
    <SidebarLayout>
      <div className="candidate-detail">
        <div className="header-row">
          <button id="goBackButton" className="go-back-button" type="button" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/'))}>
            ← Go Back
          </button>

          <div className="tabs" role="tablist" aria-label="Candidate sections">
            {TABS.map((tabId) => (
              <button
                key={tabId}
                className={`tab ${tab === tabId ? 'active' : ''}`}
                type="button"
                onClick={() => setTab(tabId)}
              >
                {tabId.charAt(0).toUpperCase() + tabId.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <p>Loading candidate…</p>
        ) : error ? (
          <p className="range-error">{error}</p>
        ) : (
          <>
            {tab === 'overview' && (
              <OverviewTab
                candidate={candidate}
                comments={comments}
                onCommentsChange={setComments}
                onSaveComments={() => handleCandidateUpdate({ comments })}
                onUpdateField={handleCandidateUpdate}
                equipments={equipments}
                onOpenAi={() => setAiModalOpen(true)}
              />
            )}

            {tab === 'resume' && (
              <ResumeTab
                candidateId={candidateId}
                candidate={candidate}
                onOpenAi={() => setAiModalOpen(true)}
                onRefresh={() => setResumeFrameKey((prev) => prev + 1)}
                frameKey={resumeFrameKey}
              />
            )}

            {tab === 'opportunities' && (
              <OpportunitiesTab opportunities={opportunities} />
            )}

            {tab === 'hire' && (
              <HireTab
                hire={hire}
                hireModel={hireModel}
                salaryUpdates={salaryUpdates}
                latestUpdate={latestSalaryUpdate}
                onHireChange={handleHireUpdate}
                onCreateUpdate={handleSalaryUpdate}
              />
            )}
          </>
        )}
      </div>
      <LogoutFab />
      <AiAssistantModal
        open={aiModalOpen}
        candidateId={candidateId}
        candidate={candidate}
        onClose={() => setAiModalOpen(false)}
        onResumeReady={() => {
          setTab('resume');
          setResumeFrameKey((prev) => prev + 1);
        }}
      />
    </SidebarLayout>
  );
}

function OverviewTab({ candidate, comments, onCommentsChange, onSaveComments, onUpdateField, equipments, onOpenAi }) {
  return (
    <div id="overview" className="tab-content active">
      <div className="field">
        <label>Name</label>
        <input
          id="field-name"
          value={candidate?.name || ''}
          onChange={(event) => onUpdateField({ name: event.target.value })}
          onBlur={(event) => onUpdateField({ name: event.target.value })}
        />
      </div>

      <div className="overview-layout">
        <div className="grid">
          <div className="field">
            <label>Country</label>
            <select
              id="field-country"
              value={candidate?.country || ''}
              onChange={(event) => onUpdateField({ country: event.target.value })}
            >
              <option value="">—</option>
              {COUNTRIES.map((country) => (
                <option key={country} value={country}>
                  {country}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Phone</label>
            <div id="phone-field">
              <button
                id="wa-btn-overview"
                className={`icon-button whatsapp ${candidate?.phone ? 'is-visible' : ''}`}
                type="button"
                onClick={() => {
                  const digits = (candidate?.phone || '').replace(/\D/g, '');
                  if (digits) window.open(`https://wa.me/${digits}`, '_blank', 'noopener');
                }}
              >
                WhatsApp
              </button>
              <div
                id="field-phone"
                className="editable-pill"
                contentEditable
                suppressContentEditableWarning
                onBlur={(event) => onUpdateField({ phone: event.currentTarget.textContent })}
              >
                {candidate?.phone || '—'}
              </div>
            </div>
          </div>
          <div className="field">
            <label>Email</label>
            <input
              id="field-email"
              value={candidate?.email || ''}
              onChange={(event) => onUpdateField({ email: event.target.value })}
              onBlur={(event) => onUpdateField({ email: event.target.value })}
            />
          </div>
          <div className="field">
            <label>LinkedIn</label>
            <div className="linkedin-row">
              <input
                id="field-linkedin"
                value={candidate?.linkedin || ''}
                onChange={(event) => onUpdateField({ linkedin: event.target.value })}
                onBlur={(event) => onUpdateField({ linkedin: event.target.value })}
              />
              <button className="pill" type="button" onClick={onOpenAi}>
                ✨ AI Assistant
              </button>
            </div>
          </div>
          <div className="field">
            <label>Salary Range</label>
            <input
              id="field-salary"
              value={candidate?.salary_range || ''}
              onChange={(event) => onUpdateField({ salary_range: event.target.value })}
              onBlur={(event) => onUpdateField({ salary_range: event.target.value })}
            />
          </div>
          <div className="field">
            <label>English Level</label>
            <input
              id="field-english"
              value={candidate?.english_level || ''}
              onChange={(event) => onUpdateField({ english_level: event.target.value })}
              onBlur={(event) => onUpdateField({ english_level: event.target.value })}
            />
          </div>
        </div>

        <div className="comment-box">
          <label>Comments</label>
          <textarea
            value={comments}
            onChange={(event) => onCommentsChange(event.target.value)}
            onBlur={onSaveComments}
            rows={4}
          />
        </div>

        <div className="equipments-block">
          <label>Equipments</label>
          {equipments.length === 0 ? (
            <p>—</p>
          ) : (
            <div className="chips">
              {equipments.map((equipment) => (
                <span key={equipment} className="chip equip-chip">
                  {equipment}
                </span>
              ))}
            </div>
          )}
          <a id="equipments-details-link" href={`equipments.html?candidate_id=${candidate?.candidate_id}`} target="_blank" rel="noopener">
            View details
          </a>
        </div>
      </div>
    </div>
  );
}

function OpportunitiesTab({ opportunities }) {
  return (
    <div id="opportunities" className="tab-content active">
      <table id="opportunitiesTable" className="styled-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Model</th>
            <th>Position</th>
            <th>Sales Lead</th>
            <th>Stage</th>
            <th>Account</th>
            <th>HR Lead</th>
          </tr>
        </thead>
        <tbody>
          {(opportunities || []).map((opp) => (
            <tr key={opp.opportunity_id} onClick={() => window.open(`opportunity-detail.html?id=${opp.opportunity_id}`, '_blank', 'noopener')}>
              <td>{opp.opportunity_id}</td>
              <td>{opp.opp_model || ''}</td>
              <td>{opp.opp_position_name || ''}</td>
              <td>{opp.opp_sales_lead || ''}</td>
              <td>{opp.opp_stage || ''}</td>
              <td>{opp.client_name || ''}</td>
              <td>{opp.opp_hr_lead || ''}</td>
            </tr>
          ))}
          {!opportunities.length && (
            <tr>
              <td colSpan={7}>No opportunities</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function HireTab({ hire, hireModel, salaryUpdates, latestUpdate, onHireChange, onCreateUpdate }) {
  const [form, setForm] = useState({
    start_date: '',
    end_date: '',
    setup_fee: '',
    employee_salary: '',
    employee_fee: '',
    employee_revenue: '',
    working_schedule: '',
    pto: '',
    computer: '',
    extraperks: '',
    references_notes: '',
  });

  const [updateForm, setUpdateForm] = useState({ salary: '', fee: '', date: '' });

  useEffect(() => {
    if (hire) {
      setForm({
        start_date: (hire.start_date || '').slice(0, 10),
        end_date: (hire.end_date || '').slice(0, 10),
        setup_fee: hire.setup_fee || '',
        employee_salary: hire.employee_salary || '',
        employee_fee: hire.employee_fee || '',
        employee_revenue: (hireModel === 'recruiting' ? hire.employee_revenue_recruiting : hire.employee_revenue) || '',
        working_schedule: hire.working_schedule || '',
        pto: hire.pto || '',
        computer: hire.computer || '',
        extraperks: hire.extraperks || '',
        references_notes: hire.references_notes || '',
      });
    }
  }, [hire, hireModel]);

  return (
    <div id="hire" className="tab-content active">
      <div className="hire-form">
        <div className="field">
          <label>Start Date</label>
          <input
            type="date"
            value={form.start_date}
            onChange={(event) => setForm((prev) => ({ ...prev, start_date: event.target.value }))}
            onBlur={(event) => onHireChange({ start_date: event.target.value })}
          />
        </div>
        <div className="field">
          <label>End Date</label>
          <input
            type="date"
            value={form.end_date}
            onChange={(event) => setForm((prev) => ({ ...prev, end_date: event.target.value }))}
            onBlur={(event) => onHireChange({ end_date: event.target.value })}
          />
        </div>
        <div className="field">
          <label>Setup Fee</label>
          <input
            type="text"
            value={form.setup_fee}
            onChange={(event) => setForm((prev) => ({ ...prev, setup_fee: event.target.value }))}
            onBlur={(event) => onHireChange({ setup_fee: event.target.value })}
          />
        </div>
        <div className="field">
          <label>Salary</label>
          <input
            type="number"
            value={form.employee_salary}
            onChange={(event) => setForm((prev) => ({ ...prev, employee_salary: event.target.value }))}
            onBlur={(event) => onHireChange({ employee_salary: event.target.value })}
          />
        </div>
        <div className="field">
          <label>Fee</label>
          <input
            type="number"
            value={form.employee_fee}
            onChange={(event) => setForm((prev) => ({ ...prev, employee_fee: event.target.value }))}
            onBlur={(event) => onHireChange({ employee_fee: event.target.value })}
          />
        </div>
        <div className="field">
          <label>Revenue</label>
          <input
            type="number"
            value={form.employee_revenue}
            onChange={(event) => setForm((prev) => ({ ...prev, employee_revenue: event.target.value }))}
            onBlur={(event) => onHireChange({ employee_revenue: event.target.value })}
          />
        </div>
        <div className="field">
          <label>Working Schedule</label>
          <input
            type="text"
            value={form.working_schedule}
            onChange={(event) => setForm((prev) => ({ ...prev, working_schedule: event.target.value }))}
            onBlur={(event) => onHireChange({ working_schedule: event.target.value })}
          />
        </div>
        <div className="field">
          <label>PTO</label>
          <input
            type="text"
            value={form.pto}
            onChange={(event) => setForm((prev) => ({ ...prev, pto: event.target.value }))}
            onBlur={(event) => onHireChange({ pto: event.target.value })}
          />
        </div>
        <div className="field">
          <label>Computer</label>
          <input
            type="text"
            value={form.computer}
            onChange={(event) => setForm((prev) => ({ ...prev, computer: event.target.value }))}
            onBlur={(event) => onHireChange({ computer: event.target.value })}
          />
        </div>
        <div className="field">
          <label>Extra Perks</label>
          <textarea
            value={form.extraperks}
            onChange={(event) => setForm((prev) => ({ ...prev, extraperks: event.target.value }))}
            onBlur={(event) => onHireChange({ extraperks: event.target.value })}
          />
        </div>
        <div className="field">
          <label>References</label>
          <textarea
            value={form.references_notes}
            onChange={(event) => setForm((prev) => ({ ...prev, references_notes: event.target.value }))}
            onBlur={(event) => onHireChange({ references_notes: event.target.value })}
          />
        </div>
      </div>

      <div className="salary-updates">
        <h3>Salary Updates</h3>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            onCreateUpdate(updateForm);
            setUpdateForm({ salary: '', fee: '', date: '' });
          }}
        >
          <input
            type="number"
            placeholder="Salary"
            value={updateForm.salary}
            onChange={(event) => setUpdateForm((prev) => ({ ...prev, salary: event.target.value }))}
          />
          <input
            type="number"
            placeholder="Fee"
            value={updateForm.fee}
            onChange={(event) => setUpdateForm((prev) => ({ ...prev, fee: event.target.value }))}
          />
          <input
            type="date"
            value={updateForm.date}
            onChange={(event) => setUpdateForm((prev) => ({ ...prev, date: event.target.value }))}
          />
          <button type="submit">Save</button>
        </form>

        <table className="styled-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Salary</th>
              <th>Fee</th>
            </tr>
          </thead>
          <tbody>
            {(salaryUpdates || []).map((update) => (
              <tr key={update.update_id || update.id}>
                <td>{update.date || '—'}</td>
                <td>{formatCurrency(update.salary)}</td>
                <td>{formatCurrency(update.fee)}</td>
              </tr>
            ))}
            {!salaryUpdates.length && (
              <tr>
                <td colSpan={3}>No salary updates</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const COUNTRIES = [
  'Argentina',
  'Bolivia',
  'Brazil',
  'Chile',
  'Colombia',
  'Costa Rica',
  'Cuba',
  'Dominican Republic',
  'Ecuador',
  'El Salvador',
  'Guatemala',
  'Honduras',
  'Mexico',
  'United States',
  'Nicaragua',
  'Panama',
  'Paraguay',
  'Peru',
  'Uruguay',
  'Venezuela',
];

export default CandidateDetailPage;
