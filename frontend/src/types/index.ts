export type UserRole = 'admin' | 'scrutiny' | 'expert' | 'approver' | 'supervisor' | 'institution';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  institution_name?: string | null;
  is_active: boolean;
  created_at?: string;
  public_key_pem?: string | null;
}

export type ApplicationStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'deficiency_found'
  | 'verified'
  | 'approved'
  | 'rejected';

export type ApplicationCategory = 'eoa' | 'new_institution' | 'change_intake' | 'closure' | 'other';

export type AIRecommendation =
  | 'pending'
  | 'forward_for_approval'
  | 'seek_clarification'
  | 'deficiency_suspected'
  | 'physical_inspection_suggested';

export interface ChecklistItem {
  doc_type: DocumentType;
  rule_code: string;
  title: string;
  description: string;
  fix_hint?: string;
}

export interface Application {
  id: string;
  application_number: string;
  institution_id: string;
  institution_name: string;
  permanent_id?: string | null;
  requested_intake?: number | null;
  category: ApplicationCategory;
  academic_year: string;
  status: ApplicationStatus;
  risk_score: number;
  ai_recommendation?: AIRecommendation | null;
  ai_summary?: string | null;
  ai_reviewed_at?: string | null;
  overall_verdict?: string | null;
  decided_at?: string | null;
  assigned_reviewer_id?: string | null;
  assigned_by?: string | null;
  assigned_at?: string | null;
  rectification_due?: string | null;
  submitted_at: string;
  updated_at: string;
  documents?: DocumentItem[];
  validation_results?: ValidationResult[];
  checklist?: ChecklistItem[];
  total_documents?: number;
  pending_documents?: number;
  flagged_documents?: number;
}

export type DocumentType =
  | 'fire_safety'
  | 'audit_report'
  | 'land_document'
  | 'faculty_list'
  | 'noc'
  | 'affidavit'
  | 'building_plan'
  | 'lab_photo'
  | 'asset_register'
  | 'campus_boundary'
  | 'other';

export type DocumentStatus = 'pending' | 'processing' | 'validated' | 'flagged' | 'rejected' | 'failed';

export interface Box {
  page?: number;
  x: number;
  y: number;
  w: number;
  h: number;
  label?: string;
}

export interface Indicator {
  method: string;
  strength: 'weak' | 'medium' | 'strong';
  description: string;
  hidden_text?: string;
  visible_text?: string;
  boxes?: Box[];
}

export interface DocumentItem {
  id: string;
  application_id: string;
  doc_type: DocumentType;
  original_filename: string;
  file_size: number;
  mime_type: string;
  status: DocumentStatus;
  extracted_data: Record<string, any>;
  page_count: number;
  processing_stage?: string | null;
  processing_progress?: number | null;
  is_current: boolean;
  superseded_by_id?: string | null;
  uploaded_at: string;
}

export interface FieldComparison {
  field: string;
  submitted: any;
  official: any;
  kind: string;
  match: boolean | null;
  score: number | null;
  reason: string;
}

export interface Verification {
  id: string;
  document_id: string;
  method: 'api' | 'qr_code' | 'digital_signature' | 'portal' | 'manual';
  source_authority: string;
  status: 'verified' | 'mismatch' | 'expired' | 'pending' | 'unavailable' | 'manual_review';
  request_identifiers?: Record<string, any> | null;
  source_response: Record<string, any>;
  field_comparison?: FieldComparison[] | null;
  reason?: string | null;
  attempts?: number | null;
  next_retry_at?: string | null;
  verified_at: string;
}

export interface DocumentDetail extends DocumentItem {
  verifications: Verification[];
  findings: ValidationResult[];
  versions: { id: string; filename: string; uploaded_at: string; is_current: boolean; status: string }[];
}

export type Severity = 'info' | 'warning' | 'critical';
export type CheckType =
  | 'completeness'
  | 'expiry'
  | 'consistency'
  | 'forgery'
  | 'compliance'
  | 'infrastructure'
  | 'duplicate'
  | 'verification'
  | 'records';

export interface ValidationResult {
  id: string;
  application_id: string;
  document_id?: string | null;
  check_type: CheckType;
  severity: Severity;
  finding: string;
  evidence?: string | null;
  fix_hint?: string | null;
  details: Record<string, any>;
  confidence: number;
  rule_code?: string | null;
  rule_version?: number | null;
  rag?: Rag | null;
  actionable_by?: 'institution' | 'officer' | 'system' | null;
  fingerprint?: string | null;
  created_at: string;
}

export interface ValidationReport {
  application_id: string;
  application_number: string;
  institution_name: string;
  risk_score: number;
  summary: {
    critical_flags: number;
    warning_flags: number;
    info_flags: number;
    risk_score: number;
    ai_recommendation: AIRecommendation | null;
    ai_summary: string | null;
    risk_contributions: { finding: string; severity: Severity; points: number }[];
  };
  findings: ValidationResult[];
  generated_at: string;
  disclaimer: string;
}

export interface DashboardStats {
  total_applications: number;
  awaiting_review: number;
  deficiency_found: number;
  approved: number;
  rejected: number;
  high_risk_flagged: number;
  total_documents_processed: number;
  tamper_suspected_count: number;
  duplicate_flags: number;
  pending_source_verifications: number;
  avg_processing_seconds_per_document: number | null;
  overdue_rectifications: number;
}

export interface Metrics {
  verification: { total_checks: number; by_status: Record<string, number>; automated_completion_rate: number | null };
  forensics: { documents: number; by_level: Record<string, number> };
  processing: { documents_with_timing: number; avg_seconds_per_document: number | null; max_seconds: number | null };
  decisions: { decided: number; ai_human_agreement_rate: number | null; duplicate_findings: number };
}

export interface RiskDistributionItem {
  category: string;
  count: number;
  color: string;
}

export interface AlertItem {
  id: string;
  application_id: string;
  application_number: string;
  institution_name: string;
  title: string;
  severity: Severity;
  check_type: CheckType;
  message: string;
  created_at: string;
}

export interface ActivityItem {
  id: string;
  action: string;
  user_name: string;
  institution_name: string;
  timestamp: string;
  details: string;
}

export interface RuleCheck {
  fact: string;
  op: string;
  value?: any;
  label?: string;
}

export interface ComplianceRule {
  id: string;
  rule_code: string;
  title: string;
  category: 'infrastructure' | 'academic' | 'financial' | 'statutory' | 'safety';
  description: string;
  conditions: { requires_doc?: DocumentType; check?: RuleCheck; fix_hint?: string; on_missing_fact?: string; [k: string]: any };
  applies_to?: string[] | null;
  severity?: Severity | null;
  handbook_reference?: string | null;
  version: number;
  is_active: boolean;
  updated_at: string;
}

export interface ComplianceEvaluation {
  application_id: string;
  total_rules_evaluated: number;
  compliant_count: number;
  deficiency_count: number;
  compliance_score: number;
  amber_count?: number;
  results: {
    rule_code: string;
    title: string;
    category: string;
    rag?: Rag;
    clause?: string | null;
    handbook_reference?: string | null;
    trace?: string[];
    status: 'compliant' | 'non_compliant' | 'warning' | 'not_applicable';
    message: string;
    evidence?: string | null;
    rule_version?: number | null;
    expected?: string | null;
    actual?: string | null;
    fix_hint?: string | null;
  }[];
}

export interface EncryptedEnvelope { alg: string; ek: string; iv: string; ct: string }

export interface ClarificationPayload {
  application_number: string;
  note: string;
  due: string;
  items: { doc_type: string | null; request: string; what_to_do: string }[];
}

export interface NotificationItem {
  id: string;
  application_id: string;
  subject: string;
  body: string;
  items: { fingerprint?: string; rule_code?: string | null; doc_type?: string | null }[];
  encrypted_payload?: EncryptedEnvelope | null;
  payload_sha256?: string | null;
  channels: string[];
  status: 'sent' | 'acknowledged' | 'resolved';
  due_date?: string | null;
  created_at: string;
  acknowledged_at?: string | null;
}

export type DeadlineKind = 'workflow' | 'evc' | 'undertaking' | 'lease_expiry' | 'document_expiry';
export interface DeadlineItem {
  id: string;
  application_id: string;
  created_by: string;
  assigned_to?: string | null;
  kind: DeadlineKind;
  title: string;
  description?: string | null;
  due_at: string;
  remind_before_hours: number;
  escalate_after_hours: number;
  reminder_sent: boolean;
  escalation_level: number;
  status: 'open' | 'completed' | 'cancelled';
  completed_at?: string | null;
  created_at: string;
}

export interface WorkflowTransitionItem {
  id: string;
  from_status: ApplicationStatus;
  to_status: ApplicationStatus;
  allowed_roles: string[];
  is_active: boolean;
  updated_at: string;
}

export interface AuditEntry {
  id: string;
  action: string;
  details: Record<string, any>;
  ip_address?: string | null;
  created_at: string;
  user_id?: string | null;
  actor: string;
  actor_role?: string | null;
  application_id?: string | null;
  entry_hash?: string | null;
  prev_hash?: string | null;
}

export interface InfraReport {
  status: 'analyzed' | 'detector_unavailable' | 'unreadable';
  model: string | null;
  equipment_counts: Record<string, number>;
  raw_detections: Record<string, number>;
  compliance_flags: { equipment: string; object: string; required: number; detected: number | null; status: string; message: string; rule_code?: string }[];
  evidence_quality: { brightness?: number; sharpness?: number; resolution?: number[]; issues: string[] };
  frames_analyzed: number;
  annotated_image_base64?: string | null;
  needs_manual_review: boolean;
  disclaimer: string;
}

// ------------------------------------------------------------------ RAG triage (officers only)

export type Rag = 'green' | 'amber' | 'red' | 'not_applicable';

/** Institution-facing ("blind") views: no analysis, flags, scores or processing stages. */
export type PortalStatus = 'draft' | 'received' | 'under_review' | 'clarification_requested' | 'approved' | 'rejected';

export interface PortalDocument {
  id: string;
  doc_type: DocumentType;
  original_filename: string;
  file_size: number;
  uploaded_at: string;
  is_current: boolean;
  state: 'received';
}

export interface PortalApplication {
  id: string;
  application_number: string;
  institution_name: string;
  permanent_id?: string | null;
  requested_intake?: number | null;
  category: ApplicationCategory;
  academic_year: string;
  status: PortalStatus;
  rectification_due?: string | null;
  submitted_at: string;
  updated_at: string;
  documents: PortalDocument[];
  checklist: { doc_type: DocumentType; title: string; description: string }[];
}

export interface RuleOutcome {
  rule_code: string;
  rule_version: number;
  title: string;
  category: string;
  rag: Rag;
  kind: string;
  actionable_by?: string | null;
  message: string;
  clause?: string | null;
  handbook_reference?: string | null;
  trace?: string[];
  expected?: string | null;
  actual?: string | null;
  fix_hint?: string | null;
  doc_type?: DocumentType | null;
}

export interface FindingReviewInfo { decision: 'confirmed' | 'overridden'; reason: string; at: string; reviewer_id: string }

export interface TriageFinding extends ValidationResult { review: FindingReviewInfo | null }

export interface TriageDocument {
  id: string;
  doc_type: DocumentType;
  filename: string;
  status: DocumentStatus;
  mime_type: string;
  page_count: number;
  uploaded_at: string;
  watermark?: string | null;
  original_sha256?: string | null;
  stored_sha256?: string | null;
}

export interface TriageBundle {
  application: Application;
  rules: RuleOutcome[];
  findings: TriageFinding[];
  documents: TriageDocument[];
  counts: { green_rules: number; amber: number; red: number; red_unreviewed: number };
  approval_blockers: string[];
  clarification_candidates: string[];
}

export interface TriageQueueItem {
  application: Application;
  red: number;
  red_unreviewed: number;
  red_confirmed: number;
  amber: number;
  amber_institution: number;
}

export interface CustodyReport {
  intact: boolean;
  checks: Record<string, boolean>;
  stored_sha256?: string;
  watermark?: string | null;
  received_at?: string | null;
  note?: string | null;
  matches_stored_hash_at_intake?: boolean;
}

export interface GraphView {
  backend: 'neo4j' | 'in-process';
  nodes: { id: string; type: string; label: string; focus?: boolean }[];
  edges: { from: string; to: string; kind: string; application?: string }[];
  links: { kind: string; finding: string; evidence: string; cypher?: string; masked?: string; serial?: string }[];
}
