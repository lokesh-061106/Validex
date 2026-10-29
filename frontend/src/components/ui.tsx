import React, { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle, HelpCircle } from 'lucide-react';
import { fetchBlobUrl } from '../api/client';
import type { AIRecommendation, ApplicationStatus, Box, FieldComparison, Severity, Verification } from '../types';

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');

export const DOC_LABELS: Record<string, string> = {
  fire_safety: 'Fire Safety NOC',
  audit_report: 'Audited Financials',
  land_document: 'Land / Title Deed',
  faculty_list: 'Faculty List',
  noc: 'University NOC',
  affidavit: 'Affidavit (e-Stamp)',
  building_plan: 'Building Plan',
  lab_photo: 'Lab Photos / Video',
  asset_register: 'Asset / Equipment Register',
  campus_boundary: 'Campus Boundary (GeoJSON)',
  other: 'Other',
};

export const STATUS_LABELS: Record<ApplicationStatus, string> = {
  draft: 'Draft',
  submitted: 'Submitted',
  under_review: 'Under review',
  deficiency_found: 'Deficiency notice',
  verified: 'Verified',
  approved: 'Approved',
  rejected: 'Rejected',
};

export const AI_LABELS: Record<AIRecommendation, { label: string; tone: string }> = {
  pending: { label: 'Not screened yet', tone: 'slate' },
  forward_for_approval: { label: 'Forward for decision', tone: 'emerald' },
  seek_clarification: { label: 'Seek clarification', tone: 'amber' },
  deficiency_suspected: { label: 'Deficiency suspected', tone: 'rose' },
  physical_inspection_suggested: { label: 'Inspection suggested', tone: 'sky' },
};

const TONES: Record<string, string> = {
  slate: 'bg-slate-100 text-slate-700 border-slate-200',
  emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  amber: 'bg-amber-50 text-amber-700 border-amber-200',
  rose: 'bg-rose-50 text-rose-700 border-rose-200',
  sky: 'bg-sky-50 text-sky-700 border-sky-200',
  indigo: 'bg-indigo-50 text-indigo-700 border-indigo-200',
};

export const Pill: React.FC<{ tone?: string; children: React.ReactNode; className?: string; title?: string }> = ({ tone = 'slate', children, className, title }) => (
  <span title={title} className={cx('inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] font-semibold whitespace-nowrap', TONES[tone], className)}>
    {children}
  </span>
);

export const StatusPill: React.FC<{ status: ApplicationStatus }> = ({ status }) => {
  const tone = { draft: 'slate', submitted: 'indigo', under_review: 'sky', deficiency_found: 'rose', verified: 'emerald', approved: 'emerald', rejected: 'rose' }[status];
  return <Pill tone={tone}>{STATUS_LABELS[status]}</Pill>;
};

export const AIPill: React.FC<{ rec?: AIRecommendation | null }> = ({ rec }) => {
  const meta = AI_LABELS[rec || 'pending'];
  return <Pill tone={meta.tone} title="AI advisory recommendation — not a decision">AI: {meta.label}</Pill>;
};

export const SeverityIcon: React.FC<{ severity: Severity; className?: string }> = ({ severity, className = 'w-4 h-4' }) =>
  severity === 'critical' ? <XCircle className={cx(className, 'text-rose-600')} /> : severity === 'warning' ? <AlertTriangle className={cx(className, 'text-amber-600')} /> : <Info className={cx(className, 'text-sky-600')} />;

export const SeverityPill: React.FC<{ severity: Severity }> = ({ severity }) => (
  <Pill tone={severity === 'critical' ? 'rose' : severity === 'warning' ? 'amber' : 'sky'}>
    <SeverityIcon severity={severity} className="w-3 h-3" />
    {severity}
  </Pill>
);

const VERIFICATION_TONE: Record<Verification['status'], string> = {
  verified: 'emerald', mismatch: 'rose', expired: 'rose', pending: 'amber', unavailable: 'amber', manual_review: 'sky',
};
const VERIFICATION_LABEL: Record<Verification['status'], string> = {
  verified: 'Verified', mismatch: 'Mismatch detected', expired: 'Expired', pending: 'Verification pending',
  unavailable: 'Source unavailable', manual_review: 'Manual review required',
};
export const VerificationPill: React.FC<{ status: Verification['status'] }> = ({ status }) => (
  <Pill tone={VERIFICATION_TONE[status]}>{VERIFICATION_LABEL[status]}</Pill>
);

export const METHOD_LABEL: Record<string, string> = {
  api: 'Issuing-authority registry', digital_signature: 'Signed QR (Ed25519)', qr_code: 'QR code', manual: 'Manual', portal: 'Portal',
};

export const Spinner: React.FC<{ className?: string }> = ({ className = 'w-5 h-5' }) => <Loader2 className={cx(className, 'animate-spin text-indigo-600')} />;

export const Card: React.FC<{ children: React.ReactNode; className?: string; title?: React.ReactNode; actions?: React.ReactNode }> = ({ children, className, title, actions }) => (
  <div className={cx('glass-panel rounded-2xl', className)}>
    {(title || actions) && (
      <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-slate-100">
        <h3 className="text-sm font-bold text-slate-900">{title}</h3>
        {actions}
      </div>
    )}
    <div className="p-5">{children}</div>
  </div>
);

export const Empty: React.FC<{ title: string; hint?: string; icon?: React.ReactNode }> = ({ title, hint, icon }) => (
  <div className="text-center py-10 text-slate-500">
    <div className="flex justify-center mb-2">{icon || <CheckCircle2 className="w-9 h-9 text-emerald-500" />}</div>
    <p className="font-semibold text-slate-800 text-sm">{title}</p>
    {hint && <p className="text-xs mt-1">{hint}</p>}
  </div>
);

export const Button: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'success' | 'ghost'; busy?: boolean }> = ({ variant = 'secondary', busy, className, children, disabled, ...rest }) => {
  const styles = {
    primary: 'bg-[#155a8a] hover:bg-[#10466d] text-white shadow-sm border-transparent',
    secondary: 'bg-white hover:bg-slate-50 text-slate-700 border-slate-200',
    danger: 'bg-rose-50 hover:bg-rose-100 text-rose-700 border-rose-300',
    success: 'bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border-emerald-300',
    ghost: 'bg-transparent hover:bg-slate-100 text-slate-600 border-transparent',
  }[variant];
  return (
    <button {...rest} disabled={disabled || busy} className={cx('inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-xl border text-xs font-semibold transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed', styles, className)}>
      {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
      {children}
    </button>
  );
};

export const Modal: React.FC<{ title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }> = ({ title, onClose, children, wide }) => {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} className={cx('bg-white rounded-2xl shadow-xl w-full max-h-[90vh] overflow-y-auto', wide ? 'max-w-4xl' : 'max-w-lg')} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <h2 className="font-bold text-slate-900 text-sm">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="p-1 rounded-lg hover:bg-slate-100 cursor-pointer"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
};

/** <img> for an authenticated API resource (fetched as a blob). */
export const AuthImage: React.FC<{ path: string; alt: string; className?: string; onLoad?: (e: React.SyntheticEvent<HTMLImageElement>) => void }> = ({ path, alt, className, onLoad }) => {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setSrc(null);
    setFailed(false);
    fetchBlobUrl(path)
      .then((u) => {
        url = u;
        if (!cancelled) setSrc(u);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);
  if (failed) return <div className="text-xs text-slate-500 p-6 text-center">Preview not available</div>;
  if (!src) return <div className="flex justify-center p-10"><Spinner /></div>;
  return <img src={src} alt={alt} className={className} onLoad={onLoad} />;
};

/** Document page with evidence boxes (coordinates normalised 0..1) drawn on top. */
export const EvidenceViewer: React.FC<{ path: string; boxes: (Box & { tone?: string })[]; alt: string; showBoxes?: boolean }> = ({ path, boxes, alt, showBoxes = true }) => (
  <div className="relative inline-block w-full bg-slate-100 rounded-xl overflow-hidden border border-slate-200">
    <AuthImage path={path} alt={alt} className="w-full h-auto block" />
    {showBoxes &&
      boxes.map((b, i) => (
        <div
          key={i}
          title={b.label}
          className={cx('absolute border-2 rounded-sm pointer-events-auto', b.tone === 'field' ? 'border-indigo-500 bg-indigo-400/10' : 'border-rose-600 bg-rose-500/15')}
          style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${Math.max(b.w * 100, 1)}%`, height: `${Math.max(b.h * 100, 0.8)}%` }}
        >
          {b.label && b.tone !== 'field' && (
            <span className="absolute left-full ml-1 top-0 text-[10px] font-bold px-1 rounded text-white whitespace-nowrap bg-rose-600 shadow">{b.label}</span>
          )}
        </div>
      ))}
  </div>
);

export const ComparisonTable: React.FC<{ rows: FieldComparison[] }> = ({ rows }) => (
  <ul className="space-y-1.5">
    {rows.map((r, i) => (
      <li key={i} className={cx('rounded-lg border px-2.5 py-1.5', r.match === false ? 'border-rose-200 bg-rose-50/50' : r.match === true ? 'border-emerald-100 bg-emerald-50/30' : 'border-slate-200')}>
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono text-[11px] text-slate-600">{r.field}</span>
          <span className={cx('inline-flex items-center gap-1 text-[11px] font-semibold', r.match === true ? 'text-emerald-700' : r.match === false ? 'text-rose-700' : 'text-slate-500')}>
            {r.match === true ? <CheckCircle2 className="w-3.5 h-3.5" /> : r.match === false ? <XCircle className="w-3.5 h-3.5" /> : <HelpCircle className="w-3.5 h-3.5" />}
            {r.match === true ? 'Match' : r.match === false ? 'Mismatch' : 'Not compared'}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 mt-1 text-[11px]">
          <div><span className="block text-[10px] text-slate-400">On document</span><span className="text-slate-800 break-words">{String(r.submitted ?? '—')}</span></div>
          <div><span className="block text-[10px] text-slate-400">Official source</span><span className="text-slate-800 break-words">{String(r.official ?? '—')}</span></div>
        </div>
        <p className="text-[10px] text-slate-500 mt-0.5">{r.reason}</p>
      </li>
    ))}
  </ul>
);

export const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—');
export const fmtDay = (s?: string | null) => (s ? new Date(s).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : '—');

export const AdvisoryNote: React.FC = () => (
  <p className="text-[11px] text-slate-500 flex items-start gap-1.5">
    <Info className="w-3.5 h-3.5 mt-px shrink-0" />
    AI findings are decision-support only. Tampering indicators are preliminary and must be verified; statutory scrutiny,
    inspection and the final decision rest with the competent AICTE authority.
  </p>
);

const RAG_META: Record<string, { tone: string; label: string }> = {
  green: { tone: 'emerald', label: 'Green · auto-pass' },
  amber: { tone: 'amber', label: 'Amber · clarification' },
  red: { tone: 'rose', label: 'Red · officer review' },
  not_applicable: { tone: 'slate', label: 'N/A' },
};

export const RagPill: React.FC<{ rag?: string | null; short?: boolean }> = ({ rag, short }) => {
  const m = RAG_META[rag || 'not_applicable'] || RAG_META.not_applicable;
  return <Pill tone={m.tone}>{short ? (rag || 'n/a').replace('_', ' ').toUpperCase() : m.label}</Pill>;
};

export const ragDot = (rag?: string | null) =>
  rag === 'red' ? 'bg-rose-500' : rag === 'amber' ? 'bg-amber-400' : rag === 'green' ? 'bg-emerald-500' : 'bg-slate-300';
