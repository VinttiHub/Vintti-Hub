import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import SidebarLayout from '../../components/layout/SidebarLayout.jsx';
import LogoutFab from '../../components/common/LogoutFab.jsx';
import usePageStylesheet from '../../hooks/usePageStylesheet.js';
import {
  createAccount,
  fetchAccountsLight,
  fetchAccountsList,
  patchAccount,
} from '../../services/crmService.js';
import { resolveAvatar } from '../../utils/avatars.js';

const allowedPriorityEmails = new Set([
  'agustin@vintti.com',
  'bahia@vintti.com',
  'angie@vintti.com',
  'lara@vintti.com',
  'agostina@vintti.com',
  'mariano@vintti.com',
]);

const leadSources = ['SEO', 'AI', 'Slack Community', 'Referral', 'Re-target', 'Outbound', 'Linkedin - Agus'];
const timezones = ['EST', 'CST', 'PST', 'MST', 'AST', 'HST'];
const typeOptions = ['NA', 'Firm', 'SMB', 'Startup'];
const sizeOptions = ['1-10', '11-50', '51-200', '201-500', '+500'];
const outsourceOptions = ['yes', 'no'];
const painPoints = ['NA', 'High salary', 'No real pain point', 'Cultural', 'Time zone', 'Knowledge', 'No time'];
const positions = [
  'Founder/Co-Founder',
  'President',
  'Vice President',
  'CEO',
  'COO',
  'CFO/Finance Manager',
  'CTO',
  'General Manager',
  'Hiring Manager',
  'Talent Acquisition/Recruiter',
  'Student/Freelancer',
  'Unemployed',
  'Other',
  'Unknown',
];

const statusOrder = ['Active Client', 'Lead in Process', 'Lead', 'Inactive Client', 'Lead Lost', '—'];

function CrmPage() {
  const navigate = useNavigate();
  usePageStylesheet('/assets/css/crm.css');
  const [accounts, setAccounts] = useState([]);
  const [referralOptions, setReferralOptions] = useState([]);
  const [searchValue, setSearchValue] = useState('');
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [modalError, setModalError] = useState('');
  const [formState, setFormState] = useState(initialFormState());
  const [priorityVisible, setPriorityVisible] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const email = (window.localStorage.getItem('user_email') || '').toLowerCase();
    setPriorityVisible(allowedPriorityEmails.has(email));
  }, []);

  useEffect(() => {
    loadAccounts();
    loadReferralClients();
  }, []);

  async function loadAccounts() {
    setLoading(true);
    try {
      const data = await fetchAccountsLight();
      setAccounts(data || []);
    } catch (error) {
      console.error('Failed to load accounts', error);
      setAccounts([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadReferralClients() {
    try {
      const list = await fetchAccountsList();
      const names = [...new Set((list || []).map((acc) => (acc.account_name || acc.client_name || '').trim()).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b));
      setReferralOptions(names);
    } catch (error) {
      console.warn('Could not load referral clients', error);
    }
  }

  const filteredAccounts = useMemo(() => {
    if (!searchValue) return accounts;
    return accounts.filter((account) =>
      (account.client_name || '').toLowerCase().includes(searchValue.toLowerCase()),
    );
  }, [accounts, searchValue]);

  async function handlePriorityChange(accountId, priority) {
    try {
      await patchAccount(accountId, { priority: priority || null });
      setAccounts((prev) =>
        prev.map((acc) => (acc.account_id === accountId ? { ...acc, priority } : acc)),
      );
    } catch (error) {
      console.error('Failed to update priority', error);
    }
  }

  function openModal() {
    setModalError('');
    setFormState(initialFormState());
    setShowModal(true);
  }

  function closeModal() {
    setShowModal(false);
    setModalError('');
  }

  function handleFormChange(event) {
    const { name, value } = event.target;
    setFormState((prev) => {
      if (name === 'referral_mode') {
        return {
          ...prev,
          referral_mode: value,
          ...(value === 'other' ? { referal_source: '' } : { referal_source_other: '' }),
        };
      }
      if (name === 'where_come_from') {
        const isReferral = (value || '').toLowerCase() === 'referral';
        return {
          ...prev,
          where_come_from: value,
          ...(isReferral
            ? {}
            : { referal_source: '', referal_source_other: '', referral_mode: 'existing' }),
        };
      }
      return { ...prev, [name]: value };
    });
    setModalError('');
  }

  async function handleCreateAccount(event) {
    event.preventDefault();
    if (!formState.where_come_from) {
      setModalError('Please select a lead source.');
      return;
    }
    const payload = normalizeAccountPayload(formState);
    try {
      await createAccount(payload);
      closeModal();
      loadAccounts();
    } catch (error) {
      setModalError(error.message || 'Failed to create account.');
    }
  }

  return (
    <SidebarLayout>
      <div className="filters-top-bar">
        <h1 className="page-title">CRM</h1>
        <button className="new-btn" type="button" onClick={openModal}>
          New
        </button>
      </div>

      <div className="crm-controls-bar">
        <div className="datatable-summary">
          Showing {filteredAccounts.length} of {accounts.length} accounts
        </div>
        <input
          type="text"
          id="searchClientInput"
          placeholder="Search by Client Name"
          className="crm-search-input"
          value={searchValue}
          onChange={(event) => setSearchValue(event.target.value)}
        />
      </div>

      <div className="table-container">
        {loading ? (
          <p>Loading accounts…</p>
        ) : (
          <table id="accountTable">
            <thead>
              <tr>
                <th>Client Name</th>
                <th>Status</th>
                <th>Sales Lead</th>
                <th>Contract</th>
                <th>TRR</th>
                <th>TSF</th>
                <th>TSR</th>
                {priorityVisible ? <th>Priority</th> : null}
              </tr>
            </thead>
            <tbody id="accountTableBody">
              {filteredAccounts.length === 0 && (
                <tr>
                  <td colSpan={priorityVisible ? 8 : 7}>No data available</td>
                </tr>
              )}
                {filteredAccounts.map((account) => (
                  <AccountRow
                    key={account.account_id}
                    account={account}
                    priorityVisible={priorityVisible}
                    onPriorityChange={handlePriorityChange}
                    onNavigate={(accountId) => navigate(`/accounts/${accountId}`)}
                  />
                ))}
            </tbody>
          </table>
        )}
      </div>

      {showModal && (
        <NewAccountModal
          formState={formState}
          referralOptions={referralOptions}
          onChange={handleFormChange}
          onClose={closeModal}
          onSubmit={handleCreateAccount}
          error={modalError}
        />
      )}

      <LogoutFab />
    </SidebarLayout>
  );
}

function AccountRow({ account, priorityVisible, onPriorityChange, onNavigate }) {
  const status = account.account_status || account.computed_status || '—';
  const priority = (account.priority || '').trim().toUpperCase();
  const showPriority = priorityVisible;
  const contractTxt = account.contract || <span className="placeholder">No hires yet</span>;
  const trrTxt = fmtMoney(account.trr) || <span className="placeholder">$0</span>;
  const tsfTxt = fmtMoney(account.tsf) || <span className="placeholder">$0</span>;
  const tsrTxt = fmtMoney(account.tsr) || <span className="placeholder">$0</span>;

  const handleRowClick = (event) => {
    if (event.target.closest('select')) return;
    if (typeof onNavigate === 'function') onNavigate(account.account_id);
  };

  return (
    <tr data-id={account.account_id} onClick={handleRowClick}>
      <td>{account.client_name || '—'}</td>
      <td className="status-td">
        {renderAccountStatusChip(status)}
      </td>
      <td className="sales-lead-cell">{renderSalesLeadCell(account)}</td>
      <td className="muted-cell">{contractTxt}</td>
      <td>{trrTxt}</td>
      <td>{tsfTxt}</td>
      <td>{tsrTxt}</td>
      {showPriority ? (
        <td>
          <select
            className={`priority-select ${priority ? `priority-${priority.toLowerCase()}` : 'priority-empty'}`}
            value={priority}
            onChange={(event) => onPriorityChange(account.account_id, event.target.value)}
            onClick={(event) => event.stopPropagation()}
          >
            <option value=""> </option>
            <option value="A">A</option>
            <option value="B">B</option>
            <option value="C">C</option>
          </select>
        </td>
      ) : null}
    </tr>
  );
}

function renderSalesLeadCell(account) {
  const email = (account.account_manager || '').toLowerCase();
  const name = account.account_manager_name || account.account_manager || 'Unassigned';
  const key = (email || name).toLowerCase();
  const initials = initialsForSalesLead(key);
  const bubble = badgeClassForSalesLead(key);
  const avatar = resolveAvatar(email);
  return (
    <div className="sales-lead" title={name}>
      <span className={`lead-bubble ${bubble}`}>{initials}</span>
      {avatar ? <img className="lead-avatar" src={avatar} alt="" /> : null}
      <span className="lead-name">{name}</span>
      <span className="sr-only">{email || name}</span>
    </div>
  );
}

function NewAccountModal({ formState, referralOptions, onChange, onClose, onSubmit, error }) {
  const isReferral = (formState.where_come_from || '').toLowerCase() === 'referral';
  return (
    <div id="popup" className="popup-overlay" style={{ display: 'flex' }}>
      <div className="popup-content">
        <button className="close-btn" type="button" onClick={onClose} aria-label="Close">
          &times;
        </button>
        <h2 className="popup-title" id="popupTitle">New Account</h2>
        {error ? <p className="candidate-form-error">{error}</p> : null}
        <form className="popup-form two-columns" onSubmit={onSubmit}>
          <div className="popup-field">
            <label>Company Name</label>
            <input type="text" name="name" value={formState.name} onChange={onChange} placeholder="Account name" />
          </div>
          <div className="popup-field full popup-inline">
            <div className="inline-group">
              <div className="field-half">
                <label>Name</label>
                <input type="text" name="contact_name" value={formState.contact_name} onChange={onChange} placeholder="Name" />
              </div>
              <div className="field-half">
                <label>Surname</label>
                <input type="text" name="contact_surname" value={formState.contact_surname} onChange={onChange} placeholder="Surname" />
              </div>
            </div>
          </div>
          <FormInput label="Industry" name="industry" value={formState.industry} onChange={onChange} placeholder="e.g. Fintech, SaaS, E-commerce" />
          <FormSelect label="Size" name="size" value={formState.size} onChange={onChange} options={sizeOptions} />
          <FormSelect label="Timezone" name="timezone" value={formState.timezone} onChange={onChange} options={timezones} />
          <FormInput label="State" name="state" value={formState.state} onChange={onChange} placeholder="State" />
          <FormInput label="Website" name="website" value={formState.website} onChange={onChange} placeholder="e.g. example.com" />
          <FormInput label="Email" name="mail" value={formState.mail} onChange={onChange} placeholder="hello@company.com" type="email" />
          <FormInput label="LinkedIn" name="linkedin" value={formState.linkedin} onChange={onChange} placeholder="LinkedIn URL" />
          <FormSelect label="Lead source" name="where_come_from" value={formState.where_come_from} onChange={onChange} options={leadSources} required />
          {isReferral && (
            <div className="popup-field" id="referralSourceWrapper">
              <label>Referral – Client</label>
              <div className="referral-source-mode" role="group" aria-label="Referral type">
                <label className="inline-radio">
                  <input
                    type="radio"
                    name="referral_mode"
                    value="existing"
                    checked={formState.referral_mode !== 'other'}
                    onChange={onChange}
                  />
                  Existing client
                </label>
                <label className="inline-radio">
                  <input
                    type="radio"
                    name="referral_mode"
                    value="other"
                    checked={formState.referral_mode === 'other'}
                    onChange={onChange}
                  />
                  Other
                </label>
              </div>
              {formState.referral_mode === 'other' ? (
                <input
                  type="text"
                  name="referal_source_other"
                  value={formState.referal_source_other}
                  onChange={onChange}
                  placeholder="Who referred this account?"
                />
              ) : (
                <>
                  <input
                    type="text"
                    name="referal_source"
                    value={formState.referal_source}
                    onChange={onChange}
                    list="referralList"
                    placeholder="Type to search clients..."
                  />
                  <datalist id="referralList">
                    {referralOptions.map((name) => (
                      <option key={name} value={name} />
                    ))}
                  </datalist>
                </>
              )}
            </div>
          )}
          <FormSelect label="Outsource before" name="outsource" value={formState.outsource} onChange={onChange} options={outsourceOptions} />
          <FormSelect label="Pain point" name="pain_points" value={formState.pain_points} onChange={onChange} options={painPoints} />
          <FormSelect label="Position" name="position" value={formState.position} onChange={onChange} options={positions} />
          <FormSelect label="Type" name="type" value={formState.type} onChange={onChange} options={typeOptions} />
          <div className="popup-field full">
            <label>About</label>
            <textarea name="about" value={formState.about} onChange={onChange} placeholder="Write a description..." />
          </div>
          <button type="submit" className="create-btn">Create</button>
        </form>
      </div>
    </div>
  );
}

function FormInput({ label, name, value, onChange, placeholder, type = 'text' }) {
  return (
    <div className="popup-field">
      <label>{label}</label>
      <input type={type} name={name} value={value} onChange={onChange} placeholder={placeholder} />
    </div>
  );
}

function FormSelect({ label, name, value, onChange, options = [], required }) {
  return (
    <div className="popup-field">
      <label>{label}</label>
      <select name={name} value={value} onChange={onChange} required={required}>
        <option value="">Select…</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}

function fmtMoney(value) {
  if (value === null || value === undefined) return null;
  const num = Number(value) || 0;
  if (num === 0) return null;
  return `$${num.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

function renderAccountStatusChip(statusText) {
  const s = (statusText || '').toLowerCase();
  if (s === 'active client') return <span className="chip chip--active-client">Active Client</span>;
  if (s === 'inactive client') return <span className="chip chip--inactive-client">Inactive Client</span>;
  if (s === 'lead in process') return <span className="chip chip--lead-process">Lead in Process</span>;
  if (s === 'lead') return <span className="chip chip--lead">Lead</span>;
  if (s === 'lead lost') return <span className="chip chip--lead-lost">Lead Lost</span>;
  return <span className="chip chip--empty">No data</span>;
}

function initialsForSalesLead(key = '') {
  const s = key.toLowerCase();
  if (s.includes('bahia')) return 'BL';
  if (s.includes('lara')) return 'LR';
  if (s.includes('agustin')) return 'AM';
  if (s.includes('mariano')) return 'MS';
  return '--';
}

function badgeClassForSalesLead(key = '') {
  const s = key.toLowerCase();
  if (s.includes('bahia')) return 'bl';
  if (s.includes('lara')) return 'lr';
  if (s.includes('agustin')) return 'am';
  if (s.includes('mariano')) return 'ms';
  return '';
}

function normalizeAccountPayload(state) {
  const payload = { ...state };
  if (payload.where_come_from) payload.where_come_from = payload.where_come_from.trim();
  const isReferral = (payload.where_come_from || '').toLowerCase() === 'referral';
  const referralMode = (payload.referral_mode || 'existing').toLowerCase();
  if (isReferral) {
    const fromList = (payload.referal_source || '').trim();
    const manualValue = (payload.referal_source_other || '').trim();
    payload.referal_source = (referralMode === 'other' ? manualValue : fromList) || null;
  } else {
    delete payload.referal_source;
  }
  delete payload.referal_source_other;
  delete payload.referral_mode;
  return payload;
}

function initialFormState() {
  return {
    name: '',
    contact_name: '',
    contact_surname: '',
    industry: '',
    size: '',
    timezone: '',
    state: '',
    website: '',
    mail: '',
    linkedin: '',
    where_come_from: '',
    referal_source: '',
    referal_source_other: '',
    referral_mode: 'existing',
    outsource: '',
    pain_points: '',
    position: '',
    type: 'NA',
    about: '',
  };
}

export default CrmPage;
