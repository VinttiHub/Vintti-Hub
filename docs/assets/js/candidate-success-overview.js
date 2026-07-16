// ============================================================================
// Candidate Success Overview
// Reads the free-form "candidate_succes" notes for a candidate and renders them
// as a clean chronological timeline (mirrors the Client overview experience).
// ============================================================================

const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

const params = new URLSearchParams(window.location.search);
const candidateId = params.get('id');

// Where to send the user back to.
const backHref = candidateId
  ? `candidate-details.html?id=${encodeURIComponent(candidateId)}`
  : 'candidates.html';

document.addEventListener('DOMContentLoaded', () => {
  const backTop = document.getElementById('breadcrumbBack');
  const backBottom = document.getElementById('footerBack');
  if (backTop) backTop.href = backHref;
  if (backBottom) backBottom.href = backHref;

  if (!candidateId) {
    renderEmpty();
    setName('Missing candidate');
    return;
  }

  loadCandidate();
});

async function loadCandidate() {
  try {
    const res = await fetch(`${API_BASE}/candidates/${candidateId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    setName((data.name || '').trim() || `Candidate #${candidateId}`);

    const entries = parseEntries(data.candidate_succes || '');
    renderTimeline(entries);
    renderHighlights(entries);
  } catch (err) {
    console.error('❌ Error loading candidate success overview:', err);
    setName(`Candidate #${candidateId}`);
    renderEmpty();
  }
}

function setName(name) {
  const el = document.getElementById('candidateName');
  if (el) el.textContent = name;
}

// ---------------------------------------------------------------------------
// Parsing: turn contenteditable HTML into an array of { title, lines } entries.
// Entries are separated by blank lines in the original note.
// ---------------------------------------------------------------------------
function parseEntries(html) {
  if (!html || !html.trim()) return [];

  // Normalize block boundaries into newlines and list items into bullets.
  const normalized = html
    .replace(/<\s*br\s*\/?>/gi, '\n')
    .replace(/<li[^>]*>/gi, '\n• ')
    .replace(/<\/(div|p|li|h[1-6]|ul|ol)\s*>/gi, '\n');

  const holder = document.createElement('div');
  holder.innerHTML = normalized;
  const text = (holder.textContent || '')
    .replace(/ /g, ' ') // non-breaking spaces
    .replace(/\r/g, '');

  // Split into trimmed lines, remembering which are blank (entry separators).
  const rawLines = text.split('\n').map((l) => l.trim());

  const entries = [];
  let current = null;

  for (const line of rawLines) {
    if (line === '') {
      if (current) {
        entries.push(current);
        current = null;
      }
      continue;
    }
    if (!current) {
      current = { title: line, lines: [] };
    } else {
      current.lines.push(line.replace(/^•\s*/, ''));
    }
  }
  if (current) entries.push(current);

  return entries;
}

// ---------------------------------------------------------------------------
// Chip: try to surface a date / weekday token from the entry title.
// Handles numeric dates (10/11, 20/01/2026) and written dates in Spanish /
// English (e.g. "20 de enero", "enero 20", "Jan 20", "20 January 2026").
// ---------------------------------------------------------------------------
// Month name (ES / EN, full + common abbreviations) → month number.
const MONTH_TO_NUM = {
  enero: 1, ene: 1, january: 1, jan: 1,
  febrero: 2, feb: 2, february: 2,
  marzo: 3, mar: 3, march: 3,
  abril: 4, abr: 4, april: 4, apr: 4,
  mayo: 5, may: 5,
  junio: 6, jun: 6, june: 6,
  julio: 7, jul: 7, july: 7,
  agosto: 8, ago: 8, august: 8, aug: 8,
  septiembre: 9, setiembre: 9, sep: 9, set: 9, september: 9,
  octubre: 10, oct: 10, october: 10,
  noviembre: 11, nov: 11, november: 11,
  diciembre: 12, dic: 12, december: 12, dec: 12,
};
const MONTHS = `(${Object.keys(MONTH_TO_NUM).join('|')})`;

// Every detected date is normalized to a single DD/MM format so the chips
// look consistent regardless of how the note was originally written.
function pad2(n) {
  return String(n).padStart(2, '0');
}

// Returns { d, m } (day/month numbers) for the first date found, else null.
function findDateParts(title) {
  // Numeric: 10/11 or 20/01/2026 (also accepts - or . as separators)
  const numeric = title.match(/\b(\d{1,2})[\/.-](\d{1,2})(?:[\/.-]\d{2,4})?\b/);
  if (numeric) return { d: +numeric[1], m: +numeric[2] };

  // Written "day (de) month": 20 de enero / 20 enero / 20 January
  const dayMonth = title.match(new RegExp(`\\b(\\d{1,2})\\s+(?:de\\s+)?${MONTHS}\\b`, 'i'));
  if (dayMonth) return { d: +dayMonth[1], m: MONTH_TO_NUM[dayMonth[2].toLowerCase()] };

  // Written "month day": enero 20 / January 20
  const monthDay = title.match(new RegExp(`\\b${MONTHS}\\s+(\\d{1,2})\\b`, 'i'));
  if (monthDay) return { d: +monthDay[2], m: MONTH_TO_NUM[monthDay[1].toLowerCase()] };

  return null;
}

// Spanish weekday labels indexed by Date.getDay() (0 = Sunday).
const SP_DAYS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];

// Written weekday (ES / EN, accent-insensitive) → Date.getDay() number.
const WD_TO_NUM = {
  domingo: 0, sunday: 0,
  lunes: 1, monday: 1,
  martes: 2, tuesday: 2,
  miercoles: 3, wednesday: 3,
  jueves: 4, thursday: 4,
  viernes: 5, friday: 5,
  sabado: 6, saturday: 6,
};

function stripAccents(s) {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

// Returns the Date.getDay() number for a weekday word in the title, else null.
function findWeekdayNum(title) {
  const m = title.match(
    /\b(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i
  );
  if (!m) return null;
  const num = WD_TO_NUM[stripAccents(m[1])];
  return num === undefined ? null : num;
}

// Pick the most recent year (searching around today) whose (d/m) date falls on
// the written weekday — this anchors the whole timeline to a real calendar year.
function resolveAnchorYear(d, m, weekdayNum) {
  const thisYear = new Date().getFullYear();
  for (let y = thisYear + 1; y >= thisYear - 6; y--) {
    if (new Date(y, m - 1, d).getDay() === weekdayNum) return y;
  }
  return thisYear;
}

// Build one chip label per entry, filling in the weekday from the date so every
// dated entry shows the SAME "Weekday · DD/MM" format, regardless of whether the
// author wrote the weekday out. Order-independent: years are chosen by proximity
// to the anchor date, so a Nov→Jan rollover resolves correctly.
function buildChips(entries) {
  const parts = entries.map((e) => ({
    dm: findDateParts(e.title),
    wdNum: findWeekdayNum(e.title),
  }));

  // Anchor: first entry that has both a written weekday and a date.
  let anchor = null;
  for (const p of parts) {
    if (p.dm && p.wdNum !== null) {
      const y = resolveAnchorYear(p.dm.d, p.dm.m, p.wdNum);
      anchor = { time: new Date(y, p.dm.m - 1, p.dm.d).getTime(), year: y };
      break;
    }
  }

  const yearFor = (dm) => {
    if (!anchor) return null;
    let best = anchor.year;
    let bestDiff = Infinity;
    for (const y of [anchor.year - 1, anchor.year, anchor.year + 1]) {
      const diff = Math.abs(new Date(y, dm.m - 1, dm.d).getTime() - anchor.time);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = y;
      }
    }
    return best;
  };

  return parts.map((p, i) => {
    if (p.dm) {
      const date = `${pad2(p.dm.d)}/${pad2(p.dm.m)}`;
      const year = yearFor(p.dm);
      if (year !== null) {
        const dow = new Date(year, p.dm.m - 1, p.dm.d).getDay();
        return `${SP_DAYS[dow]} · ${date}`;
      }
      // No anchor available: keep any written weekday, else date only.
      return p.wdNum !== null ? `${SP_DAYS[p.wdNum]} · ${date}` : date;
    }
    if (p.wdNum !== null) return SP_DAYS[p.wdNum];
    return `Update ${i + 1}`;
  });
}

// The chip already shows the date, so strip a leading "weekday + date" prefix
// from the title and keep only what follows it (e.g. "Lunes 10/11 - primer día"
// → "primer día"). Only strips when the date sits at the start, to avoid
// removing real content.
const LEADING_DATE = new RegExp(
  '^\\s*' +
    '(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\\b[\\s,·:.\\u2013\\u2014-]*)?' +
    '(?:' +
    '\\d{1,2}[\\/.-]\\d{1,2}(?:[\\/.-]\\d{2,4})?' +
    `|\\d{1,2}\\s+(?:de\\s+)?${MONTHS}` +
    `|${MONTHS}\\s+\\d{1,2}` +
    ')' +
    '[\\s,·:.\\u2013\\u2014-]*',
  'i'
);

function stripLeadingDate(title) {
  return title.replace(LEADING_DATE, '').trim();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
function renderTimeline(entries) {
  const timeline = document.getElementById('timeline');
  const empty = document.getElementById('emptyState');
  if (!timeline) return;

  if (!entries.length) {
    timeline.innerHTML = '';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  const chips = buildChips(entries);
  timeline.innerHTML = entries.map((entry, i) => renderEntry(entry, chips[i])).join('');
}

function renderEntry(entry, chipLabel) {
  const chip = escapeHtml(chipLabel);
  const cleanTitle = stripLeadingDate(entry.title);

  const titleHtml = cleanTitle ? `<h3 class="entry-title">${escapeHtml(cleanTitle)}</h3>` : '';

  let bodyHtml = '';
  if (entry.lines.length) {
    bodyHtml = `<ul class="entry-body">${entry.lines
      .map((l) => `<li>${escapeHtml(l)}</li>`)
      .join('')}</ul>`;
  }

  return `
    <article class="entry-card">
      <div class="entry-head">
        <span class="entry-chip">${chip}</span>
      </div>
      ${titleHtml}
      ${bodyHtml}
    </article>
  `;
}

function renderHighlights(entries) {
  const count = document.getElementById('highlightCount');
  const latest = document.getElementById('highlightLatest');

  if (count) count.textContent = entries.length ? String(entries.length) : '0';

  if (latest) {
    if (entries.length) {
      const chips = buildChips(entries);
      latest.textContent = chips[chips.length - 1];
    } else {
      latest.textContent = '—';
    }
  }
}

function renderEmpty() {
  const timeline = document.getElementById('timeline');
  const empty = document.getElementById('emptyState');
  if (timeline) timeline.innerHTML = '';
  if (empty) empty.style.display = '';
  const count = document.getElementById('highlightCount');
  const latest = document.getElementById('highlightLatest');
  if (count) count.textContent = '0';
  if (latest) latest.textContent = '—';
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
