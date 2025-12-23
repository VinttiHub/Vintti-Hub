import { useEffect, useMemo, useState } from 'react';
import SidebarLayout from '../../components/layout/SidebarLayout.jsx';
import LogoutFab from '../../components/common/LogoutFab.jsx';
import usePageStylesheet from '../../hooks/usePageStylesheet.js';
import {
  coresignalCollect,
  coresignalSearch,
  parseCandidateQuery,
  searchInternalCandidates,
} from '../../services/candidateSearchService.js';

const EXPERIENCE_OPTIONS = Array.from({ length: 11 }, (_, i) => i);
const CORESIGNAL_LOCATIONS = [
  { tag: '🇲🇽 Mexico', location: 'Mexico' },
  { tag: '🇦🇷 Argentina', location: 'Argentina' },
  { tag: '🇨🇴 Colombia', location: 'Colombia' },
  { tag: '🌎 LATAM', location: null },
];

function CandidateSearchPage() {
  usePageStylesheet('/assets/css/candidate-search.css');

  const [query, setQuery] = useState('');
  const [chips, setChips] = useState([]);
  const [allVinttiResults, setAllVinttiResults] = useState([]);
  const [experienceFilter, setExperienceFilter] = useState('');
  const [csResults, setCsResults] = useState([]);
  const [csLoading, setCsLoading] = useState(false);
  const [csError, setCsError] = useState('');
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');

  const filteredVinttiResults = useMemo(() => filterVinttiResults(allVinttiResults, experienceFilter), [allVinttiResults, experienceFilter]);

  async function handleSearch() {
    if (!query.trim()) return;
    setSearching(true);
    setError('');
    setCsError('');
    try {
      const parsed = await parseCandidateQuery(query.trim());
      setChips(buildChips(parsed));
      if (Number.isFinite(parsed.years_experience)) {
        setExperienceFilter(String(parsed.years_experience));
      } else {
        setExperienceFilter('');
      }

      const tools = (parsed.tools || []).map((tool) => String(tool).toLowerCase().trim()).filter(Boolean);
      const location = (parsed.location || '').trim();
      const title = (parsed.title || '').trim();

      const vinttiData = await searchInternalCandidates({ tools, location, title });
      setAllVinttiResults(vinttiData.items || []);

      setCsLoading(true);
      const aggregatedCs = await coresignalMultiSearch(parsed);
      setCsResults(aggregatedCs);
      if (!aggregatedCs.length) {
        setCsError('Sin resultados en Coresignal para este criterio.');
      }
    } catch (err) {
      console.error(err);
      setError(err.message || 'No pudimos ejecutar la búsqueda.');
      setAllVinttiResults([]);
      setCsResults([]);
    } finally {
      setSearching(false);
      setCsLoading(false);
    }
  }

  async function coresignalMultiSearch(parsed) {
    const seen = new Set();
    const aggregated = [];

    for (const step of CORESIGNAL_LOCATIONS) {
      try {
        const resp = await coresignalSearch({ parsed, page: 1, locationOverride: step.location });
        const items = Array.isArray(resp?.data) ? resp.data : resp?.data?.items || [];
        items.forEach((item) => {
          const id = item.employee_id || item.id || item.public_identifier || item.publicIdentifier || item.canonical_shorthand_name;
          if (!id || seen.has(id)) return;
          seen.add(id);
          aggregated.push({
            ...item,
            sourceTag: step.tag,
          });
        });
      } catch (error) {
        console.warn(`Coresignal search failed for ${step.tag}`, error);
      }
    }

    return aggregated;
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter') {
      handleSearch();
    }
  }

  return (
    <SidebarLayout>
      <div className="candidate-search-page">
        <header className="hero">
          <h1 className="title">🔎 Vintti Candidate Finder</h1>
          <div className="search-wrap">
            <input
              id="nl-query"
              className="search-input"
              type="text"
              placeholder="Describe al candidato ideal…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleKeyDown}
            />
            <button id="search-btn" className="search-btn" type="button" onClick={handleSearch} disabled={searching}>
              {searching ? 'Buscando…' : 'Buscar'}
            </button>
          </div>
          {!!chips.length && (
            <div id="chips" className="chips">
              {chips.map((chip) => (
                <span key={chip} className="chip">{chip}</span>
              ))}
            </div>
          )}
          {error ? <p className="empty">{error}</p> : null}
        </header>

        <main className="grid">
          <section className="col">
            <h2 className="col-title">🌱 Vintti Talent</h2>
            <div className="filters-row">
              <label htmlFor="exp-filter" className="filter-label">
                Years of experience
              </label>
              <select
                id="exp-filter"
                className="filter-select"
                value={experienceFilter}
                onChange={(event) => setExperienceFilter(event.target.value)}
              >
                <option value="">Any experience</option>
                {EXPERIENCE_OPTIONS.map((value) => (
                  <option key={value} value={value}>{value}+ years</option>
                ))}
              </select>
            </div>

            <div id="vintti-results" className="cards">
              {filteredVinttiResults.map((candidate) => (
                <a
                  key={candidate.candidate_id}
                  className="card"
                  href={`https://vinttihub.vintti.com/candidate-details.html?id=${encodeURIComponent(candidate.candidate_id)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <div className="card-body">
                    <div className="card-name">{candidate.name || '(sin nombre)'}</div>
                    <div className="card-meta">
                      {(candidate.country || '—')}
                      {candidate.english_level ? ` · 🇬🇧 ${candidate.english_level}` : ''}
                    </div>
                    <div className="card-notes">
                      {candidate.salary_range ? `Desired salary: ${candidate.salary_range}` : ''}
                    </div>
                  </div>
                </a>
              ))}
            </div>
            {!filteredVinttiResults.length && (
              <div id="vintti-empty" className="empty">No encontramos candidatos con esas herramientas (aún).</div>
            )}
          </section>

          <section className="col">
            <h2 className="col-title">🛰️ Linkedin</h2>
            <div id="coresignal-wrap">
              {csLoading ? <p>Consultando Coresignal…</p> : null}
              {!csLoading && !csResults.length && csError && <div id="cs-empty" className="empty">{csError}</div>}
              <div id="cs-results" className="cards">
                {csResults.map((profile) => (
                  <CoresignalCard key={profile.employee_id || profile.id || profile.public_identifier} profile={profile} />
                ))}
              </div>
            </div>
          </section>
        </main>
      </div>
      <LogoutFab />
    </SidebarLayout>
  );
}

function buildChips(parsed) {
  const labels = [];
  if (parsed.title) labels.push(`💼 ${parsed.title}`);
  (parsed.tools || []).forEach((tool) => labels.push(`🧰 ${tool}`));
  if (Number.isFinite(parsed.years_experience)) labels.push(`⏳ ${parsed.years_experience} yrs`);
  if (parsed.location) labels.push(`📍 ${parsed.location}`);
  return labels;
}

function filterVinttiResults(results, expFilter) {
  if (!Array.isArray(results) || !results.length) return [];
  let filtered = [...results];
  if (expFilter !== '') {
    const minYears = parseInt(expFilter, 10);
    if (!Number.isNaN(minYears)) {
      filtered = filtered.filter((row) => {
        const years = typeof row.years_experience === 'number' ? row.years_experience : 0;
        return years >= minYears;
      });
    }
  }

  filtered.sort((a, b) => {
    const countryOrder = countryRank(a.country) - countryRank(b.country);
    if (countryOrder !== 0) return countryOrder;
    const salaryA = parseSalary(a.salary_range);
    const salaryB = parseSalary(b.salary_range);
    if (salaryA !== salaryB) return salaryA - salaryB;
    return (a.name || '').localeCompare(b.name || '');
  });
  return filtered;
}

function countryRank(country) {
  const c = (country || '').toLowerCase();
  if (c.includes('mexico')) return 1;
  if (c.includes('argentina')) return 2;
  if (c.includes('colombia')) return 3;
  return 4;
}

function parseSalary(value) {
  if (!value) return Infinity;
  const match = String(value).match(/\d+/);
  if (!match) return Infinity;
  const salary = parseInt(match[0], 10);
  return Number.isNaN(salary) ? Infinity : salary;
}

function CoresignalCard({ profile }) {
  const name = profile.name || profile.full_name || profile.public_identifier || 'Profile';
  const location = profile.location || profile.country || '—';
  const headline = profile.headline || '';
  const linkedInUrl = profile.linkedin_url || profile.linkedin || profile.linkedinUrl;
  const publicId = profile.public_identifier || profile.publicIdentifier;
  const employeeId = profile.employee_id || profile.id || profile.canonical_shorthand_name;

  const href = buildLinkedinUrl({ linkedInUrl, publicId });

  const handleClick = async (event) => {
    if (href) return;
    event.preventDefault();
    if (!employeeId) return;
    try {
      const detail = await coresignalCollect(employeeId);
      const finalUrl = buildLinkedinUrl({
        linkedInUrl: detail.linkedin_url || detail.linkedin || detail.linkedinUrl || detail.profile_url,
        publicId: detail.public_identifier || detail.publicIdentifier,
      });
      if (finalUrl) {
        window.open(finalUrl, '_blank', 'noopener');
      }
    } catch (error) {
      console.error('Failed to collect profile', error);
    }
  };

  return (
    <a
      className="card cs-card"
      href={href || '#'}
      target={href ? '_blank' : undefined}
      rel={href ? 'noopener noreferrer' : undefined}
      onClick={handleClick}
    >
      <div className="card-body">
        <div className="card-name cs-card-name">{name}</div>
        <div className="card-meta cs-card-meta">{location}</div>
        <div className="card-notes cs-card-notes">{headline || '—'}</div>
      </div>
    </a>
  );
}

function buildLinkedinUrl({ linkedInUrl, publicId }) {
  if (linkedInUrl && /^https?:\/\//i.test(linkedInUrl)) return linkedInUrl;
  if (publicId) return `https://www.linkedin.com/in/${encodeURIComponent(publicId)}`;
  return null;
}

export default CandidateSearchPage;
