import PropTypes from 'prop-types';

function MigrationPlaceholder({ title, description }) {
  return (
    <main className="main-content fade-in" style={{ display: 'block', textAlign: 'center' }}>
      <section className="login-box" style={{ maxWidth: 520 }}>
        <p className="holiday-mini-message" style={{ marginBottom: 0 }}>
          Coming soon
        </p>
        <h1 style={{ marginTop: 24 }}>{title}</h1>
        <p style={{ marginBottom: 24 }}>{description}</p>
        <p style={{ color: 'var(--muted)', marginBottom: 32 }}>
          We&apos;re finishing the backend wiring before porting this screen. Routes already exist, so plugging the
          translated JSX will be seamless.
        </p>
        <a href="/" className="main-action-button">
          Back to login
        </a>
      </section>
    </main>
  );
}

MigrationPlaceholder.propTypes = {
  title: PropTypes.string.isRequired,
  description: PropTypes.string.isRequired,
};

export default MigrationPlaceholder;
