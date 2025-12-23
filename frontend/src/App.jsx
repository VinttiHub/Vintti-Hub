import { Navigate, Route, Routes } from 'react-router-dom';
import LoginPage from './pages/LoginPage.jsx';
import MigrationPlaceholder from './pages/MigrationPlaceholder.jsx';

const placeholderRoutes = [
  { path: '/opportunities', title: 'Opportunities', description: 'This view will host the migrated opportunities pipeline.' },
  { path: '/crm', title: 'CRM', description: 'Full CRM experience will move here in the next migration wave.' },
  { path: '/candidates', title: 'Candidates', description: 'Candidate search and detail flows will live here soon.' },
  { path: '/dashboard', title: 'Dashboard', description: 'Reporting widgets will be ported after the core flows.' },
];

function App() {
  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
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
