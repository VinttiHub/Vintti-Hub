import { useEffect, useMemo, useState } from 'react';
import SidebarLayout from '../../components/layout/SidebarLayout.jsx';
import LogoutFab from '../../components/common/LogoutFab.jsx';
import usePageStylesheet from '../../hooks/usePageStylesheet.js';
import { fetchProfile, fetchRecruiterMetrics } from '../../services/recruiterMetricsService.js';

const EXCLUDED_EMAILS = new Set([
  'sol@vintti.com',
  'agustin@vintti.com',
  'bahia@vintti.com',
  'agustina.ferrari@vintti.com',
  'jazmin@vintti.com',
]);

const RESTRICTED_EMAILS = new Set([
  'agustina.barbero@vintti.com',
  'constanza@vintti.com',
  'pilar@vintti.com',
  'pilar.fernandez@vintti.com',
  'agostina@vintti.com',
  'julieta@vintti.com',
]);

const RECRUITER_POWER_ALLOWED = new Set([
  'angie@vintti.com',
  'agostina@vintti.com',
  'agustin@vintti.com',
  'lara@vintti.com',
]);

function RecruiterPowerPage() {
  usePageStylesheet('/assets/css/recruiter-power.css');
  const [metrics, setMetrics] = useState({
    byLead: {},
    orderedLeadEmails: [],
    monthStart: null,
    monthEnd: null,
    rangeStart: null,
    rangeEnd: null,
    currentUserEmail: null,
  });
  const [selectedLead, setSelectedLead] = useState('');
  const [error, setError] = useState('');
  const [rangeError, setRangeError] = useState('');
  const [loading, setLoading] = useState(true);

  const [rangeInputs, setRangeInputs] = useState({ start: '', end: '' });

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      try {
        const profile = await fetchProfile().catch(() => null);
        const currentEmail = profile?.email_vintti?.toLowerCase() || null;
        const data = await fetchRecruiterMetrics();
        const prepared = prepareMetrics(data);
        setMetrics((prev) => ({
          ...prev,
          ...prepared,
          currentUserEmail: currentEmail || data.current_user_email?.toLowerCase() || prev.currentUserEmail,
        }));
        setRangeInputs({
          start: prepared.rangeStart || '',
          end: prepared.rangeEnd || '',
        });
      } catch (err) {
        console.error(err);
        setError('Unable to load recruiter metrics.');
      } finally {
        setLoading(false);
      }
    };
    init();
  }, []);

  useEffect(() => {
    if (!metrics.currentUserEmail) return;
    if (RESTRICTED_EMAILS.has(metrics.currentUserEmail)) {
      setSelectedLead(metrics.currentUserEmail);
    }
  }, [metrics.currentUserEmail, metrics.orderedLeadEmails]);

  const availableLeads = useMemo(() => {
    const emails = metrics.orderedLeadEmails || [];
    if (!metrics.currentUserEmail) {
      return emails;
    }
    if (RESTRICTED_EMAILS.has(metrics.currentUserEmail)) {
      return emails.filter((email) => email === metrics.currentUserEmail);
    }
    return emails;
  }, [metrics.orderedLeadEmails, metrics.currentUserEmail]);

  const selectedMetrics = selectedLead ? metrics.byLead[selectedLead] : null;

  async function applyRange() {
    setRangeError('');
    if (!rangeInputs.start || !rangeInputs.end) {
      setRangeError('Pick both start and end dates.');
      return;
    }
    if (rangeInputs.end < rangeInputs.start) {
      setRangeError('End date must be after start date.');
      return;
    }
    setLoading(true);
    try {
      const data = await fetchRecruiterMetrics({
        start: rangeInputs.start,
        end: rangeInputs.end,
      });
      const prepared = prepareMetrics(data);
      setMetrics((prev) => ({
        ...prev,
        ...prepared,
      }));
    } catch (err) {
      console.error(err);
      setRangeError('Could not load metrics for that range. Try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <SidebarLayout>
      <main className="metrics-page">
        <header className="metrics-header">
          <div className="metrics-title-block">
            <h1 className="metrics-title">Recruiter Performance Dashboard</h1>
            <p className="metrics-subtitle">
              Track wins, losses and conversion rate per HR lead (custom date range + lifetime).
            </p>
          </div>
          {metrics.currentUserEmail && RECRUITER_POWER_ALLOWED.has(metrics.currentUserEmail) && (
            <a
              id="recruiterLabBtn"
              className="recruiter-lab-btn"
              href="https://dashboard.vintti.com/public/dashboard/ca9c80d2-854e-4feb-9a99-5cc6e2519c84?mode=monthly_cr_cw=&recruiter=&recruiter1=&tab=41-wins-%26-losts"
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="lab-emoji">🧪</span>
              <span className="lab-text">Recruiter Lab</span>
            </a>
          )}
        </header>

        <section className="metrics-filters" aria-label="Filters">
          <div className="metrics-filter">
            <label htmlFor="hrLeadSelect" className="filter-label">Recruiter</label>
            <select
              id="hrLeadSelect"
              className="filter-select"
              value={selectedLead}
              onChange={(event) => setSelectedLead(event.target.value)}
            >
              {!selectedLead && <option value="">Select recruiter…</option>}
              {availableLeads
                .filter((email) => !EXCLUDED_EMAILS.has(email))
                .sort((a, b) => getLeadLabel(metrics.byLead, a).localeCompare(getLeadLabel(metrics.byLead, b)))
                .map((email) => (
                  <option key={email} value={email}>
                    {getLeadLabel(metrics.byLead, email)}
                  </option>
                ))}
            </select>
          </div>

          <div className="metrics-filter">
            <span className="filter-label">Date range</span>

            <div className="date-range">
              <label className="date-chip">
                <span className="date-chip-label">From</span>
                <input
                  id="rangeStart"
                  type="date"
                  value={rangeInputs.start}
                  onChange={(event) => setRangeInputs((prev) => ({ ...prev, start: event.target.value }))}
                />
              </label>

              <label className="date-chip">
                <span className="date-chip-label">To</span>
                <input
                  id="rangeEnd"
                  type="date"
                  value={rangeInputs.end}
                  onChange={(event) => setRangeInputs((prev) => ({ ...prev, end: event.target.value }))}
                />
              </label>

              <button id="applyRangeBtn" className="apply-range-btn" type="button" onClick={applyRange}>
                Apply
              </button>
            </div>

            {rangeError ? <div id="rangeError" className="range-error">{rangeError}</div> : null}
          </div>
        </section>

        {error ? <p className="range-error">{error}</p> : null}

        <section className="metrics-cards" aria-live="polite">
          <MetricCard
            label={metrics.rangeStart && metrics.rangeEnd ? 'Closed Win · Selected Range' : 'Closed Win · Last 30 Days'}
            compareLabel={formatTrend(selectedMetrics?.closed_win_month, selectedMetrics?.prev_closed_win_month, true)}
            value={selectedMetrics?.closed_win_month}
            helper="Opportunities marked as Closed Win in the selected window."
          />

          <MetricCard
            label={metrics.rangeStart && metrics.rangeEnd ? 'Closed Lost · Selected Range' : 'Closed Lost · Last 30 Days'}
            compareLabel={formatTrend(selectedMetrics?.closed_lost_month, selectedMetrics?.prev_closed_lost_month, false)}
            value={selectedMetrics?.closed_lost_month}
            helper="Opportunities marked as Closed Lost in the selected window."
          />

          <MetricCard label="Total Closed Win" value={selectedMetrics?.closed_win_total} helper="Lifetime Closed Win opportunities." />
          <MetricCard label="Total Closed Lost" value={selectedMetrics?.closed_lost_total} helper="Lifetime Closed Lost opportunities." />

          <MetricCard
            label={metrics.rangeStart && metrics.rangeEnd ? 'Conversion · Selected Range' : 'Conversion · Last 30 Days'}
            value={formatPercent(selectedMetrics?.conversion_rate_last_20)}
            helper={conversionHelper(selectedMetrics)}
          />

          <MetricCard
            label="Conversion · Lifetime"
            value={formatPercent(selectedMetrics?.conversion_rate_lifetime)}
            helper="Lifetime share of Closed Win over all closed opportunities."
          />

          <MetricCard
            label="Sent vs Interviewed"
            value={formatPercent(selectedMetrics?.avg_sent_vs_interview_ratio)}
            helper={sentVsInterviewHelper(selectedMetrics)}
          />
        </section>

        <section className="meta-footer">
          <p id="periodInfo" className="meta-text">
            {metrics.rangeStart && metrics.rangeEnd
              ? `Selected window: ${formatRange(metrics.rangeStart, metrics.rangeEnd)}`
              : ''}
          </p>
        </section>
      </main>
      <LogoutFab />
    </SidebarLayout>
  );
}

function MetricCard({ label, compareLabel, value, helper }) {
  return (
    <article className="metric-card">
      <div className="metric-header">
        <span className="metric-label">{label}</span>
        {compareLabel ? <span className={`metric-compare ${compareLabel.className}`}>{compareLabel.label}</span> : null}
      </div>
      <div className="metric-value">{value == null ? '–' : value}</div>
      <p className="metric-caption">{helper}</p>
    </article>
  );
}

function prepareMetrics(data) {
  const byLead = {};
  const emails = [];
  (data.metrics || []).forEach((row) => {
    const email = (row.hr_lead_email || row.hr_lead || '').toLowerCase();
    if (!email || EXCLUDED_EMAILS.has(email)) return;
    byLead[email] = row;
    emails.push(email);
  });

  return {
    byLead,
    orderedLeadEmails: emails,
    monthStart: data.month_start,
    monthEnd: data.month_end,
    rangeStart: data.range_start || data.month_start?.slice(0, 10),
    rangeEnd: data.range_end || data.month_end?.slice(0, 10),
  };
}

function getLeadLabel(byLead, email) {
  return byLead[email]?.hr_lead_name || byLead[email]?.hr_lead || email;
}

function formatTrend(current, previous, goodWhenHigher) {
  if (previous == null) return null;
  const diff = current - previous;
  if (diff === 0) return { label: 'same', className: 'neutral' };
  const arrow = diff > 0 ? '↑' : '↓';
  const verb = diff > 0 ? 'up' : 'down';
  const isImprovement = goodWhenHigher ? diff > 0 : diff < 0;
  return { label: `${arrow} ${verb} ${Math.abs(diff)}`, className: isImprovement ? 'up' : 'down' };
}

function formatPercent(value) {
  if (value == null) return '–';
  const pct = value * 100;
  if (pct === 0) return '0%';
  if (pct === 100) return '100%';
  return `${pct.toFixed(1).replace('.0', '')}%`;
}

function formatRange(start, end) {
  const pretty = (val) => {
    const [year, month, day] = val.split('-');
    return `${day}/${month}/${year}`;
  };
  return `${pretty(start)} — ${pretty(end)}`;
}

function conversionHelper(metrics) {
  if (!metrics) return 'No data available.';
  const total = metrics.last_20_count ?? 0;
  const wins = metrics.last_20_win ?? 0;
  if (!total) return 'No closed opportunities in the selected range.';
  return `Selected range: ${wins} Closed Win out of ${total} closed opportunities.`;
}

function sentVsInterviewHelper(metrics) {
  if (!metrics) return 'No opportunities with recruiter interview counts yet.';
  const sample = metrics.sent_vs_interview_sample_count ?? 0;
  const totals = metrics.sent_vs_interview_totals || {};
  const sent = Number(totals.sent ?? 0);
  const interviewed =
    totals.interviewed === null ||
    totals.interviewed === undefined ||
    Number.isNaN(Number(totals.interviewed))
      ? '—'
      : Number(totals.interviewed);
  if (!sample) return 'No opportunities with recruiter interview counts yet.';
  const plural = sample === 1 ? '' : 's';
  return `Avg of ${sample} opp${plural} · ${sent} sent / ${interviewed} interviewed (recruiter logs).`;
}

export default RecruiterPowerPage;
