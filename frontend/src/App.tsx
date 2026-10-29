import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { DashboardLayout } from './components/layout/DashboardLayout';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { ApplicationsPage } from './pages/ApplicationsPage';
import { ApplicationDetailPage } from './pages/ApplicationDetailPage';
import { CompliancePage } from './pages/CompliancePage';
import { InfrastructurePage } from './pages/InfrastructurePage';
import { AuditPage } from './pages/AuditPage';
import { AdminPage } from './pages/AdminPage';
import { InstitutionHomePage } from './pages/InstitutionHomePage';
import { NoticesPage } from './pages/NoticesPage';
import { PortalApplicationPage } from './pages/PortalApplicationPage';
import { DeadlinesPage } from './pages/DeadlinesPage';
import { WorkflowPage } from './pages/WorkflowPage';
import type { UserRole } from './types';

const Protected: React.FC<{ children: React.ReactNode; roles?: UserRole[] }> = ({ children, roles }) => {
  const { user, isLoading } = useAuth();
  if (isLoading) {
    return <div className="min-h-screen w-full flex items-center justify-center bg-slate-50 text-slate-600 text-sm font-medium">Verifying session…</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  return <>{children}</>;
};

const Home: React.FC = () => {
  const { user } = useAuth();
  return user?.role === 'institution' ? <InstitutionHomePage /> : <DashboardPage />;
};

const OFFICIALS: UserRole[] = ['admin', 'scrutiny', 'expert', 'approver', 'supervisor'];

/** Institutions get the blind portal view; officers get the triage console. */
const ApplicationRoute: React.FC = () => {
  const { user } = useAuth();
  return user?.role === 'institution' ? <PortalApplicationPage /> : <ApplicationDetailPage />;
};

export const App: React.FC = () => (
  <AuthProvider>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<Protected><DashboardLayout /></Protected>}>
          <Route index element={<Home />} />
          <Route path="applications" element={<Protected roles={OFFICIALS}><ApplicationsPage /></Protected>} />
          <Route path="applications/:id" element={<ApplicationRoute />} />
          <Route path="notices" element={<Protected roles={['institution']}><NoticesPage /></Protected>} />
          <Route path="deadlines" element={<DeadlinesPage />} />
          <Route path="compliance" element={<CompliancePage />} />
          <Route path="infrastructure" element={<Protected roles={OFFICIALS}><InfrastructurePage /></Protected>} />
          <Route path="audit" element={<Protected roles={OFFICIALS}><AuditPage /></Protected>} />
          <Route path="admin" element={<Protected roles={['admin']}><AdminPage /></Protected>} />
          <Route path="workflow" element={<Protected roles={['admin']}><WorkflowPage /></Protected>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </AuthProvider>
);

export default App;
