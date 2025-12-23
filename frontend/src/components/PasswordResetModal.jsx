import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { requestPasswordReset } from '../services/authService.js';

function PasswordResetModal({ isOpen, initialEmail, onClose }) {
  const [email, setEmail] = useState(initialEmail || '');
  const [feedback, setFeedback] = useState({ variant: '', message: '' });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setEmail(initialEmail || '');
      setFeedback({ variant: '', message: '' });
    }
  }, [isOpen, initialEmail]);

  const close = () => {
    if (!submitting) onClose();
  };

  const handleOverlayClick = (event) => {
    if (event.target === event.currentTarget) {
      close();
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const trimmedEmail = email.trim().toLowerCase();

    if (!trimmedEmail) {
      setFeedback({ variant: 'error', message: 'Please enter your email.' });
      return;
    }

    setSubmitting(true);
    setFeedback({ variant: '', message: '' });

    try {
      await requestPasswordReset(trimmedEmail);
      setFeedback({
        variant: 'ok',
        message: 'If this email exists, a reset link has been sent.',
      });
    } catch (error) {
      setFeedback({
        variant: 'error',
        message: error.message || 'There was an error sending the reset email.',
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      id="passwordResetModal"
      className="modal-overlay"
      style={{ display: isOpen ? 'flex' : 'none' }}
      onClick={handleOverlayClick}
    >
      <div className="modal-box" onClick={(event) => event.stopPropagation()}>
        <h3>Reset your password</h3>
        <p>Enter your Vintti email and we’ll send you a secure link to update your password.</p>

        <form id="passwordResetForm" onSubmit={handleSubmit}>
          <input
            type="email"
            id="resetEmail"
            name="resetEmail"
            placeholder="your.email@vintti.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            disabled={submitting}
          />
          <div className="modal-actions">
            <button type="submit" disabled={submitting}>
              {submitting ? 'Sending…' : 'Send reset link'}
            </button>
            <button type="button" id="close-reset-modal" className="secondary-btn" onClick={close} disabled={submitting}>
              Cancel
            </button>
          </div>
          <p id="resetFeedback" className={`reset-feedback ${feedback.variant || ''}`}>
            {feedback.message}
          </p>
        </form>
      </div>
    </div>
  );
}

PasswordResetModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  initialEmail: PropTypes.string,
  onClose: PropTypes.func.isRequired,
};

export default PasswordResetModal;
