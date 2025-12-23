import { useEffect } from 'react';
import PropTypes from 'prop-types';

function ExternalRedirect({ href }) {
  useEffect(() => {
    if (href) {
      window.location.replace(href);
    }
  }, [href]);

  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <p>Redirecting to {href}…</p>
    </div>
  );
}

ExternalRedirect.propTypes = {
  href: PropTypes.string.isRequired,
};

export default ExternalRedirect;
