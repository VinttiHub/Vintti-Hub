import { useEffect, useMemo, useState } from 'react';
import SidebarLayout from '../../components/layout/SidebarLayout.jsx';
import LogoutFab from '../../components/common/LogoutFab.jsx';
import usePageStylesheet from '../../hooks/usePageStylesheet.js';
import { fetchOpportunities } from '../../services/opportunitiesService.js';
import { fetchAccountsLight } from '../../services/crmService.js';

const STAGES = ['Negotiating', 'Interviewing', 'Sourcing', 'Deep Dive', 'NDA Sent'];
const HR_LEADS = [
  { email: 'pilar@vintti.com', label: 'Pilar' },
  { email: 'pilar.fernandez@vintti.com', label: 'Pilar Fernandez' },
  { email: 'agostina@vintti.com', label: 'Agostina' },
  { email: 'jazmin@vintti.com', label: 'Jazmín' },
  { email: 'agustina.barbero@vintti.com', label: 'Agustina Barbero' },
  { email: 'constanza@vintti.com', label: 'Constanza' },
  { email: 'julieta@vintti.com', label: 'Julieta Godoy' },
];

function OpportunitiesSummaryPage() {
  usePageStylesheet('/assets/css/opportunities-summary.css');
  const [counts, setCounts] = useState(buildInitialCounts());
  const [oppsCache, setOppsCache] = useState([]);
  const [accountsMap, setAccountsMap] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [drilldown, setDrilldown] = useState({ open: false, hrEmail: '', stage: '', opps: [] });
  const [selectedCell, setSelectedCell] = useState('');
  const [lastUpdated, setLastUpdated] = useState(new Date());

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const [opportunities, accounts] = await Promise.all([
          fetchOpportunities(),
          fetchAccountsLight(),
        ]);
        setOppsCache(opportunities || []);
        setAccountsMap(buildAccountsMap(accounts || []));
        setCounts(buildSummaryCounts(opportunities || []));
        setLastUpdated(new Date());
      } catch (err) {
        console.error(err);
        setError('Unable to load opportunities summary. Please try again later.');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const columnTotals = useMemo(() => {
    const totals = STAGES.map(() => 0);
    HR_LEADS.forEach(({ email }) => {
      STAGES.forEach((stage, idx) => {
        totals[idx] += counts[email]?.[stage] || 0;
      });
    });
    return totals;
  }, [counts]);

  const grandTotal = useMemo(() => columnTotals.reduce((sum, value) => sum + value, 0), [columnTotals]);

  function openDrilldown(email, stage) {
    if (!email || !stage) return;
    const normalized = normalizeEmail(email);
    const opps = (oppsCache || []).filter(
      (opp) =>
        normalizeEmail(opp.opp_hr_lead) === normalized &&
        (opp.opp_stage || '').trim() === stage,
    );
    setSelectedCell(`${normalized}-${stage}`);
    setDrilldown({
      open: true,
      hrEmail: normalized,
      stage,
      opps,
    });
  }

  function closeDrilldown() {
    setDrilldown({ open: false, hrEmail: '', stage: '', opps: [] });
    setSelectedCell('');
  }

  function accountNameFor(opp) {
    if (opp?.client_name) return opp.client_name;
    const id = opp?.account_id;
    if (id && accountsMap[id]) return accountsMap[id];
    return '—';
  }

  function handleOpportunityClick(opp) {
    const id = opp?.opportunity_id ?? opp?.opp_id ?? opp?.id;
    if (!id) return;
    window.open(`opportunity-detail.html?id=${encodeURIComponent(id)}`, '_blank', 'noopener,noreferrer');
  }

  const formattedUpdatedAt = useMemo(() => {
    const date = lastUpdated;
    return `${date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })} at ${date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}`;
  }, [lastUpdated]);

  return (
    <SidebarLayout>
      <div className="summary-container">
        <button className="go-back-button" type="button" onClick={() => window.history.back()}>
          ← Go Back
        </button>
        <header className="summary-header">
          <h1>Opportunities Summary</h1>
          <p>This dashboard shows the current distribution of opportunities by HR lead and stage.</p>
        </header>
        {error ? <p className="empty">{error}</p> : null}
        <div className="opportunity-summary-table">
          {loading ? (
            <p>Loading summary…</p>
          ) : (
            <table id="summaryTable">
              <thead>
                <tr>
                  <th>HR Lead</th>
                  {STAGES.map((stage) => (
                    <th key={stage} className={`stage-title stage-title-${slugify(stage)}`}>
                      <span className="stage-emoji" aria-hidden="true">{stageEmoji(stage)}</span>
                      <span className="stage-label">{stage}</span>
                    </th>
                  ))}
                  <th className="total-title">Total</th>
                </tr>
              </thead>
              <tbody>
                {HR_LEADS.map(({ email, label }) => {
                  const rowCounts = counts[email] || {};
                  const rowTotal = STAGES.reduce((sum, stage) => sum + (rowCounts[stage] || 0), 0);
                  return (
                    <tr key={email} data-email={email}>
                      <td>{label}</td>
                      {STAGES.map((stage) => {
                        const cellKey = `${email}-${stage}`;
                        const value = rowCounts[stage] || 0;
                        const isSelected = selectedCell === cellKey;
                        return (
                          <td
                            key={stage}
                            className={isSelected ? 'selected-cell' : undefined}
                            onClick={() => openDrilldown(email, stage)}
                          >
                            {value}
                          </td>
                        );
                      })}
                      <td className="total-cell">{rowTotal}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="totals-row">
                  <th className="totals-title">Total</th>
                  {columnTotals.map((value, idx) => (
                    <th key={STAGES[idx]} className={`total-col total-col-${idx + 1}`}>{value}</th>
                  ))}
                  <th className="total-cell grand-total">{grandTotal}</th>
                </tr>
              </tfoot>
            </table>
          )}
        </div>

        <div id="lastUpdated" className="last-updated">
          Last updated: {formattedUpdatedAt} — refresh to get the latest numbers.
        </div>

        {drilldown.open && (
          <section id="drilldownWrapper" className="drilldown">
            <header className="drilldown-header">
              <div>
                <h3 id="drilldownTitle">
                  Opportunities — <strong>{displayNameFor(drilldown.hrEmail)}</strong> · {stageBadge(drilldown.stage)}
                </h3>
                <p id="drilldownSubtitle" className="drilldown-sub">
                  {drilldown.opps.length} related
                </p>
              </div>
              <button id="drilldownClose" className="btn-clear" type="button" aria-label="Close" onClick={closeDrilldown}>
                ✕
              </button>
            </header>

            <div className="drilldown-table-wrapper">
              {drilldown.opps.length === 0 ? (
                <div id="drilldownEmpty" className="dd-empty">No related opportunities</div>
              ) : (
                <table id="drilldownTable" className="dd-table">
                  <thead>
                    <tr>
                      <th style={{ width: '60%' }}>🎯 Position</th>
                      <th style={{ width: '40%' }}>🏢 Account</th>
                    </tr>
                  </thead>
                  <tbody>
                    {drilldown.opps
                      .sort((a, b) => accountNameFor(a).localeCompare(accountNameFor(b)))
                      .map((opp) => (
                        <tr key={opp.opportunity_id} className="dd-row" onClick={() => handleOpportunityClick(opp)}>
                          <td className="dd-position">
                            <span className="dd-title">{opp.opp_position_name || '—'}</span>
                          </td>
                          <td className="dd-account">
                            <span>{accountNameFor(opp)}</span>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        )}
      </div>
      <LogoutFab />
    </SidebarLayout>
  );
}

function buildInitialCounts() {
  const base = {};
  HR_LEADS.forEach(({ email }) => {
    base[email] = {};
    STAGES.forEach((stage) => {
      base[email][stage] = 0;
    });
  });
  return base;
}

function buildSummaryCounts(opportunities) {
  const counts = buildInitialCounts();
  opportunities.forEach((opp) => {
    const email = normalizeEmail(opp.opp_hr_lead);
    const stage = (opp.opp_stage || '').trim();
    if (email && counts[email] && STAGES.includes(stage)) {
      counts[email][stage] += 1;
    }
  });
  return counts;
}

function normalizeEmail(email) {
  return (email || '').toLowerCase().trim();
}

function stageEmoji(stage) {
  return {
    Negotiating: '🤝',
    Interviewing: '🎤',
    Sourcing: '🧭',
    'Deep Dive': '🔎',
    'NDA Sent': '📝',
  }[stage] || '';
}

function stageBadge(stage) {
  const emoji = stageEmoji(stage);
  return `${emoji} ${stage}`;
}

function slugify(value) {
  return String(value).toLowerCase().replace(/[^a-z]+/g, '-').replace(/(^-+|-+$)/g, '');
}

function displayNameFor(email) {
  const entry = HR_LEADS.find((lead) => normalizeEmail(lead.email) === normalizeEmail(email));
  return entry?.label || email;
}

function buildAccountsMap(accounts) {
  const map = {};
  (accounts || []).forEach((acc) => {
    if (acc?.account_id) {
      map[acc.account_id] = acc.client_name || acc.account_name || '—';
    }
  });
  return map;
}

export default OpportunitiesSummaryPage;
