import { NavLink } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { API_BASE_URL } from '../../constants/api.js';
import { getCurrentUserId } from '../../services/userService.js';

const SUMMARY_ALLOWED = new Set([
  'agustin@vintti.com',
  'bahia@vintti.com',
  'angie@vintti.com',
  'lara@vintti.com',
  'agostina@vintti.com',
  'mariano@vintti.com',
  'jazmin@vintti.com',
]);

const CANDIDATE_SEARCH_ALLOWED = new Set([
  'agustina.barbero@vintti.com',
  'agustin@vintti.com',
  'lara@vintti.com',
  'constanza@vintti.com',
  'pilar@vintti.com',
  'pilar.fernandez@vintti.com',
  'angie@vintti.com',
  'agostina@vintti.com',
  'julieta@vintti.com',
]);

const EQUIPMENTS_ALLOWED = new Set([
  'angie@vintti.com',
  'jazmin@vintti.com',
  'agustin@vintti.com',
  'lara@vintti.com',
]);

function initialsFromName(name = '') {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '—';
  const a = (parts[0]?.[0] || '').toUpperCase();
  const b = (parts[1]?.[0] || '').toUpperCase();
  return (a + b) || a || '—';
}

function initialsFromEmail(email = '') {
  const local = String(email).split('@')[0] || '';
  if (!local) return '—';
  const bits = local.split(/[._-]+/).filter(Boolean);
  return (bits.length >= 2)
    ? (bits[0][0] + bits[1][0]).toUpperCase()
    : local.slice(0, 2).toUpperCase();
}

function Sidebar({ collapsed }) {
  const [profile, setProfile] = useState({
    name: 'Profile',
    initials: '—',
    href: 'profile.html',
  });
  const [email, setEmail] = useState('');

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const stored = (window.localStorage.getItem('user_email') || window.sessionStorage.getItem('user_email') || '').toLowerCase();
    setEmail(stored);

    let isMounted = true;

    async function loadProfile() {
      let userId = null;
      try {
        userId = await getCurrentUserId();
      } catch {
        userId = Number(window.localStorage.getItem('user_id')) || null;
      }

      const profileHref = userId != null ? `profile.html?user_id=${encodeURIComponent(userId)}` : 'profile.html';
      let fetchedUser = null;

      try {
        if (userId != null) {
          const res = await fetch(`${API_BASE_URL}/users/${encodeURIComponent(userId)}?user_id=${encodeURIComponent(userId)}`, {
            credentials: 'include',
          });
          if (res.ok) {
            fetchedUser = await res.json();
          }
        }

        if (!fetchedUser) {
          const fallback = await fetch(`${API_BASE_URL}/profile/me${userId != null ? `?user_id=${encodeURIComponent(userId)}` : ''}`, {
            credentials: 'include',
          });
          if (fallback.ok) {
            fetchedUser = await fallback.json();
          }
        }
      } catch (error) {
        console.debug('[sidebar] profile fetch failed', error);
      }

      if (!isMounted) return;

      const name = fetchedUser?.user_name || 'Profile';
      const initials = fetchedUser?.user_name
        ? initialsFromName(fetchedUser.user_name)
        : initialsFromEmail(stored);

      setProfile({
        name,
        initials,
        href: profileHref,
      });
    }

    loadProfile();
    return () => {
      isMounted = false;
    };
  }, []);

  const showSummary = email && SUMMARY_ALLOWED.has(email);
  const showCandidateSearch = email && CANDIDATE_SEARCH_ALLOWED.has(email);
  const showEquipments = email && EQUIPMENTS_ALLOWED.has(email);

  return (
    <aside className={`sidebar ${collapsed ? 'custom-sidebar-hidden' : ''}`}>
      <img src="/assets/img/vintti_logo.png" alt="Vintti Logo" className="logo" />

      <nav className="sidebar-nav">
        <p className="sidebar-section-label">CORE</p>

        <NavLink to="/candidates" className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
          <span className="menu-icon"><i className="fa-solid fa-user-group" /></span>
          <span className="menu-label">Candidates</span>
        </NavLink>

        <NavLink to="/crm" className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
          <span className="menu-icon"><i className="fa-solid fa-building" /></span>
          <span className="menu-label">CRM</span>
        </NavLink>

        <NavLink to="/opportunities" className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
          <span className="menu-icon"><i className="fa-solid fa-chart-line" /></span>
          <span className="menu-label">Opportunities</span>
        </NavLink>

        {showCandidateSearch && (
          <NavLink to="/candidate-search" className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
            <span className="menu-icon"><i className="fa-solid fa-magnifying-glass" /></span>
            <span className="menu-label">Candidate Search</span>
          </NavLink>
        )}

        {showEquipments && (
          <a className="menu-item" href="equipments.html">
            <span className="menu-icon"><i className="fa-solid fa-laptop" /></span>
            <span className="menu-label">Equipments</span>
          </a>
        )}

        <p className="sidebar-section-label">INSIGHTS</p>

        {showSummary && (
          <NavLink to="/opportunities-summary" className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
            <span className="menu-icon"><i className="fa-solid fa-chart-column" /></span>
            <span className="menu-label">Opportunities Summary</span>
          </NavLink>
        )}

        <a
          className="menu-item"
          href="https://dashboard.vintti.com/public/dashboard/a6d74a9c-7ffb-4bec-b202-b26cdb57ff84?meses=3&metric_arpa=&metrica=revenue&tab=5-growth-%26-revenue"
          target="_blank"
          rel="noopener noreferrer"
        >
          <span className="menu-icon"><i className="fa-solid fa-gauge-high" /></span>
          <span className="menu-label">Dashboard</span>
        </a>

        <NavLink to="/management-metrics" className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
          <span className="menu-icon"><i className="fa-solid fa-chart-bar" /></span>
          <span className="menu-label">Management Metrics</span>
        </NavLink>

        <NavLink to="/recruiter-power" className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
          <span className="menu-icon"><i className="fa-solid fa-bolt" /></span>
          <span className="menu-label">Recruiter Power</span>
        </NavLink>

        <NavLink to="/sales-force" className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}>
          <span className="menu-icon"><i className="fa-solid fa-rocket" /></span>
          <span className="menu-label">Sales Force</span>
        </NavLink>
      </nav>

      <a href={profile.href} className="profile-tile" id="sidebarProfile">
        <span className="profile-avatar">
          <span id="profileAvatarInitials" className="profile-initials" aria-hidden="true">{profile.initials}</span>
        </span>
        <span className="profile-meta">
          <span id="profileName" className="profile-name">{profile.name}</span>
        </span>
      </a>
    </aside>
  );
}

export default Sidebar;
