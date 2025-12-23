import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { updateCandidate } from '../../../services/candidateDetailService.js';

function AiAssistantModal({ open, candidateId, onClose, onResumeReady }) {
  const [linkedinScrap, setLinkedinScrap] = useState('');
  const [cvScrap, setCvScrap] = useState('');
  const [comments, setComments] = useState('');
  const [loading, setLoading] = useState(false);
  const [loaderPhrase, setLoaderPhrase] = useState('');

  useEffect(() => {
    if (!open) {
      setComments('');
      setLoaderPhrase('');
      setLoading(false);
    }
  }, [open]);

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

  async function handleGenerate() {
    if (!candidateId) return;
    setLoading(true);
    try {
      await ensureResume();
      const sources = await resolveSources();
      if (!sources.hasAnySource) {
        alert('Please add LinkedIn or CV info before generating.');
        return;
      }
      await fetch(`${import.meta.env.VITE_API_BASE || 'https://7m6mw95m8y.us-east-2.awsapprunner.com'}/generate_resume_fields`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidate_id: candidateId,
          linkedin_scrapper: sources.linkedin_scrapper,
          cv_pdf_scrapper: sources.cv_pdf_scrapper,
        }),
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
    window.Resume?.ensure?.();
  }

  async function resolveSources() {
    let linkedinScrapper = linkedinScrap.trim();
    let cvScrapper = cvScrap.trim();
    let hasLinkedinUrl = false;
    let hasCvFile = false;
    const response = await fetch(`${import.meta.env.VITE_API_BASE || 'https://7m6mw95m8y.us-east-2.awsapprunner.com'}/candidates/${candidateId}`);
    if (response.ok) {
      const data = await response.json();
      if (!linkedinScrapper) linkedinScrapper = data.linkedin_scrapper || data.coresignal_scrapper || '';
      if (!cvScrapper) cvScrapper = data.cv_pdf_scrapper || data.affinda_scrapper || '';
      hasLinkedinUrl = !!(data.linkedin || '').trim();
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
      <label>LinkedIn Data</label>
      <textarea value={linkedinScrap} onChange={(event) => setLinkedinScrap(event.target.value)} />
      <label>PDF Extract</label>
      <textarea value={cvScrap} onChange={(event) => setCvScrap(event.target.value)} />
      <label>Do you want me to take something into account?</label>
      <textarea id="ai-comments" value={comments} onChange={(event) => setComments(event.target.value)} />
      <button type="button" onClick={handleGenerate} disabled={loading}>
        {loading ? 'Working…' : "✨ Let's Go!"}
      </button>
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
  onClose: PropTypes.func.isRequired,
  onResumeReady: PropTypes.func.isRequired,
};

export default AiAssistantModal;
