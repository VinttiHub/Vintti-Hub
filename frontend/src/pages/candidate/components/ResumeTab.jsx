import PropTypes from 'prop-types';

function ResumeTab({ candidateId, candidate, onOpenAi }) {
  return (
    <div id="resume" className="tab-content active">
      <div className="resume-toolbar">
        <button type="button" onClick={onOpenAi}>
          ✨ AI Assistant
        </button>
        <button type="button">Client Version</button>
      </div>
      <iframe
        title="Resume"
        src={`resume-readonly.html?candidate_id=${candidateId}`}
        className="resume-frame"
      />
    </div>
  );
}

ResumeTab.propTypes = {
  candidateId: PropTypes.number.isRequired,
  candidate: PropTypes.object,
  onOpenAi: PropTypes.func.isRequired,
};

export default ResumeTab;
