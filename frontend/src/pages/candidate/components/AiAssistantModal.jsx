import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import {
  fetchCandidateCvs,
  fetchCandidate,
  generateResumeFields,
  updateCandidateScrap,
} from '../../../services/candidateDetailService.js';

function AiAssistantModal({ open, candidateId, candidate, onClose, onResumeReady }) {
  const [linkedinScrap, setLinkedinScrap] = useState(candidate?.linkedin_scrapper || '');
  const [cvScrap, setCvScrap] = useState(candidate?.cv_pdf_scrapper || '');
  const [comments, setComments] = useState('');
  const [loading, setLoading] = useState(false);
  const [loaderPhrase, setLoaderPhrase] = useState('');
  const [cvFiles, setCvFiles] = useState([]);

  useEffect(() => {
    if (!open) {
      setComments('');
      setLoaderPhrase('');
      setLoading(false);
      return;
    }
    setCvFiles([]);
    let cancelled = false;
    (async () => {
      if (!candidateId) return;
      try {
        const files = await fetchCandidateCvs(candidateId);
        if (!cancelled) setCvFiles(Array.isArray(files) ? files : []);
      } catch (err) {
        console.warn('Failed to load CV files', err);
        if (!cancelled) setCvFiles([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, candidateId]);

  const phrases = [
    'Las chicas lindas saben esperar 💅✨',
    'Gracias por tu paciencia, sos la mejor Vinttituta 💖👑',
    'Keep calm and deja que Vinttihub te lo solucione 😌🛠️',
    'Tranquila reina, tu CV está en buenas manos 📄👑',
    'Si esto fuera un casting de modelos, ya estarías contratada 😍',
    'Las Vinttitutas no se apuran, se hacen desear 💁‍♀️💫',
    'Generando algo genial para tu clientito ✨📤💌',
  ];

  useEffect(() => {
    if (!loading) return;
    let idx = 0;
    setLoaderPhrase(phrases[idx]);
    const interval = setInterval(() => {
      idx = (idx + 1) % phrases.length;
      setLoaderPhrase(phrases[idx]);
    }, 3000);
    return () => clearInterval(interval);
  }, [loading]);

  useEffect(() => {
    setLinkedinScrap(candidate?.linkedin_scrapper || candidate?.coresignal_scrapper || '');
    setCvScrap(candidate?.cv_pdf_scrapper || candidate?.affinda_scrapper || '');
  }, [candidate]);

  const hasStoredSources = candidateHasStoredSources(candidate, cvFiles);
  const canGenerate = Boolean(linkedinScrap.trim() || cvScrap.trim() || hasStoredSources);

  async function handleGenerate() {
    if (!candidateId || loading) return;
    if (!canGenerate) {
      alert('Please add LinkedIn or CV info before generating.');
      return;
    }
    setLoading(true);
    try {
      await ensureResume();
      await persistScrapInputs();
      const sources = await resolveSources();
      if (!sources.hasAnySource) {
        alert('Please add LinkedIn or CV info before generating.');
        return;
      }
      await generateResumeFields(candidateId, {
        linkedin_scrapper: sources.linkedin_scrapper,
        cv_pdf_scrapper: sources.cv_pdf_scrapper,
      });
      onResumeReady();
      onClose();
    } catch (err) {
      console.error(err);
      alert('Something went wrong while generating the resume.');
    } finally {
      setLoading(false);
    }
  }

  async function ensureResume() {
    if (window.Resume?.ensure) {
      await window.Resume.ensure();
      return;
    }
    // fallback: touch resume endpoint
    try {
      await fetchCandidate(candidateId);
    } catch {}
  }

  async function persistScrapInputs() {
    const payload = {};
    const linkedTrimmed = linkedinScrap.trim();
    const cvTrimmed = cvScrap.trim();
    if (linkedTrimmed) payload.linkedin_scrapper = linkedTrimmed;
    if (cvTrimmed) payload.cv_pdf_scrapper = cvTrimmed;
    if (Object.keys(payload).length) {
      await updateCandidateScrap(candidateId, payload);
    }
  }

  async function handleScrapBlur(field, value) {
    if (!candidateId) return;
    try {
      await updateCandidateScrap(candidateId, { [field]: value.trim() });
    } catch (err) {
      console.warn(`Failed to save ${field}`, err);
    }
  }

  async function resolveSources() {
    let linkedinScrapper = linkedinScrap.trim();
    let cvScrapper = cvScrap.trim();
    let hasLinkedinUrl = !!(candidate?.linkedin || '').trim();
    let hasCvFile = Array.isArray(cvFiles) && cvFiles.length > 0;
    try {
      if (!linkedinScrapper || !cvScrapper || !hasLinkedinUrl) {
        const data = await fetchCandidate(candidateId);
        if (!linkedinScrapper) linkedinScrapper = data.linkedin_scrapper || data.coresignal_scrapper || '';
        if (!cvScrapper) cvScrapper = data.cv_pdf_scrapper || data.affinda_scrapper || '';
        hasLinkedinUrl = !!(data.linkedin || '').trim();
      }
    } catch {}
    if (!hasCvFile) {
      try {
        const cvList = await fetchCandidateCvs(candidateId);
        hasCvFile = Array.isArray(cvList) && cvList.length > 0;
      } catch {}
    }
    return {
      linkedin_scrapper: linkedinScrapper,
      cv_pdf_scrapper: cvScrapper,
      hasAnySource: !!(linkedinScrapper || cvScrapper || hasLinkedinUrl || hasCvFile),
    };
  }

  if (!open) return null;

  return (
    <div id="ai-popup" className="ai-modal">
      <button id="ai-close" className="modal-close" type="button" aria-label="Close" onClick={onClose}>
        ×
      </button>
      <h2>✨ AI Assistant</h2>
      <label htmlFor="ai-linkedin-scrap">LinkedIn Data</label>
      <div id="ai-linkedin-note">
        {candidate?.linkedin ? (
          <a href={normalizeUrl(candidate.linkedin)} target="_blank" rel="noopener noreferrer">
            Open LinkedIn profile
          </a>
        ) : (
          <span>LinkedIn? VinttiHub covered it. You do you 💅</span>
        )}
      </div>
      <textarea
        id="ai-linkedin-scrap"
        value={linkedinScrap}
        onChange={(event) => setLinkedinScrap(event.target.value)}
        onBlur={(event) => handleScrapBlur('linkedin_scrapper', event.target.value)}
      />
      <label htmlFor="ai-pdf-scrap">PDF Extract</label>
      <div id="ai-pdf-note">
        {cvFiles.length ? (
          <ul style={{ margin: '4px 0 0', paddingLeft: '18px' }}>
            {cvFiles.slice(0, 3).map((file) => (
              <li key={file.key || file.url || file.name}>
                {file?.url ? (
                  <a href={file.url} target="_blank" rel="noopener noreferrer">
                    {file?.name || 'View file'}
                  </a>
                ) : (
                  <span>{file?.name || 'File on record'}</span>
                )}
              </li>
            ))}
            {cvFiles.length > 3 && <li>+{cvFiles.length - 3} more</li>}
          </ul>
        ) : (
          <span>PDF? Already scanned by VinttiHub 🪄</span>
        )}
      </div>
      <textarea
        id="ai-pdf-scrap"
        value={cvScrap}
        onChange={(event) => setCvScrap(event.target.value)}
        onBlur={(event) => handleScrapBlur('cv_pdf_scrapper', event.target.value)}
      />
      <label>Do you want me to take something into account?</label>
      <textarea id="ai-comments" value={comments} onChange={(event) => setComments(event.target.value)} />
      <button type="button" onClick={handleGenerate} disabled={loading || !canGenerate}>
        {loading ? 'Working...' : "✨ Let's Go!"}
      </button>
      {!canGenerate && (
        <p className="reminder" style={{ marginTop: '8px' }}>
          Please add LinkedIn or CV info before generating.
        </p>
      )}
      {loading && (
        <div id="resume-loader">
          <p id="resume-loader-phrase">{loaderPhrase}</p>
        </div>
      )}
    </div>
  );
}

AiAssistantModal.propTypes = {
  open: PropTypes.bool.isRequired,
  candidateId: PropTypes.number.isRequired,
  candidate: PropTypes.object,
  onClose: PropTypes.func.isRequired,
  onResumeReady: PropTypes.func.isRequired,
};

export default AiAssistantModal;

function normalizeUrl(url) {
  if (!url) return '';
  let next = String(url).trim();
  if (!next) return '';
  if (!/^https?:\/\//i.test(next)) {
    next = `https://${next.replace(/^\/+/, '')}`;
  }
  return next;
}

function candidateHasStoredSources(candidate, cvFiles = []) {
  const trim = (value) => (value || '').toString().trim();
  return Boolean(
    trim(candidate?.linkedin_scrapper) ||
      trim(candidate?.cv_pdf_scrapper) ||
      trim(candidate?.affinda_scrapper) ||
      trim(candidate?.coresignal_scrapper) ||
      trim(candidate?.linkedin) ||
      (Array.isArray(cvFiles) && cvFiles.length > 0),
  );
}
