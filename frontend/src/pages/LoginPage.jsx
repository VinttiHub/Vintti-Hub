import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import PasswordResetModal from '../components/PasswordResetModal.jsx';
import { finalizeUserContext, loginRequest } from '../services/authService.js';
import { resolveAvatar } from '../utils/avatars.js';

function LoginPage() {
  const [formState, setFormState] = useState({ email: '', password: '' });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [nickname, setNickname] = useState('');
  const [showResetModal, setShowResetModal] = useState(false);
  const [showAnimation, setShowAnimation] = useState(false);
  const audioRef = useRef(null);
  const animationTimeoutRef = useRef(null);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const savedEmail = window.localStorage?.getItem('user_email');
    if (savedEmail) {
      setFormState((prev) => ({ ...prev, email: savedEmail }));
    }
    return () => {
      if (animationTimeoutRef.current) {
        clearTimeout(animationTimeoutRef.current);
      }
    };
  }, []);

  const loginAvatar = useMemo(() => resolveAvatar(formState.email), [formState.email]);
  const welcomeAvatar = isAuthenticated ? loginAvatar : null;

  const playClick = () => {
    const audio = audioRef.current;
    if (!audio) return;
    try {
      audio.currentTime = 0;
      const maybePromise = audio.play();
      if (maybePromise?.catch) {
        maybePromise.catch(() => {});
      }
    } catch (error) {
      console.debug('Click sound blocked:', error);
    }
  };

  const handleInputChange = (event) => {
    const { name, value } = event.target;
    setFormState((prev) => ({ ...prev, [name]: value }));
    if (errorMessage) setErrorMessage('');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (isSubmitting) return;

    setIsSubmitting(true);
    setErrorMessage('');
    playClick();

    try {
      const email = formState.email.trim().toLowerCase();
      const data = await loginRequest({ email, password: formState.password });
      setNickname(data.nickname || 'friend');

      await finalizeUserContext(email, data.user_id);
      const avatarSrc = resolveAvatar(email);
      if (avatarSrc && typeof window !== 'undefined') {
        window.localStorage.setItem('user_avatar', avatarSrc);
      }

      setIsAuthenticated(true);
      setShowAnimation(true);
      animationTimeoutRef.current = window.setTimeout(() => {
        setShowAnimation(false);
      }, 1800);
    } catch (error) {
      setErrorMessage(error.message || 'Unexpected error. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <audio
        id="click-sound"
        ref={audioRef}
        src="/assets/sounds/click.mp3"
        preload="auto"
        aria-hidden="true"
      />

      <div id="login-container" className="login-box" style={{ display: isAuthenticated ? 'none' : 'block' }}>
        <h2>Login</h2>
        <form id="login-form" onSubmit={handleSubmit}>
          <div className="input-with-avatar">
            <input
              type="email"
              id="email"
              name="email"
              placeholder="Enter your email"
              autoComplete="username"
              value={formState.email}
              onChange={handleInputChange}
              required
            />
            <img
              id="login-avatar"
              className="login-avatar"
              alt=""
              aria-hidden="true"
              loading="lazy"
              src={loginAvatar || undefined}
              style={{ display: loginAvatar ? 'block' : 'none' }}
            />
          </div>

          <input
            type="password"
            id="password"
            name="password"
            placeholder="Enter your password"
            autoComplete="current-password"
            value={formState.password}
            onChange={handleInputChange}
            required
          />

          <button
            type="button"
            id="open-reset-modal"
            className="link-button"
            onClick={() => setShowResetModal(true)}
            disabled={isSubmitting}
          >
            Forgot / Change password?
          </button>

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Authenticating…' : 'Login'}
          </button>
          <p
            id="chatResponse"
            style={{ marginTop: 10, color: errorMessage ? 'var(--danger, #ff4d4d)' : 'lime' }}
          >
            {errorMessage}
          </p>
        </form>
      </div>

      <main
        id="welcome-container"
        className="main-content fade-in"
        style={{ display: isAuthenticated ? 'block' : 'none' }}
      >
        <div
          id="login-animation"
          className={`login-animation ${showAnimation ? '' : 'hidden'}`}
          aria-hidden={!showAnimation}
        >
          <img src="/assets/img/vintti_logo.png" alt="Vintti Logo" className="login-animation-logo" />
          <p className="login-animation-text">Entering Vintti HUB...</p>
        </div>
        <h1 className="welcome-title">
          <img
            id="welcome-avatar"
            className="welcome-avatar"
            alt=""
            aria-hidden="true"
            loading="lazy"
            src={welcomeAvatar || undefined}
            style={{ display: welcomeAvatar ? 'inline-block' : 'none' }}
          />
          <span id="personalized-greeting">{nickname ? `Hey ${nickname}, ` : ''}</span>
          Welcome to <span className="gradient-text">Vintti HUB</span>
        </h1>
        <p className="holiday-mini-message">🎄 Christmas magic in the air — wishing you a bright and joyful day ✨</p>
        <Link to="/opportunities" className="main-action-button">
          🚀 Play hard, Execute and Push the limits.
        </Link>
      </main>

      <footer className="footer">&copy; 2025 Vintti. All rights reserved.</footer>
      <img src="/assets/img/vintti_logo.png" alt="Vintti Logo" className="corner-logo" />

      <div className="bubble-container">
        <span className="bubble-button bubble-lime">Outsource</span>
        <span className="bubble-button bubble-outline-blue">Grow</span>

        <span className="bubble-button bubble-pink">Vinttitutas</span>
        <span className="bubble-button bubble-outline-red">Negotiate</span>
        <span className="bubble-button bubble-red">Transformation</span>

        <span className="bubble-button bubble-outline-blue">Results</span>
        <span className="bubble-button bubble-lime">Lead</span>
        <span className="bubble-button bubble-outline-orange">Explore</span>

        <span className="bubble-button bubble-dark-red">Interview</span>
        <span className="bubble-button bubble-pink-dark">Sales-and-Ops</span>
        <span className="bubble-button bubble-orange">Innovate</span>

        <span className="bubble-button bubble-green">Hire</span>
      </div>

      <PasswordResetModal
        isOpen={showResetModal}
        initialEmail={formState.email}
        onClose={() => setShowResetModal(false)}
      />
    </>
  );
}

export default LoginPage;
