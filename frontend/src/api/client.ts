import axios from 'axios';
import type {
  User,
  Application,
  DocumentItem,
  DocumentDetail,
  ValidationReport,
  DashboardStats,
  Metrics,
  RiskDistributionItem,
  AlertItem,
  ActivityItem,
  ComplianceRule,
  ComplianceEvaluation,
  NotificationItem,
  AuditEntry,
  Verification,
  InfraReport,
  ChecklistItem,
  PortalApplication,
  PortalDocument,
  TriageBundle,
  TriageQueueItem,
  CustodyReport,
  GraphView,
  DeadlineItem,
  DeadlineKind,
  WorkflowTransitionItem,
} from '../types';

const api = axios.create({ baseURL: import.meta.env.VITE_API_URL || '/api' });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('aicte_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error?.response?.status === 401 && !String(error.config?.url).includes('/auth/login')) {
      localStorage.removeItem('aicte_token');
      if (window.location.pathname !== '/login') window.location.assign('/login');
    }
    return Promise.reject(error);
  },
);

/** Human-readable message from an API error. */
export const errorMessage = (err: any): string => {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ');
  return err?.message || 'Request failed';
};

/** Fetch an authenticated binary resource and return an object URL for <img>/<iframe>. */
export const fetchBlobUrl = async (path: string): Promise<string> => {
  const res = await api.get(path, { responseType: 'blob' });
  return URL.createObjectURL(res.data);
};

export const authApi = {
  login: async (credentials: { email: string; password: string }) => (await api.post('/auth/login-json', credentials)).data,
  register: async (data: { email: string; password: string; full_name: string; institution_name?: string }) =>
    (await api.post('/auth/register', data)).data,
  getMe: async (): Promise<User> => (await api.get('/auth/me')).data,
  setPublicKey: async (public_key_pem: string) => (await api.put('/auth/public-key', { public_key_pem })).data,
};

export const applicationsApi = {
  list: async (params?: { status?: string; category?: string; search?: string }): Promise<Application[]> =>
    (await api.get('/applications', { params })).data,
  reviewers: async (): Promise<{ id: string; full_name: string; role: string }[]> => (await api.get('/applications/reviewers')).data,
  assign: async (id: string, assigned_to: string | null, reason: string): Promise<Application> =>
    (await api.patch(`/applications/${id}/assignment`, { assigned_to, reason })).data,
  get: async (id: string): Promise<Application> => (await api.get(`/applications/${id}`)).data,
  create: async (data: { category: string; academic_year: string; permanent_id?: string; requested_intake?: number }): Promise<Application> =>
    (await api.post('/applications', data)).data,
  update: async (id: string, data: { category: string; academic_year: string; permanent_id?: string; requested_intake?: number }) =>
    (await api.patch(`/applications/${id}`, data)).data,
  submit: async (id: string): Promise<Application> => (await api.post(`/applications/${id}/submit`)).data,
  decide: async (id: string, status: string, verdict_notes?: string): Promise<Application> =>
    (await api.post(`/applications/${id}/decision`, { status, verdict_notes })).data,
  clarificationRequest: async (id: string, notes: string, due_days: number, finding_ids?: string[]): Promise<NotificationItem> =>
    (await api.post(`/applications/${id}/clarification-request`, { notes, due_days, finding_ids })).data,
};

/** Institution portal: the same endpoints answer institutions with blind views. */
export const portalApi = {
  list: async (): Promise<PortalApplication[]> => (await api.get('/applications')).data,
  get: async (id: string): Promise<PortalApplication> => (await api.get(`/applications/${id}`)).data,
  create: async (data: { category: string; academic_year: string; permanent_id?: string; requested_intake?: number }): Promise<PortalApplication> =>
    (await api.post('/applications', data)).data,
  submit: async (id: string): Promise<PortalApplication> => (await api.post(`/applications/${id}/submit`)).data,
};

export const triageApi = {
  queue: async (): Promise<TriageQueueItem[]> => (await api.get('/triage/queue')).data,
  bundle: async (id: string): Promise<TriageBundle> => (await api.get(`/triage/${id}`)).data,
  review: async (appId: string, findingId: string, decision: 'confirmed' | 'overridden', reason: string) =>
    (await api.post(`/triage/${appId}/findings/${findingId}/review`, { decision, reason })).data,
  graph: async (id: string): Promise<GraphView> => (await api.get(`/triage/${id}/graph`)).data,
};

export const documentsApi = {
  upload: async (applicationId: string, file: File, docType?: string): Promise<PortalDocument> => {
    const fd = new FormData();
    fd.append('application_id', applicationId);
    fd.append('file', file);
    if (docType) fd.append('doc_type', docType);
    return (await api.post('/documents/upload', fd)).data;
  },
  replace: async (docId: string, file: File): Promise<PortalDocument> => {
    const fd = new FormData();
    fd.append('file', file);
    return (await api.post(`/documents/${docId}/replace`, fd)).data;
  },
  get: async (id: string): Promise<DocumentDetail> => (await api.get(`/documents/${id}`)).data,
  custody: async (id: string): Promise<CustodyReport> => (await api.get(`/documents/${id}/custody`)).data,
  reprocess: async (id: string): Promise<DocumentItem> => (await api.post(`/documents/${id}/reprocess`)).data,
  pageUrl: (id: string, page = 0) => `/documents/${id}/page/${page}`,
  evidenceUrl: (id: string, kind: 'evidence' | 'ela' | 'annotated') => `/documents/${id}/evidence/${kind}`,
  fileUrl: (id: string) => `/documents/${id}/file`,
};

export const validationApi = {
  trigger: async (appId: string) => (await api.post(`/validation/trigger/${appId}`)).data,
  getReport: async (appId: string): Promise<ValidationReport> => (await api.get(`/validation/report/${appId}`)).data,
};

export const verificationApi = {
  trigger: async (docId: string): Promise<Verification[]> => (await api.post(`/verification/trigger/${docId}`)).data,
  getStatus: async (docId: string): Promise<Verification[]> => (await api.get(`/verification/status/${docId}`)).data,
  sources: async () => (await api.get('/verification/sources')).data,
};

export const infrastructureApi = {
  analyze: async (file: File): Promise<InfraReport> => {
    const fd = new FormData();
    fd.append('file', file);
    return (await api.post('/infrastructure/analyze', fd)).data;
  },
  norms: async (): Promise<{ object: string; min: number; rule_code: string; label: string }[]> => (await api.get('/infrastructure/norms')).data,
};

export const complianceApi = {
  getRules: async (includeInactive = false): Promise<ComplianceRule[]> =>
    (await api.get('/compliance/rules', { params: { include_inactive: includeInactive } })).data,
  createRule: async (rule: Partial<ComplianceRule>): Promise<ComplianceRule> => (await api.post('/compliance/rules', rule)).data,
  updateRule: async (id: string, changes: Partial<ComplianceRule> & { change_reason: string }): Promise<ComplianceRule> =>
    (await api.patch(`/compliance/rules/${id}`, changes)).data,
  history: async (id: string): Promise<{ action: string; at: string; details: any }[]> => (await api.get(`/compliance/rules/${id}/history`)).data,
  check: async (appId: string): Promise<ComplianceEvaluation> => (await api.get(`/compliance/check/${appId}`)).data,
  checklist: async (appId: string): Promise<ChecklistItem[]> => (await api.get(`/compliance/checklist/${appId}`)).data,
};

export const dashboardApi = {
  getStats: async (): Promise<DashboardStats> => (await api.get('/dashboard/stats')).data,
  getRiskDistribution: async (): Promise<RiskDistributionItem[]> => (await api.get('/dashboard/risk-distribution')).data,
  getAlerts: async (): Promise<AlertItem[]> => (await api.get('/dashboard/alerts', { params: { limit: 12 } })).data,
  getRecentActivity: async (): Promise<ActivityItem[]> => (await api.get('/dashboard/recent-activity')).data,
  getMetrics: async (): Promise<Metrics> => (await api.get('/dashboard/metrics')).data,
  exportReport: async (): Promise<Blob> => (await api.get('/dashboard/report.csv', { responseType: 'blob' })).data,
};

export const auditApi = {
  getAppLogs: async (appId: string): Promise<AuditEntry[]> => (await api.get(`/audit/${appId}`)).data,
  getSystemLogs: async (action?: string): Promise<AuditEntry[]> => (await api.get('/audit/system/recent', { params: { action, limit: 200 } })).data,
  verifyChain: async () => (await api.get('/audit/verify-chain')).data,
};

export const notificationsApi = {
  list: async (applicationId?: string): Promise<NotificationItem[]> =>
    (await api.get('/notifications', { params: { application_id: applicationId } })).data,
  acknowledge: async (id: string): Promise<NotificationItem> => (await api.post(`/notifications/${id}/acknowledge`)).data,
};

export const deadlinesApi = {
  list: async (): Promise<DeadlineItem[]> => (await api.get('/deadlines')).data,
  create: async (data: { application_id: string; kind: DeadlineKind; title: string; description?: string; due_at: string; remind_before_hours: number; escalate_after_hours: number }) =>
    (await api.post('/deadlines', data)).data as DeadlineItem,
  complete: async (id: string) => (await api.patch(`/deadlines/${id}`, { status: 'completed', reason: 'Marked complete in Validex' })).data as DeadlineItem,
  processDue: async (): Promise<{ reminders_created: number; escalations_created: number }> => (await api.post('/deadlines/process-due')).data,
};

export const workflowApi = {
  list: async (): Promise<WorkflowTransitionItem[]> => (await api.get('/workflow/transitions')).data,
  configure: async (edge: { from_status: string; to_status: string; allowed_roles: string[]; is_active: boolean; change_reason: string }) =>
    (await api.put('/workflow/transitions', edge)).data as WorkflowTransitionItem,
};

export const adminApi = {
  users: async (): Promise<User[]> => (await api.get('/admin/users')).data,
  createUser: async (data: { email: string; password: string; full_name: string; role: string; institution_name?: string }) =>
    (await api.post('/admin/users', data)).data,
  setActive: async (id: string, is_active: boolean) => (await api.patch(`/admin/users/${id}`, { is_active })).data,
  outageStatus: async (): Promise<{ outage: boolean; mode: string }> => (await api.get('/admin/simulated-sources/status')).data,
  setOutage: async (enabled: boolean) => (await api.post('/admin/simulated-sources/outage', { enabled })).data,
  purge: async (dryRun: boolean, retentionDays?: number) =>
    (await api.post('/admin/retention/purge', null, { params: { dry_run: dryRun, retention_days: retentionDays } })).data,
};

export default api;
