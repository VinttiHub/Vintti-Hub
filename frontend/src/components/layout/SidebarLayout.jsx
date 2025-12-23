import { useEffect, useState } from 'react';
import Sidebar from './Sidebar.jsx';

function SidebarLayout({ children }) {
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const stored = window.localStorage.getItem('sidebarHidden') === 'true';
    setHidden(stored);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('sidebarHidden', hidden ? 'true' : 'false');
  }, [hidden]);

  return (
    <div className="app-shell">
      <Sidebar collapsed={hidden} />
      <div
        className="sidebar-wow-toggle"
        id="sidebarToggle"
        role="button"
        aria-label="Toggle sidebar"
        tabIndex={0}
        onClick={() => setHidden((prev) => !prev)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            setHidden((prev) => !prev);
          }
        }}
        style={{ left: hidden ? '12px' : '220px' }}
      >
        <i className={`fa-solid ${hidden ? 'fa-chevron-right' : 'fa-chevron-left'}`} aria-hidden="true" />
      </div>
      <main className={`main-content ${hidden ? 'custom-main-expanded' : ''}`}>
        {children}
      </main>
    </div>
  );
}

export default SidebarLayout;
