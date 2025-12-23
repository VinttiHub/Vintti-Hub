import { Navigate, Route, Routes } from 'react-router-dom';
import LoginPage from './pages/LoginPage.jsx';
import MigrationPlaceholder from './pages/MigrationPlaceholder.jsx';
import OpportunitiesPage from './pages/opportunities/OpportunitiesPage.jsx';
import CandidatesPage from './pages/candidates/CandidatesPage.jsx';
import CrmPage from './pages/crm/CrmPage.jsx';

const placeholderRoutes = [
  { path: '/candidate-search', title: 'Candidate Search', description: 'Advanced search filters will be ported shortly.' },
  { path: '/dashboard', title: 'Dashboard', description: 'Reporting widgets will be ported after the core flows.' },
  { path: '/opportunities-summary', title: 'Opportunities Summary', description: 'Summary dashboards will land after pipeline parity.' },
  { path: '/recruiter-power', title: 'Recruiter Power', description: 'Recruiter metrics are still being migrated.' },
];

function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/opportunities" element={<OpportunitiesPage />} />
      <Route path="/candidates" element={<CandidatesPage />} />
      <Route path="/crm" element={<CrmPage />} />
      {placeholderRoutes.map(route => (
        <Route
          key={route.path}
          path={route.path}
          element={<MigrationPlaceholder title={route.title} description={route.description} />}
        />
      ))}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
