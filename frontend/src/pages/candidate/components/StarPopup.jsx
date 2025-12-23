import { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';

function StarPopup({
  open,
  title,
  description,
  placeholder,
  requirePrompt = true,
  onClose,
  onSubmit,
  onSuccess,
}) {
  const [prompt, setPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const textareaRef = useRef(null);

  useEffect(() => {
    if (!open) {
      setPrompt('');
      setLoading(false);
      setError('');
      return;
    }
    setPrompt('');
    setError('');
    setLoading(false);
    const id = requestAnimationFrame(() => textareaRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, [open]);

  async function handleGenerate(event) {
    event?.preventDefault();
    const value = prompt.trim();
    if (requirePrompt && !value) {
      setError('Please add a comment before generating.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const result = await onSubmit(value);
      onSuccess?.(result);
      setPrompt('');
      onClose();
    } catch (err) {
      console.error(err);
      setError(err?.message || 'Failed to improve this section. Try again.');
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="star-popup"
      role="dialog"
      aria-modal="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <button className="close-star-popup" type="button" aria-label="Close" onClick={onClose}>
        ✖
      </button>
      <h3>{title}</h3>
      {description && <p className="reminder">{description}</p>}
      <textarea
        ref={textareaRef}
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder={placeholder}
        disabled={loading}
      />
      {error && (
        <p className="reminder" style={{ color: '#d33' }}>
          {error}
        </p>
      )}
      <button className="generate-btn" type="button" onClick={handleGenerate} disabled={loading}>
        {loading ? 'Working...' : 'Generate'}
      </button>
    </div>
  );
}

StarPopup.propTypes = {
  open: PropTypes.bool.isRequired,
  title: PropTypes.string.isRequired,
  description: PropTypes.string,
  placeholder: PropTypes.string,
  requirePrompt: PropTypes.bool,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  onSuccess: PropTypes.func,
};

export default StarPopup;
