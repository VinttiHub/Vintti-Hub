import { Navigate, Route, Routes } from 'react-router-dom';
import LoginPage from './pages/LoginPage.jsx';
import MigrationPlaceholder from './pages/MigrationPlaceholder.jsx';
import OpportunitiesPage from './pages/opportunities/OpportunitiesPage.jsx';
import CandidatesPage from './pages/candidates/CandidatesPage.jsx';
import CrmPage from './pages/crm/CrmPage.jsx';
import CandidateSearchPage from './pages/candidateSearch/CandidateSearchPage.jsx';
import CandidateDetailPage from './pages/candidate/CandidateDetailPage.jsx';
import OpportunitiesSummaryPage from './pages/opportunitiesSummary/OpportunitiesSummaryPage.jsx';
import RecruiterPowerPage from './pages/recruiterPower/RecruiterPowerPage.jsx';
import AccountDetailPage from './pages/account/AccountDetailPage.jsx';
import MainDashboardRedirect from './pages/redirects/MainDashboardRedirect.jsx';
import ControlDashboardRedirect from './pages/redirects/ControlDashboardRedirect.jsx';
import SalesForceRedirect from './pages/redirects/SalesForceRedirect.jsx';

const placeholderRoutes = [];

function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/opportunities" element={<OpportunitiesPage />} />
      <Route path="/candidates" element={<CandidatesPage />} />
      <Route path="/candidates/:id" element={<CandidateDetailPage />} />
      <Route path="/crm" element={<CrmPage />} />
      <Route path="/candidate-search" element={<CandidateSearchPage />} />
      <Route path="/opportunities-summary" element={<OpportunitiesSummaryPage />} />
      <Route path="/recruiter-power" element={<RecruiterPowerPage />} />
      <Route path="/accounts/:id" element={<AccountDetailPage />} />
      <Route path="/dashboard" element={<MainDashboardRedirect />} />
      <Route path="/management-metrics" element={<ControlDashboardRedirect />} />
      <Route path="/sales-force" element={<SalesForceRedirect />} />
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
