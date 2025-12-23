import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import SidebarLayout from '../../components/layout/SidebarLayout.jsx';
import LogoutFab from '../../components/common/LogoutFab.jsx';
import usePageStylesheet from '../../hooks/usePageStylesheet.js';
import {
  deleteAccountPdf,
  fetchAccount,
  fetchAccountCandidates,
  fetchAccountOpportunities,
  listAccountPdfs,
  renameAccountPdf,
  updateAccount,
  updateCandidateField,
  uploadAccountPdfs,
} from '../../services/accountDetailService.js';

function AccountDetailPage() {
  usePageStylesheet('/assets/css/account-details.css');
  const navigate = useNavigate();
  const { id } = useParams();
  const [account, setAccount] = useState(null);
  const [opportunities, setOpportunities] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [pdfs, setPdfs] = useState([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [openSections, setOpenSections] = useState({ info: true, opportunities: true });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [comments, setComments] = useState('');
  const [painPoints, setPainPoints] = useState('');
  const [pdfUploading, setPdfUploading] = useState(false);
  const [showDiscountAlert, setShowDiscountAlert] = useState(true);

  useEffect(() => {
    if (!id) return;
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const [acc, opps, emps, docs] = await Promise.all([
          fetchAccount(id),
          fetchAccountOpportunities(id),
          fetchAccountCandidates(id),
          listAccountPdfs(id),
        ]);
        setAccount(acc);
        setOpportunities(opps || []);
        setCandidates(emps || []);
        setPdfs(docs || []);
        setComments(acc.comments || '');
        setPainPoints(acc.pain_points || '');
      } catch (err) {
        console.error(err);
        setError('Unable to load account details.');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [id]);

  const staffingEmployees = useMemo(
    () => candidates.filter((candidate) => candidate.opp_model === 'Staffing'),
    [candidates],
  );
  const recruitingEmployees = useMemo(
    () => candidates.filter((candidate) => candidate.opp_model === 'Recruiting'),
    [candidates],
  );

  const discountAlerts = useMemo(() => {
    const now = new Date();
    const currentMonthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    return staffingEmployees.filter((candidate) => {
      const range = parseRange(candidate.discount_daterange);
      if (!candidate.discount_dolar || !range.end) return false;
      const end = new Date(range.end);
      const endMonthStart = new Date(end.getFullYear(), end.getMonth(), 1);
      return endMonthStart >= currentMonthStart;
    });
  }, [staffingEmployees]);

  async function handleAccountUpdate(patch) {
    if (!id) return;
    try {
      await updateAccount(id, patch);
      setAccount((prev) => ({ ...(prev || {}), ...patch }));
    } catch (err) {
      console.error(err);
      alert('Failed to update account.');
    }
  }

  async function handlePdfUpload(files) {
    if (!files.length || !id) return;
    setPdfUploading(true);
    try {
      await uploadAccountPdfs(id, files);
      const docs = await listAccountPdfs(id);
      setPdfs(docs || []);
    } catch (err) {
      console.error(err);
      alert('Upload failed.');
    } finally {
      setPdfUploading(false);
    }
  }

  async function handlePdfRename(key, newName) {
    if (!id) return;
    try {
      await renameAccountPdf(id, key, newName);
      const docs = await listAccountPdfs(id);
      setPdfs(docs || []);
    } catch (err) {
      console.error(err);
      alert('Failed to rename file.');
    }
  }

  async function handlePdfDelete(key) {
    if (!id) return;
    try {
      await deleteAccountPdf(id, key);
      const docs = await listAccountPdfs(id);
      setPdfs(docs || []);
    } catch (err) {
      console.error(err);
      alert('Failed to delete file.');
    }
  }

  function handleGoBack() {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  }

  function toggleSection(section) {
    setOpenSections((prev) => ({ ...prev, [section]: !prev[section] }));
  }

  async function handleCandidateField(candidateId, field, value, opportunityId) {
    try {
      await updateCandidateField(candidateId, field, value, opportunityId);
      setCandidates((prev) =>
        prev.map((candidate) => (candidate.candidate_id === candidateId ? { ...candidate, [field]: value } : candidate)),
      );
    } catch (err) {
      console.error(err);
      alert(`Failed to update ${field}`);
    }
  }

  if (!id) {
    return (
      <SidebarLayout>
        <div className="main-content">
          <p>Missing account id.</p>
        </div>
        <LogoutFab />
      </SidebarLayout>
    );
  }

  return (
    <SidebarLayout>
      <main className="main-content account-details">
        <button id="goBackButton" className="go-back-button" type="button" onClick={handleGoBack}>
          ← Go Back
        </button>

        {loading ? (
          <p>Loading account…</p>
        ) : error ? (
          <p className="range-error">{error}</p>
        ) : (
          <>
            <h1 className="page-title">Account Details</h1>
            <div className="tab-selector" role="tablist" aria-label="Account sections">
              <button
                className={`tab-btn ${activeTab === 'overview' ? 'active' : ''}`}
                type="button"
                onClick={() => setActiveTab('overview')}
              >
                Overview
              </button>
              <button
                className={`tab-btn ${activeTab === 'employees' ? 'active' : ''}`}
                type="button"
                onClick={() => setActiveTab('employees')}
              >
                Employees
              </button>
            </div>

            {activeTab === 'overview' && (
              <section className="tab-content active" id="overview">
                <AccordionSection
                  title="Account Info 🏢"
                  open={openSections.info}
                  onToggle={() => toggleSection('info')}
                >
                  <div className="grid-two-cols">
                    <p>
                      <strong>Name:</strong>
                      <input
                        id="account-client-name"
                        className="editable-input"
                        type="text"
                        value={account?.client_name || ''}
                        onChange={(event) => setAccount((prev) => ({ ...prev, client_name: event.target.value }))}
                        onBlur={() => handleAccountUpdate({ client_name: account?.client_name || '' })}
                      />
                    </p>
                    <InfoRow label="Size" value={account?.size} />
                    <InfoRow label="Timezone" value={account?.timezone} />
                    <InfoRow label="State" value={account?.state} />
                    <p>
                      <strong>LinkedIn:</strong>
                      <a id="linkedin-link" href={account?.linkedin || '#'} target="_blank" rel="noopener">
                        Open
                      </a>
                      <button className="edit-btn" type="button" onClick={() => promptLink('linkedin')}>
                        ✎
                      </button>
                    </p>
                    <p>
                      <strong>Website:</strong>
                      <a id="website-link" href={account?.website || '#'} target="_blank" rel="noopener">
                        Open
                      </a>
                      <button className="edit-btn" type="button" onClick={() => promptLink('website')}>
                        ✎
                      </button>
                    </p>
                    <InfoRow label="Contract" value={account?.contract} />
                    <InfoRow label="Total Staffing Fee" value={formatCurrency(account?.tsf)} />
                    <InfoRow label="Total Staffing Revenue" value={formatCurrency(account?.tsr)} />
                    <InfoRow label="Total Recruiting Revenue" value={formatCurrency(account?.trr)} />
                  </div>

                  <ContractsBlock
                    pdfs={pdfs}
                    uploading={pdfUploading}
                    onUpload={handlePdfUpload}
                    onRename={handlePdfRename}
                    onDelete={handlePdfDelete}
                  />

                  <div className="comment-box">
                    <label htmlFor="comments">
                      <strong>Comments:</strong>
                    </label>
                    <textarea
                      id="comments"
                      rows={4}
                      value={comments}
                      onChange={(event) => setComments(event.target.value)}
                      onBlur={() => handleAccountUpdate({ comments })}
                    />
                  </div>

                  <div className="comment-box">
                    <label htmlFor="pain-points">
                      <strong>Pain Points:</strong>
                    </label>
                    <textarea
                      id="pain-points"
                      rows={4}
                      value={painPoints}
                      onChange={(event) => setPainPoints(event.target.value)}
                      onBlur={() => handleAccountUpdate({ pain_points: painPoints })}
                    />
                  </div>
                </AccordionSection>

                <AccordionSection
                  title="Associated Opportunities 💼"
                  open={openSections.opportunities}
                  onToggle={() => toggleSection('opportunities')}
                >
                  <table className="styled-table" role="table" aria-label="Associated opportunities">
                    <thead>
                      <tr>
                        <th>Position</th>
                        <th>Stage</th>
                        <th>Hire</th>
                      </tr>
                    </thead>
                    <tbody>
                      {opportunities.length === 0 ? (
                        <tr>
                          <td colSpan={3}>No opportunities found</td>
                        </tr>
                      ) : (
                        opportunities.map((opp) => (
                          <tr
                            key={opp.opportunity_id}
                            onClick={() =>
                              window.open(
                                `opportunity-detail.html?id=${encodeURIComponent(opp.opportunity_id)}`,
                                '_blank',
                                'noopener',
                              )
                            }
                            style={{ cursor: 'pointer' }}
                          >
                            <td>{opp.opp_position_name || '—'}</td>
                            <td>{opp.opp_stage || '—'}</td>
                            <td>{opp.candidate_name || <span className="no-hire">Not hired yet</span>}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </AccordionSection>

                {discountAlerts.length > 0 && showDiscountAlert && (
                  <DiscountAlert candidates={discountAlerts} onDismiss={() => setShowDiscountAlert(false)} />
                )}
              </section>
            )}

            {activeTab === 'employees' && (
              <section className="tab-content active" id="employees">
                <div className="card">
                  <h2>Employees – Staffing</h2>
                  <table className="styled-table expandable">
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>Employee</th>
                        <th>Start Date</th>
                        <th>End Date</th>
                        <th>Position</th>
                        <th>Fee</th>
                        <th>Salary</th>
                        <th>Revenue</th>
                        <th>Discount $</th>
                        <th>Discount Range</th>
                        <th>Referral $</th>
                        <th>Referral Range</th>
                        <th>Buy Out $</th>
                        <th>Buy Out Range</th>
                      </tr>
                    </thead>
                    <tbody>
                      {staffingEmployees.length === 0 ? (
                        <tr>
                          <td colSpan={14}>No employees in Staffing</td>
                        </tr>
                      ) : (
                        staffingEmployees.map((employee) => (
                          <StaffingRow key={employee.candidate_id} employee={employee} onChange={handleCandidateField} />
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="card">
                  <h2>Employees – Recruiting</h2>
                  <table className="styled-table expandable">
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>Employee</th>
                        <th>Start Date</th>
                        <th>End Date</th>
                        <th>Position</th>
                        <th>Probation (Days)</th>
                        <th>Salary</th>
                        <th>Revenue</th>
                        <th>Referral $</th>
                        <th>Referral Range</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recruitingEmployees.length === 0 ? (
                        <tr>
                          <td colSpan={10}>No employees in Recruiting</td>
                        </tr>
                      ) : (
                        recruitingEmployees.map((employee) => (
                          <RecruitingRow key={employee.candidate_id} employee={employee} onChange={handleCandidateField} />
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
          </>
        )}
      </main>
      <LogoutFab />
    </SidebarLayout>
  );

  function promptLink(field) {
    const current = account?.[field] || '';
    const newValue = window.prompt(`Enter new ${field} URL:`, current);
    if (!newValue) return;
    handleAccountUpdate({ [field]: newValue });
  }
}

function InfoRow({ label, value }) {
  return (
    <p>
      <strong>{label}:</strong> {value || '—'}
    </p>
  );
}

function AccordionSection({ title, open, onToggle, children }) {
  return (
    <div className={`accordion-section ${open ? 'open' : ''}`}>
      <div className="accordion-header" role="button" tabIndex={0} onClick={onToggle} onKeyDown={(event) => event.key === 'Enter' && onToggle()}>
        {title}
      </div>
      {open && <div className="accordion-content">{children}</div>}
    </div>
  );
}

function ContractsBlock({ pdfs, uploading, onUpload, onRename, onDelete }) {
  const [selectedFiles, setSelectedFiles] = useState([]);

  function handleFileChange(event) {
    setSelectedFiles(Array.from(event.target.files || []).filter((file) => file.type === 'application/pdf'));
  }

  return (
    <section className="contracts-block" id="contracts-block">
      <div className="contracts-header">
        <div className="contracts-titles">
          <h3 id="contracts-title">Contracts</h3>
          <p className="subtle">Upload and manage all contract PDFs for this account.</p>
        </div>
        <div className="upload-row">
          <input type="file" id="pdfUpload" accept="application/pdf" multiple onChange={handleFileChange} />
          <button id="uploadPdfBtn" type="button" onClick={() => onUpload(selectedFiles)} disabled={!selectedFiles.length || uploading}>
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      </div>

      <div id="pdfPreviewContainer" className="contracts-list">
        {pdfs.length === 0 ? (
          <div className="contract-item" style={{ justifyContent: 'center', color: '#666' }}>
            📄 No contracts uploaded yet — use the Upload button.
          </div>
        ) : (
          pdfs.map((pdf) => <PdfRow key={pdf.key} pdf={pdf} onRename={onRename} onDelete={onDelete} />)
        )}
      </div>
    </section>
  );
}

function PdfRow({ pdf, onRename, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(pdf.name);

  async function save() {
    let nextName = name.trim();
    if (!nextName) return;
    if (!/\.pdf$/i.test(nextName)) nextName += '.pdf';
    nextName = nextName.replace(/[\\/]/g, '-');
    await onRename(pdf.key, nextName);
    setEditing(false);
  }

  return (
    <div className="contract-item">
      <div className="contract-left">
        <span className="file-icon">📄</span>
        {editing ? (
          <input className="file-edit" value={name} onChange={(event) => setName(event.target.value)} onKeyDown={(event) => {
            if (event.key === 'Enter') save();
            if (event.key === 'Escape') {
              setEditing(false);
              setName(pdf.name);
            }
          }} />
        ) : (
          <a className="file-name" href={pdf.url} target="_blank" rel="noopener noreferrer">
            {pdf.name}
          </a>
        )}
      </div>
      <div className="contract-right">
        {!editing && (
          <button className="icon-btn rename-btn" type="button" onClick={() => setEditing(true)}>
            Rename
          </button>
        )}
        {editing && (
          <>
            <button className="icon-btn save-btn" type="button" onClick={save}>
              Save
            </button>
            <button
              className="icon-btn cancel-btn"
              type="button"
              onClick={() => {
                setEditing(false);
                setName(pdf.name);
              }}
            >
              Cancel
            </button>
          </>
        )}
        <a className="link-btn" href={pdf.url} target="_blank" rel="noopener noreferrer">
          Open
        </a>
        <button className="icon-btn icon-danger delete-btn" type="button" onClick={() => onDelete(pdf.key)}>
          Delete
        </button>
      </div>
    </div>
  );
}

function StaffingRow({ employee, onChange }) {
  const range = parseRange(employee.discount_daterange);
  const referralRange = parseRange(employee.referral_daterange);
  const buyoutRange = parseRange(employee.buyout_daterange);
  return (
    <tr>
      <td>{renderStatusChip(employee.status || (employee.end_date ? 'inactive' : 'active'))}</td>
      <td>
        <a href={`/candidates/${employee.candidate_id}`} className="employee-link">
          {employee.name || '—'}
        </a>
      </td>
      <td>
        <input
          type="date"
          className="input-chip"
          value={dateValue(employee.start_date)}
          onChange={(event) => onChange(employee.candidate_id, 'start_date', event.target.value || null, employee.opportunity_id)}
        />
      </td>
      <td>
        <input
          type="date"
          className="input-chip"
          value={dateValue(employee.end_date)}
          onChange={(event) => onChange(employee.candidate_id, 'end_date', event.target.value || null, employee.opportunity_id)}
        />
      </td>
      <td>{employee.opp_position_name || '—'}</td>
      <td>{formatCurrency(employee.employee_fee)}</td>
      <td>{formatCurrency(employee.employee_salary)}</td>
      <td>{formatCurrency(employee.employee_revenue)}</td>
      <td>
        <CurrencyInput
          value={employee.discount_dolar}
          onChange={(value) => onChange(employee.candidate_id, 'discount_dolar', value, employee.opportunity_id)}
        />
      </td>
      <td>
        <RangeInput
          start={range.start}
          end={range.end}
          onChange={(value) => onChange(employee.candidate_id, 'discount_daterange', value, employee.opportunity_id)}
        />
      </td>
      <td>
        <CurrencyInput
          value={employee.referral_dolar}
          onChange={(value) => onChange(employee.candidate_id, 'referral_dolar', value, employee.opportunity_id)}
        />
      </td>
      <td>
        <RangeInput
          start={referralRange.start}
          end={referralRange.end}
          onChange={(value) => onChange(employee.candidate_id, 'referral_daterange', value, employee.opportunity_id)}
        />
      </td>
      <td>
        <CurrencyInput
          value={employee.buyout_dolar}
          onChange={(value) => onChange(employee.candidate_id, 'buyout_dolar', value, employee.opportunity_id)}
        />
      </td>
      <td>
        <RangeInput
          start={buyoutRange.start}
          end={buyoutRange.end}
          onChange={(value) => onChange(employee.candidate_id, 'buyout_daterange', value, employee.opportunity_id)}
        />
      </td>
    </tr>
  );
}

function RecruitingRow({ employee, onChange }) {
  const referralRange = parseRange(employee.referral_daterange);
  return (
    <tr>
      <td>{renderStatusChip(employee.status || (employee.end_date ? 'inactive' : 'active'))}</td>
      <td>
        <a href={`/candidates/${employee.candidate_id}`} className="employee-link">
          {employee.name || '—'}
        </a>
      </td>
      <td>
        <input
          type="date"
          className="input-chip"
          value={dateValue(employee.start_date)}
          onChange={(event) => onChange(employee.candidate_id, 'start_date', event.target.value || null, employee.opportunity_id)}
        />
      </td>
      <td>
        <input
          type="date"
          className="input-chip"
          value={dateValue(employee.end_date)}
          onChange={(event) => onChange(employee.candidate_id, 'end_date', event.target.value || null, employee.opportunity_id)}
        />
      </td>
      <td>{employee.opp_position_name || '—'}</td>
      <td>{employee.probation_days || '—'}</td>
      <td>{formatCurrency(employee.employee_salary)}</td>
      <td>{formatCurrency(employee.employee_revenue)}</td>
      <td>
        <CurrencyInput
          value={employee.referral_dolar}
          onChange={(value) => onChange(employee.candidate_id, 'referral_dolar', value, employee.opportunity_id)}
        />
      </td>
      <td>
        <RangeInput
          start={referralRange.start}
          end={referralRange.end}
          onChange={(value) => onChange(employee.candidate_id, 'referral_daterange', value, employee.opportunity_id)}
        />
      </td>
    </tr>
  );
}

function CurrencyInput({ value, onChange }) {
  const [display, setDisplay] = useState(value ? String(value) : '');
  useEffect(() => {
    setDisplay(value ? String(value) : '');
  }, [value]);

  function handleBlur() {
    const numeric = parseFloat(display.replace(/[^\d.]/g, ''));
    if (Number.isNaN(numeric)) {
      setDisplay('');
      onChange(null);
    } else {
      onChange(numeric);
      setDisplay(String(numeric));
    }
  }

  return (
    <input
      type="text"
      className="input-chip"
      value={display}
      onChange={(event) => setDisplay(event.target.value)}
      onBlur={handleBlur}
      placeholder="$0"
    />
  );
}

function RangeInput({ start, end, onChange }) {
  const [localStart, setLocalStart] = useState(start || '');
  const [localEnd, setLocalEnd] = useState(end || '');

  useEffect(() => {
    setLocalStart(start || '');
    setLocalEnd(end || '');
  }, [start, end]);

  function emit(nextStart, nextEnd) {
    if (!nextStart && !nextEnd) {
      onChange(null);
    } else {
      onChange(`[${nextStart || ''}, ${nextEnd || ''}]`);
    }
  }

  return (
    <div className="range-input">
      <input
        type="date"
        value={localStart}
        onChange={(event) => {
          setLocalStart(event.target.value);
          emit(event.target.value, localEnd);
        }}
      />
      <input
        type="date"
        value={localEnd}
        onChange={(event) => {
          setLocalEnd(event.target.value);
          emit(localStart, event.target.value);
        }}
      />
    </div>
  );
}

function DiscountAlert({ candidates, onDismiss }) {
  return (
    <aside id="discount-alert" className="discount-alert" aria-live="polite">
      <button id="close-discount-alert" className="close-alert-btn" type="button" onClick={onDismiss}>
        ❌
      </button>
      <strong>
        ⚡ <span id="discount-count">{candidates.length}</span> discounts active
      </strong>
      <ul id="discount-list">
        {candidates.map((candidate) => {
          const range = parseRange(candidate.discount_daterange);
          return (
            <li key={candidate.candidate_id}>
              <strong>{candidate.name}</strong> — {candidate.opp_position_name || '—'} · until {range.end || '—'}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

function renderStatusChip(statusText) {
  const status = (statusText || '').toLowerCase();
  if (status.includes('inactive')) return <span className="status-chip status-inactive">Inactive</span>;
  return <span className="status-chip status-active">Active</span>;
}

function dateValue(raw) {
  if (!raw) return '';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return '';
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function formatCurrency(value) {
  if (value == null || value === '') return '—';
  const number = Number(value);
  if (Number.isNaN(number)) return value;
  return `$${number.toLocaleString()}`;
}

function parseRange(value) {
  if (!value || typeof value !== 'string') return { start: '', end: '' };
  const match = value.replace(/[\[\]]/g, '').split(',').map((part) => part.trim());
  return { start: match[0] || '', end: match[1] || '' };
}

export default AccountDetailPage;
