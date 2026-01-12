import { useCallback, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import StarPopup from './StarPopup.jsx';
import {
  improveAbout,
  improveEducation,
  improveTools,
  improveWorkExperience,
  fetchResumeRecord,
  fetchCandidateCvs,
  fetchCandidate,
} from '../../../services/candidateDetailService.js';
import downloadResumePdf from '../../../utils/resumePdf.js';

const STAR_SECTIONS = [
  { id: 'about', label: 'About', emoji: '🌟' },
  { id: 'education', label: 'Education', emoji: '🎓' },
  { id: 'work', label: 'Work Experience', emoji: '💼' },
  { id: 'tools', label: 'Tools', emoji: '🧰' },
];

const STAR_DESCRIPTION = "Remember: I already have this candidate's info from LinkedIn and the PDF.";

const STAR_CONFIG = {
  about: {
    title: 'About Prompt',
    description: STAR_DESCRIPTION,
    placeholder: 'What would you like to improve in this section?',
    requirePrompt: false,
    responseKey: 'about',
    submit: improveAbout,
  },
  education: {
    title: 'Education Prompt',
    description: STAR_DESCRIPTION,
    placeholder: 'Tell me what to highlight in education...',
    requirePrompt: true,
    responseKey: 'education',
    submit: improveEducation,
  },
  work: {
    title: 'Work Experience Prompt',
    description: STAR_DESCRIPTION,
    placeholder: 'Share context to enrich work experience entries...',
    requirePrompt: true,
    responseKey: 'work_experience',
    submit: improveWorkExperience,
  },
  tools: {
    title: 'Tools Prompt',
    description: STAR_DESCRIPTION,
    placeholder: 'List the tools/skills to emphasize...',
    requirePrompt: true,
    responseKey: 'tools',
    submit: improveTools,
  },
};

function createAvailabilityState(enabled, reason) {
  return STAR_SECTIONS.reduce((acc, { id }) => {
    acc[id] = { enabled, reason };
    return acc;
  }, {});
}

function ResumeTab({ candidateId, candidate, onOpenAi, frameKey, onRefresh }) {
  const [openPopup, setOpenPopup] = useState(null);
  const [starAvailability, setStarAvailability] = useState(() => createAvailabilityState(false, 'Checking sources...'));
  const [checkingStars, setCheckingStars] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  const resumeUrl = useMemo(() => (candidateId ? `resume-readonly.html?id=${candidateId}` : '#'), [candidateId]);

  const applyResumePatch = useCallback((sectionId, payload) => {
    if (!window.Resume?.applyGenerated) return;
    const key = STAR_CONFIG[sectionId]?.responseKey;
    if (!key) return;
    const result = payload?.[key];
    if (result == null) return;
    window.Resume.applyGenerated({ [key]: result });
  }, []);

  const handleStarSubmit = useCallback(
    async (sectionId, prompt) => {
      const config = STAR_CONFIG[sectionId];
      if (!config) return null;
      const response = await config.submit(candidateId, prompt);
      applyResumePatch(sectionId, response);
      return response;
    },
    [applyResumePatch, candidateId],
  );

  const refreshStarAvailability = useCallback(async () => {
    if (!candidateId) return;
    setCheckingStars(true);
    try {
      let cand = candidate;
      if (!cand) {
        try {
          cand = await fetchCandidate(candidateId);
        } catch (err) {
          console.warn('Failed to load candidate for star gating', err);
        }
      }
      const trimmed = (value) => (value || '').toString().trim();
      let hasAnySource = false;
      if (cand) {
        hasAnySource = Boolean(
          trimmed(cand.linkedin_scrapper) ||
            trimmed(cand.cv_pdf_scrapper) ||
            trimmed(cand.affinda_scrapper) ||
            trimmed(cand.coresignal_scrapper) ||
            trimmed(cand.linkedin),
        );
      }
      if (!hasAnySource) {
        try {
          const files = await fetchCandidateCvs(candidateId);
          hasAnySource = Array.isArray(files) && files.length > 0;
        } catch (err) {
          console.warn('Failed to load candidate CVs', err);
        }
      }

      let resumeExists = false;
      try {
        await fetchResumeRecord(candidateId);
        resumeExists = true;
      } catch (err) {
        resumeExists = false;
      }

      const baseReason = hasAnySource ? '' : 'Please use the AI Assistant button first.';
      const aboutReason = hasAnySource
        ? resumeExists
          ? ''
          : 'Please complete resume first.'
        : 'Please use the AI Assistant button first.';

      setStarAvailability({
        about: { enabled: hasAnySource && resumeExists, reason: aboutReason || baseReason },
        education: { enabled: hasAnySource, reason: baseReason || 'Please use the AI Assistant button first.' },
        work: { enabled: hasAnySource, reason: baseReason || 'Please use the AI Assistant button first.' },
        tools: { enabled: hasAnySource, reason: baseReason || 'Please use the AI Assistant button first.' },
      });
    } catch (err) {
      console.error('Failed to evaluate star availability', err);
      setStarAvailability(createAvailabilityState(false, 'Unable to verify sources.'));
    } finally {
      setCheckingStars(false);
    }
  }, [candidateId, candidate]);

  useEffect(() => {
    refreshStarAvailability();
  }, [refreshStarAvailability, frameKey]);

  const handlePopupSuccess = useCallback(() => {
    onRefresh();
    refreshStarAvailability();
  }, [onRefresh, refreshStarAvailability]);

  const handleDownloadPdf = useCallback(async () => {
    if (!candidateId || downloadingPdf) return;
    setDownloadingPdf(true);
    try {
      const resume = await fetchResumeRecord(candidateId);
      await downloadResumePdf({ candidate, resume });
    } catch (err) {
      console.error('Failed to download resume PDF', err);
      alert('Unable to generate the resume PDF right now. Please try again in a moment.');
    } finally {
      setDownloadingPdf(false);
    }
  }, [candidateId, candidate, downloadingPdf]);

  return (
    <div id="resume" className="tab-content active">
      <div className="resume-toolbar">
        <button type="button" className="pill" onClick={onOpenAi}>
          ✨ AI Assistant
        </button>
        <a className="pill" href={resumeUrl} target="_blank" rel="noopener noreferrer">
          📄 Client Version
        </a>
        <button type="button" className="pill" onClick={handleDownloadPdf} disabled={downloadingPdf}>
          {downloadingPdf ? '⏳ Preparing PDF…' : '⬇️ Download PDF'}
        </button>
      </div>

      <div className="star-buttons">
        {STAR_SECTIONS.map(({ id, label, emoji }) => {
          const availability = starAvailability[id] || { enabled: false, reason: 'Checking sources...' };
          const disabled = checkingStars || !availability.enabled;
          return (
            <button
              key={id}
              className={`star-button ${disabled ? 'disabled-star' : ''}`}
              type="button"
              onClick={() => !disabled && setOpenPopup(id)}
              disabled={disabled}
              title={disabled ? availability.reason : undefined}
            >
              {emoji} {label}
            </button>
          );
        })}
      </div>

      <iframe key={frameKey} title="Resume" src={resumeUrl} className="resume-frame" />

      {STAR_SECTIONS.map(({ id }) => {
        const config = STAR_CONFIG[id];
        return (
          <StarPopup
            key={id}
            open={openPopup === id}
            title={config.title}
            description={config.description}
            placeholder={config.placeholder}
            requirePrompt={config.requirePrompt}
            onClose={() => setOpenPopup(null)}
            onSubmit={(prompt) => handleStarSubmit(id, prompt)}
            onSuccess={handlePopupSuccess}
          />
        );
      })}
    </div>
  );
}

ResumeTab.propTypes = {
  candidateId: PropTypes.number.isRequired,
  candidate: PropTypes.object,
  frameKey: PropTypes.number.isRequired,
  onOpenAi: PropTypes.func.isRequired,
  onRefresh: PropTypes.func.isRequired,
};

export default ResumeTab;
