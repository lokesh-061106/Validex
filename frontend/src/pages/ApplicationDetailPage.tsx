import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft, Play, Gavel, Lock, Columns2, ShieldCheck, Network, Map as MapIcon, ScrollText, Bell, FileSearch, Hash,
  ChevronDown, ChevronUp, ShieldAlert, Stamp, CheckCircle2, XCircle,
} from 'lucide-react';
import { applicationsApi, auditApi, documentsApi, errorMessage, notificationsApi, triageApi, validationApi } from '../api/client';
import type {
  AuditEntry, Box, CustodyReport, DocumentDetail, GraphView, NotificationItem, RuleOutcome, TriageBundle, TriageDocument, TriageFinding,
} from '../types';
import {
  AIPill, AI_LABELS, AdvisoryNote, Button, Card, DOC_LABELS, Empty, EvidenceViewer, Modal, Pill, RagPill, Spinner, StatusPill, cx, fmtDate, fmtDay, ragDot,
} from '../components/ui';
import { DocumentReview } from '../components/DocumentReview';
import { useAuth } from '../context/AuthContext';

type Tab = 'review' | 'rules' | 'evidence' | 'graph' | 'spatial' | 'notices' | 'audit';
const APP_WIDE = '__application__';
const RAG_ORDER: Record<string, number> = { red: 0, amber: 1, green: 2, not_applicable: 3 };
const worst = (rags: (string | null | undefined)[]) => rags.filter(Boolean).sort((a, b) => RAG_ORDER[a!] - RAG_ORDER[b!])[0] || null;

/** Triage & Human Console (officers only): data from PostgreSQL, watermarked files from MinIO. */
export const ApplicationDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [bundle, setBundle] = useState<TriageBundle | null>(null);
  const [notices, setNotices] = useState<NotificationItem[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [tab, setTab] = useState<Tab>('review');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [deciding, setDeciding] = useState(false);
  const [clarifying, setClarifying] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    const [b, n, au] = await Promise.all([triageApi.bundle(id), notificationsApi.list(id), auditApi.getAppLogs(id)]);
    setBundle(b); setNotices(n); setAudit(au);
  }, [id]);

  useEffect(() => { load().catch((e) => setError(errorMessage(e))); }, [load]);

  const run = async (label: string, fn: () => Promise<any>) => {
    setBusy(label);
    setError('');
    try {
      await fn();
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy('');
    }
  };

  if (error && !bundle) return <Empty title="Could not load application" hint={error} />;
  if (!bundle) return <div className="flex justify-center p-16"><Spinner /></div>;

  const app = bundle.application;
  const canIssueFinalDecision = user?.role === 'approver';
  const decided = app.status === 'approved' || app.status === 'rejected';
  const hasBoundary = bundle.documents.some((d) => d.doc_type === 'campus_boundary');
  const tabs: { key: Tab; label: string; icon: React.ElementType; show?: boolean }[] = [
    { key: 'review', label: 'Split-screen review', icon: Columns2 },
    { key: 'rules', label: `Handbook rules (${bundle.rules.length})`, icon: ShieldCheck },
    { key: 'evidence', label: 'Document evidence', icon: FileSearch },
    { key: 'graph', label: 'Collusion graph', icon: Network },
    { key: 'spatial', label: 'Spatial', icon: MapIcon, show: hasBoundary },
    { key: 'notices', label: `Clarifications (${notices.length})`, icon: Bell },
    { key: 'audit', label: 'Audit trail', icon: ScrollText },
  ];

  return (
    <div className="space-y-5">
      <Link to="/applications" className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-800"><ArrowLeft className="w-3.5 h-3.5" />Triage queue</Link>

      <div className="glass-panel rounded-2xl p-6">
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-bold text-indigo-700 px-3 py-1 rounded-lg bg-indigo-50 border border-indigo-200">{app.application_number}</span>
              <StatusPill status={app.status} />
              <Pill>{app.category.replace('_', ' ').toUpperCase()}</Pill>
              <Pill tone="indigo" title="This console is never shown to institutions"><Lock className="w-3 h-3" />Officers only</Pill>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{app.institution_name}</h1>
            <p className="text-xs text-slate-500">AICTE ID {app.permanent_id || '—'} · intake {app.requested_intake ?? '—'} · AY {app.academic_year} · submitted {fmtDay(app.submitted_at)}</p>
            {app.overall_verdict && <p className="text-xs text-slate-700"><span className="font-semibold">Decision note:</span> {app.overall_verdict}</p>}
          </div>
          <div className="w-full lg:w-[26rem] space-y-2">
            <div className="grid grid-cols-3 gap-2">
              <Tile tone="emerald" label="Green rules" value={bundle.counts.green_rules} />
              <Tile tone="amber" label="Amber items" value={bundle.counts.amber} />
              <Tile tone="rose" label="Red unreviewed" value={`${bundle.counts.red_unreviewed}/${bundle.counts.red}`} />
            </div>
            <div className="p-3 rounded-xl bg-slate-50 border border-slate-200 space-y-1">
              <div className="flex items-center justify-between"><AIPill rec={app.ai_recommendation} /><span className="text-[11px] text-slate-500 font-mono" title="Risk score 0-100">risk {app.risk_score}</span></div>
              <p className="text-xs text-slate-700">{app.ai_summary || 'Not screened yet.'}</p>
            </div>
          </div>
        </div>
        {bundle.approval_blockers.length > 0 && !decided && (
          <p className="mt-3 text-xs text-rose-800 bg-rose-50 border border-rose-200 rounded-lg p-2 flex gap-2">
            <ShieldAlert className="w-4 h-4 shrink-0" />Approval blocked: {bundle.approval_blockers.join('; ')}.
          </p>
        )}
        <div className="mt-4 pt-4 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3">
          <AdvisoryNote />
          {!decided && app.status !== 'draft' && (
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => run('screen', () => validationApi.trigger(app.id))} busy={busy === 'screen'}><Play className="w-3.5 h-3.5" />Re-run screening</Button>
              <Button onClick={() => setClarifying(true)} disabled={bundle.clarification_candidates.length === 0} title="Send amber items to the institution, encrypted">
                <Lock className="w-3.5 h-3.5" />Request clarification ({bundle.clarification_candidates.length})
              </Button>
              {canIssueFinalDecision && <Button variant="primary" onClick={() => setDeciding(true)}><Gavel className="w-3.5 h-3.5" />Record final decision</Button>}
            </div>
          )}
        </div>
        {error && <p className="text-xs text-rose-600 mt-2" role="alert">{error}</p>}
      </div>

      <div className="flex border-b border-slate-200 gap-5 text-xs font-semibold overflow-x-auto" role="tablist">
        {tabs.filter((t) => t.show !== false).map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)} className={cx('pb-3 flex items-center gap-1.5 border-b-2 whitespace-nowrap cursor-pointer', tab === t.key ? 'border-indigo-600 text-indigo-700' : 'border-transparent text-slate-500 hover:text-slate-800')}>
            <t.icon className="w-4 h-4" />{t.label}
          </button>
        ))}
      </div>

      {tab === 'review' && <SplitReview bundle={bundle} onReviewed={load} />}
      {tab === 'rules' && <RulesTable rules={bundle.rules} />}
      {tab === 'evidence' && <DocumentReview documents={(app.documents || [])} isOfficial />}
      {tab === 'graph' && <GraphPanel appId={app.id} />}
      {tab === 'spatial' && <SpatialPanel docs={bundle.documents} />}
      {tab === 'notices' && <OfficerNotices notices={notices} />}
      {tab === 'audit' && <AuditList audit={audit} />}

      {deciding && <DecisionModal bundle={bundle} onClose={() => setDeciding(false)} onDone={() => { setDeciding(false); load(); }} />}
      {clarifying && <ClarificationModal bundle={bundle} onClose={() => setClarifying(false)} onDone={() => { setClarifying(false); setTab('notices'); load(); }} />}
    </div>
  );
};

const Tile: React.FC<{ tone: string; label: string; value: React.ReactNode }> = ({ tone, label, value }) => (
  <div className={cx('rounded-xl border p-2.5 text-center', tone === 'emerald' ? 'bg-emerald-50 border-emerald-200' : tone === 'amber' ? 'bg-amber-50 border-amber-200' : 'bg-rose-50 border-rose-200')}>
    <p className={cx('text-xl font-bold font-mono', tone === 'emerald' ? 'text-emerald-700' : tone === 'amber' ? 'text-amber-700' : 'text-rose-700')}>{value}</p>
    <p className="text-[10px] uppercase tracking-wider font-bold text-slate-500">{label}</p>
  </div>
);

// ------------------------------------------------------------------ split-screen review

const SplitReview: React.FC<{ bundle: TriageBundle; onReviewed: () => void }> = ({ bundle, onReviewed }) => {
  const docs = bundle.documents;
  const ragFor = useCallback((docId: string, docType: string) => worst([
    ...bundle.findings.filter((f) => f.document_id === docId).map((f) => f.rag),
    ...bundle.rules.filter((r) => r.doc_type === docType).map((r) => r.rag),
  ]), [bundle]);
  const firstFlagged = docs.find((d) => ['red', 'amber'].includes(ragFor(d.id, d.doc_type) || ''));
  const [selected, setSelected] = useState<string>(firstFlagged?.id || docs[0]?.id || APP_WIDE);
  const doc = docs.find((d) => d.id === selected) || null;

  const findings = doc ? bundle.findings.filter((f) => f.document_id === doc.id) : bundle.findings.filter((f) => !f.document_id && !f.rule_code);
  const rules = doc ? bundle.rules.filter((r) => r.doc_type === doc.doc_type) : bundle.rules.filter((r) => !r.doc_type);
  const ruleFindings = bundle.findings.filter((f) => f.rule_code && rules.some((r) => r.rule_code === f.rule_code));
  const appWideRag = worst([...bundle.findings.filter((f) => !f.document_id).map((f) => f.rag), ...bundle.rules.filter((r) => !r.doc_type).map((r) => r.rag)]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {docs.map((d) => (
          <button key={d.id} onClick={() => setSelected(d.id)} className={cx('px-3 py-1.5 rounded-lg border text-xs font-semibold flex items-center gap-1.5 cursor-pointer', d.id === selected ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50')}>
            <span className={cx('w-2 h-2 rounded-full', ragDot(ragFor(d.id, d.doc_type)))} />{DOC_LABELS[d.doc_type] || d.doc_type}
          </button>
        ))}
        <button onClick={() => setSelected(APP_WIDE)} className={cx('px-3 py-1.5 rounded-lg border text-xs font-semibold flex items-center gap-1.5 cursor-pointer', selected === APP_WIDE ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50')}>
          <span className={cx('w-2 h-2 rounded-full', ragDot(appWideRag))} />Application-wide
        </button>
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 xl:col-span-7">
          {doc ? <DocumentPane doc={doc} /> : (
            <Card title="Application-wide checks">
              <p className="text-xs text-slate-600">Cross-document and cross-institution checks: deterministic ratios, the collusion graph (shared PAN / biometric / equipment) and records consistency. They are listed on the right with the handbook clause each applies.</p>
            </Card>
          )}
        </div>
        <div className="col-span-12 xl:col-span-5 space-y-3 xl:max-h-[78vh] xl:overflow-y-auto pr-1">
          <h3 className="text-[11px] uppercase font-bold tracking-wider text-slate-500">Handbook clauses ({rules.length})</h3>
          {rules.length === 0 && <p className="text-xs text-slate-500">No handbook rule targets this document directly.</p>}
          {[...rules].sort((a, b) => RAG_ORDER[a.rag] - RAG_ORDER[b.rag]).map((r) => (
            <RuleCard key={r.rule_code} rule={r} finding={ruleFindings.find((f) => f.rule_code === r.rule_code)} appId={bundle.application.id} onReviewed={onReviewed} />
          ))}
          <h3 className="text-[11px] uppercase font-bold tracking-wider text-slate-500 pt-2">Forensic & verification findings ({findings.length})</h3>
          {findings.length === 0 && <p className="text-xs text-slate-500">No forensic, verification or graph findings.</p>}
          {[...findings].sort((a, b) => RAG_ORDER[a.rag || 'green'] - RAG_ORDER[b.rag || 'green']).map((f) => (
            <FindingCard key={f.id} f={f} appId={bundle.application.id} onReviewed={onReviewed} />
          ))}
        </div>
      </div>
    </div>
  );
};

const DocumentPane: React.FC<{ doc: TriageDocument }> = ({ doc }) => {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [page, setPage] = useState(0);
  const [custody, setCustody] = useState<CustodyReport | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    setDetail(null); setCustody(null); setPage(0);
    documentsApi.get(doc.id).then(setDetail);
  }, [doc.id]);

  const boxes = useMemo(() => {
    const out: (Box & { tone?: string })[] = [];
    (detail?.extracted_data?.forensics?.indicators || []).forEach((i: any) =>
      (i.boxes || []).forEach((b: Box) => (b.page ?? 0) === page && out.push({ ...b, label: b.label || i.method })));
    return out;
  }, [detail, page]);

  const verify = async () => {
    setChecking(true);
    try { setCustody(await documentsApi.custody(doc.id)); } finally { setChecking(false); }
  };

  const viewable = !doc.mime_type.startsWith('video/') && doc.doc_type !== 'campus_boundary';
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-slate-800 truncate">{doc.filename} <span className="text-slate-400 font-normal">· {doc.page_count} page(s) · {fmtDate(doc.uploaded_at)}</span></p>
        {doc.page_count > 1 && (
          <div className="flex items-center gap-1 text-xs">
            <Button variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>‹</Button>
            <span className="text-slate-500">page {page + 1}/{doc.page_count}</span>
            <Button variant="ghost" disabled={page >= doc.page_count - 1} onClick={() => setPage(page + 1)}>›</Button>
          </div>
        )}
      </div>
      {viewable ? <EvidenceViewer path={documentsApi.pageUrl(doc.id, page)} boxes={boxes} alt={doc.filename} /> : (
        <Card><p className="text-xs text-slate-600">{doc.doc_type === 'campus_boundary' ? 'GeoJSON boundary: see the Spatial tab for the map.' : 'Video: see Document evidence for the analysed keyframe.'}</p></Card>
      )}
      <div className="p-3 rounded-xl border border-slate-200 bg-white text-[11px] space-y-1">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 font-semibold text-slate-800"><Stamp className="w-3.5 h-3.5 text-indigo-600" />Chain of custody</span>
          <Button variant="ghost" busy={checking} onClick={verify}>Verify now</Button>
        </div>
        <p className="font-mono text-slate-600 break-all">{doc.watermark || 'No custody watermark (stored before watermarking)'}</p>
        <p className="font-mono text-slate-400 break-all" title="SHA-256 of the file as received">original {doc.original_sha256?.slice(0, 24)}… · stored {doc.stored_sha256?.slice(0, 24)}…</p>
        {custody && (
          <div className="pt-1">
            <p className={cx('font-semibold flex items-center gap-1', custody.intact ? 'text-emerald-700' : 'text-rose-700')}>
              {custody.intact ? <CheckCircle2 className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}{custody.intact ? 'Intact: stored object matches the sealed original' : 'Custody broken: stored object was altered'}
            </p>
            <p className="text-slate-500">{Object.entries(custody.checks).map(([k, v]) => `${v ? '✓' : '✗'} ${k.replace(/_/g, ' ')}`).join(' · ')}</p>
          </div>
        )}
      </div>
    </div>
  );
};

const RuleCard: React.FC<{ rule: RuleOutcome; finding?: TriageFinding; appId: string; onReviewed: () => void }> = ({ rule, finding, appId, onReviewed }) => {
  const [open, setOpen] = useState(rule.rag !== 'green');
  return (
    <div className={cx('p-3 rounded-xl border bg-white', rule.rag === 'red' ? 'border-rose-200' : rule.rag === 'amber' ? 'border-amber-200' : 'border-slate-200')}>
      <button className="w-full text-left cursor-pointer" onClick={() => setOpen(!open)}>
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-semibold text-slate-900">{rule.title}</p>
          <RagPill rag={rule.rag} short />
        </div>
        <p className="text-[11px] text-slate-600 mt-0.5">{rule.message}</p>
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {rule.clause && (
            <blockquote className="text-[11px] text-slate-700 bg-indigo-50/60 border-l-2 border-indigo-400 rounded-r-lg px-2.5 py-1.5">
              <span className="block font-mono text-[10px] text-indigo-700 font-semibold">{rule.rule_code} v{rule.rule_version} · {rule.handbook_reference}</span>
              {rule.clause}
            </blockquote>
          )}
          {rule.trace && rule.trace.length > 0 && (
            <pre className="text-[10px] font-mono bg-slate-900 text-slate-100 rounded-lg p-2 whitespace-pre-wrap">{rule.trace.join('\n')}</pre>
          )}
          {finding && finding.rag === 'red' && <ReviewControls f={finding} appId={appId} onReviewed={onReviewed} />}
        </div>
      )}
    </div>
  );
};

const ACTOR: Record<string, string> = { institution: 'institution must supply', officer: 'officer to check', system: 'system will retry' };

const FindingCard: React.FC<{ f: TriageFinding; appId: string; onReviewed: () => void }> = ({ f, appId, onReviewed }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className={cx('p-3 rounded-xl border bg-white', f.rag === 'red' ? 'border-rose-200' : f.rag === 'amber' ? 'border-amber-200' : 'border-slate-200')}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold text-slate-900">{f.finding}</p>
        <RagPill rag={f.rag} short />
      </div>
      <div className="flex flex-wrap items-center gap-1.5 mt-1">
        <Pill>{f.check_type}</Pill>
        {f.rag === 'amber' && f.actionable_by && <Pill tone="amber">{ACTOR[f.actionable_by]}</Pill>}
        <span className="text-[10px] text-slate-500">confidence {Math.round(f.confidence * 100)}%</span>
      </div>
      {f.evidence && (
        <>
          <button onClick={() => setOpen(!open)} className="text-[11px] font-semibold text-slate-500 hover:text-slate-800 mt-1.5 inline-flex items-center gap-1 cursor-pointer">
            {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />} Evidence
          </button>
          {open && (
            <div className="mt-1 text-[11px] text-slate-600 bg-slate-50 rounded-lg p-2 space-y-1">
              <p className="whitespace-pre-wrap">{f.evidence}</p>
              {f.details?.graph?.cypher && <pre className="font-mono text-[10px] bg-slate-900 text-slate-100 rounded p-2 whitespace-pre-wrap">{f.details.graph.cypher}</pre>}
            </div>
          )}
        </>
      )}
      {f.rag === 'red' && <div className="mt-2"><ReviewControls f={f} appId={appId} onReviewed={onReviewed} /></div>}
    </div>
  );
};

/** RED items need a human: confirm the anomaly, or override it with a recorded reason. */
const ReviewControls: React.FC<{ f: TriageFinding; appId: string; onReviewed: () => void }> = ({ f, appId, onReviewed }) => {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (f.review) {
    return (
      <p className={cx('text-[11px] rounded-lg px-2 py-1.5 border', f.review.decision === 'confirmed' ? 'bg-rose-50 border-rose-200 text-rose-800' : 'bg-emerald-50 border-emerald-200 text-emerald-800')}>
        <span className="font-semibold">{f.review.decision === 'confirmed' ? 'Confirmed as genuine anomaly' : 'Overridden'}</span> · {fmtDate(f.review.at)} — {f.review.reason}
      </p>
    );
  }
  const act = async (decision: 'confirmed' | 'overridden') => {
    setBusy(true);
    setError('');
    try {
      await triageApi.review(appId, f.id, decision, reason.trim());
      onReviewed();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };
  return (
    <div className="space-y-1.5">
      <textarea rows={2} className="input text-xs" placeholder="Reason (required, recorded in the audit ledger)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Review reason" />
      <div className="flex gap-2 justify-end">
        <Button variant="danger" busy={busy} disabled={reason.trim().length < 10} onClick={() => act('confirmed')}>Confirm anomaly</Button>
        <Button busy={busy} disabled={reason.trim().length < 10} onClick={() => act('overridden')}>Override</Button>
      </div>
      {error && <p className="text-[11px] text-rose-600" role="alert">{error}</p>}
    </div>
  );
};

// ------------------------------------------------------------------ rules, graph, spatial, notices, audit

const RulesTable: React.FC<{ rules: RuleOutcome[] }> = ({ rules }) => (
  <Card title="Deterministic rule engine — AICTE Approval Process Handbook bounds (no generative AI)">
    <div className="overflow-x-auto" role="region" aria-label="Compliance findings table" tabIndex={0}>
    <table className="w-full min-w-[540px] text-xs">
      <thead><tr className="text-left text-slate-500 border-b border-slate-100"><th className="py-2">Rule</th><th>RAG</th><th>Expected</th><th>Found</th><th>Calculation</th></tr></thead>
      <tbody>
        {[...rules].sort((a, b) => RAG_ORDER[a.rag] - RAG_ORDER[b.rag]).map((r) => (
          <tr key={r.rule_code} className="border-b border-slate-50 align-top">
            <td className="py-2 pr-2 w-1/3">
              <p className="font-semibold text-slate-800">{r.title}</p>
              <p className="text-[10px] font-mono text-slate-400">{r.rule_code} v{r.rule_version} · {r.category}</p>
              {r.clause && <p className="text-[10px] text-slate-500 mt-0.5">{r.clause}</p>}
            </td>
            <td className="pr-2"><RagPill rag={r.rag} short /></td>
            <td className="pr-2 font-mono">{r.expected ?? '—'}</td>
            <td className="pr-2 font-mono">{r.actual ?? '—'}</td>
            <td className="text-slate-600"><p>{r.message}</p>{r.trace && r.trace.length > 0 && <p className="font-mono text-[10px] text-slate-500 mt-0.5">{r.trace.join(' ; ')}</p>}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  </Card>
);

const NODE_COLOR: Record<string, string> = { institution: '#4f46e5', faculty: '#e11d48', biometric: '#d97706', equipment: '#0891b2' };

const GraphPanel: React.FC<{ appId: string }> = ({ appId }) => {
  const [g, setG] = useState<GraphView | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { triageApi.graph(appId).then(setG).catch((e) => setError(errorMessage(e))); }, [appId]);
  if (error) return <Empty title="Graph unavailable" hint={error} />;
  if (!g) return <div className="flex justify-center p-10"><Spinner /></div>;
  if (g.links.length === 0) return <Empty title="No shared identities or assets" hint={`No faculty PAN, biometric or equipment serial of this institution appears elsewhere (backend: ${g.backend}).`} />;

  const W = 760, H = 460, cx0 = W / 2, cy0 = H / 2;
  const focus = g.nodes.find((n) => n.focus)!;
  const shared = g.nodes.filter((n) => n.type !== 'institution');
  const others = g.nodes.filter((n) => n.type === 'institution' && !n.focus);
  const pos: Record<string, [number, number]> = { [focus.id]: [W * 0.17, cy0] };
  shared.forEach((n, i) => { pos[n.id] = [cx0, 30 + (i + 0.5) * ((H - 60) / shared.length)]; });
  others.forEach((n, i) => { pos[n.id] = [W * 0.83, 60 + (i + 0.5) * ((H - 120) / others.length)]; });

  return (
    <div className="grid grid-cols-12 gap-4">
      <Card className="col-span-12 lg:col-span-8" title={`Collusion graph — backend: ${g.backend === 'neo4j' ? 'Neo4j' : 'in-process (Neo4j not configured)'}`}>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Shared identities and assets between institutions">
          {g.edges.map((e, i) => {
            const [x1, y1] = pos[e.from] || [0, 0]; const [x2, y2] = pos[e.to] || [0, 0];
            return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#94a3b8" strokeWidth={1.2} />;
          })}
          {g.nodes.map((n) => {
            const [x, y] = pos[n.id] || [0, 0];
            const inst = n.type === 'institution';
            return (
              <g key={n.id}>
                <circle cx={x} cy={y} r={inst ? 16 : 7} fill={NODE_COLOR[n.type] || '#64748b'} stroke="#fff" strokeWidth={2} />
                <text x={inst ? x : x + 11} y={inst ? y + 32 : y + 4} fontSize={inst ? 12 : 10} textAnchor={inst ? 'middle' : 'start'} fill="#0f172a" fontWeight={inst ? 700 : 500}>
                  {n.label.length > 30 ? `${n.label.slice(0, 28)}…` : n.label}
                </text>
              </g>
            );
          })}
        </svg>
        <div className="flex gap-3 text-[11px] text-slate-600 mt-1">
          {Object.entries(NODE_COLOR).map(([k, c]) => <span key={k} className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{k}</span>)}
        </div>
      </Card>
      <div className="col-span-12 lg:col-span-4 space-y-2 max-h-[70vh] overflow-y-auto">
        {g.links.map((l, i) => (
          <div key={i} className="p-3 rounded-xl border border-rose-200 bg-white text-xs">
            <p className="font-semibold text-slate-900">{l.finding}</p>
            <p className="text-[11px] text-slate-600 mt-1">{l.evidence}</p>
            {l.cypher && <pre className="mt-1.5 font-mono text-[10px] bg-slate-900 text-slate-100 rounded p-2 whitespace-pre-wrap">{l.cypher}</pre>}
          </div>
        ))}
        <p className="text-[10px] text-slate-400">Identifiers are keyed with HMAC; PANs are shown masked. Biometric references are template IDs, not images.</p>
      </div>
    </div>
  );
};

const SpatialPanel: React.FC<{ docs: TriageDocument[] }> = ({ docs }) => {
  const boundary = docs.find((d) => d.doc_type === 'campus_boundary');
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  useEffect(() => { if (boundary) documentsApi.get(boundary.id).then(setDetail); }, [boundary]);
  if (!boundary) return <Empty title="No campus boundary submitted" />;
  if (!detail) return <div className="flex justify-center p-10"><Spinner /></div>;
  const s = detail.extracted_data?.spatial || {};
  const geom = s.geometry || { campus: [], buildings: [], observed: [] };
  const all: number[][] = [...(geom.campus || []), ...(geom.buildings || []), ...(geom.observed || [])].flat();
  if (all.length === 0) return <Empty title="Boundary could not be analysed" hint={(s.issues || []).map((i: any) => i.message).join('; ')} />;
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const k = Math.cos(((minY + maxY) / 2) * Math.PI / 180); // equirectangular: shrink longitude
  const span = Math.max((maxX - minX) * k, maxY - minY) || 1;
  const W = 520, pad = 20;
  const pt = (p: number[]) => `${pad + ((p[0] - minX) * k / span) * (W - 2 * pad)},${pad + ((maxY - p[1]) / span) * (W - 2 * pad)}`;
  const poly = (ring: number[][]) => ring.map(pt).join(' ');

  return (
    <div className="grid grid-cols-12 gap-4">
      <Card className="col-span-12 lg:col-span-7" title="Campus boundary vs footprints">
        <svg viewBox={`0 0 ${W} ${W}`} className="w-full max-w-xl mx-auto bg-slate-50 rounded-xl" role="img" aria-label="Campus boundary map">
          {(geom.campus || []).map((r: number[][], i: number) => <polygon key={`c${i}`} points={poly(r)} fill="#e0e7ff" stroke="#4f46e5" strokeWidth={2} />)}
          {(geom.observed || []).map((r: number[][], i: number) => <polygon key={`o${i}`} points={poly(r)} fill="#94a3b8" fillOpacity={0.55} stroke="#475569" strokeWidth={1} />)}
          {(geom.buildings || []).map((r: number[][], i: number) => <polygon key={`b${i}`} points={poly(r)} fill="none" stroke="#e11d48" strokeWidth={1.6} strokeDasharray="5 3" />)}
        </svg>
        <div className="flex gap-4 text-[11px] text-slate-600 mt-2">
          <span className="flex items-center gap-1"><span className="w-3 h-3 bg-indigo-100 border-2 border-indigo-600" />surveyed boundary</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 border-2 border-dashed border-rose-600" />declared building</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 bg-slate-400" />observed footprint ({s.observed_source})</span>
        </div>
      </Card>
      <div className="col-span-12 lg:col-span-5 space-y-3">
        <Card title="Measurements (geodesic)">
          <dl className="text-xs grid grid-cols-2 gap-y-1.5">
            <dt className="text-slate-500">Boundary area</dt><dd className="font-mono">{s.boundary_area_sqm?.toLocaleString()} m² ({s.boundary_area_acres} acres)</dd>
            <dt className="text-slate-500">Declared footprint</dt><dd className="font-mono">{s.declared_footprint_sqm?.toLocaleString() ?? '—'} m²</dd>
            <dt className="text-slate-500">Observed footprint</dt><dd className="font-mono">{s.observed_footprint_sqm?.toLocaleString() ?? '—'} m² ({s.observed_footprints} bldg)</dd>
          </dl>
          <ul className="mt-2 text-xs space-y-1">
            {(s.declared_buildings || []).map((b: any) => (
              <li key={b.name} className="flex justify-between"><span>{b.name}</span><span className={b.inside_campus ? 'text-emerald-700' : 'text-rose-700 font-semibold'}>{b.area_sqm} m² · {b.inside_campus ? 'inside' : 'OUTSIDE boundary'}</span></li>
            ))}
          </ul>
        </Card>
        {(s.issues || []).map((i: any, idx: number) => (
          <div key={idx} className={cx('p-3 rounded-xl border text-xs bg-white', i.rag === 'red' ? 'border-rose-200' : 'border-amber-200')}>
            <div className="flex justify-between gap-2"><p className="font-semibold">{i.message}</p><RagPill rag={i.rag} short /></div>
            {i.evidence && <p className="text-[11px] text-slate-600 mt-1">{i.evidence}</p>}
          </div>
        ))}
        <p className="text-[10px] text-slate-400">Observed footprints come from a pluggable GIS provider (simulated unless an approved provider is configured). This compares vector footprints, not satellite imagery.</p>
      </div>
    </div>
  );
};

const OfficerNotices: React.FC<{ notices: NotificationItem[] }> = ({ notices }) =>
  notices.length === 0 ? <Empty title="No clarification requests sent" /> : (
    <div className="space-y-3">
      {notices.map((n) => (
        <Card key={n.id} title={<span className="flex items-center gap-2"><Lock className="w-4 h-4 text-indigo-600" />{n.subject}</span>} actions={<Pill tone={n.status === 'sent' ? 'amber' : 'sky'}>{n.status}</Pill>}>
          <p className="text-[11px] text-slate-500">Sent {fmtDate(n.created_at)} · due {fmtDay(n.due_date)} · {n.items.length} item(s): {n.items.map((i) => i.rule_code || DOC_LABELS[i.doc_type || ''] || i.doc_type).filter(Boolean).join(', ')}</p>
          <p className="text-[11px] text-slate-500 mt-1">Content is encrypted to the institution ({n.encrypted_payload?.alg}); only its browser can read it. Plaintext SHA-256 in the ledger: <span className="font-mono">{n.payload_sha256?.slice(0, 16)}…</span></p>
        </Card>
      ))}
    </div>
  );

const AuditList: React.FC<{ audit: AuditEntry[] }> = ({ audit }) => (
  <Card title="Audit trail (hash-chained, append-only)">
    <ul className="divide-y divide-slate-100">
      {audit.map((e) => (
        <li key={e.id} className="py-2 text-xs flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p><span className="font-semibold text-slate-800">{e.action.replace(/_/g, ' ')}</span> <span className="text-slate-500">· {e.actor}{e.actor_role ? ` (${e.actor_role})` : ''}</span></p>
            <p className="text-[11px] text-slate-500 truncate">{summarize(e.details)}</p>
          </div>
          <div className="text-right shrink-0">
            <p className="text-[11px] text-slate-400">{fmtDate(e.created_at)}</p>
            {e.entry_hash && <p className="text-[10px] font-mono text-slate-400 flex items-center gap-0.5 justify-end" title={e.entry_hash}><Hash className="w-3 h-3" />{e.entry_hash.slice(0, 10)}</p>}
          </div>
        </li>
      ))}
    </ul>
  </Card>
);

const summarize = (d: Record<string, any>) =>
  Object.entries(d || {}).filter(([, v]) => typeof v !== 'object').slice(0, 5).map(([k, v]) => `${k}: ${v}`).join(' · ');

// ------------------------------------------------------------------ modals

const DecisionModal: React.FC<{ bundle: TriageBundle; onClose: () => void; onDone: () => void }> = ({ bundle, onClose, onDone }) => {
  const app = bundle.application;
  const blocked = bundle.approval_blockers.length > 0;
  const [status, setStatus] = useState(blocked ? 'under_review' : 'approved');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const aiAdverse = app.ai_recommendation === 'deficiency_suspected' || app.ai_recommendation === 'physical_inspection_suggested';
  const override = (status === 'approved' && aiAdverse) || (status === 'rejected' && app.ai_recommendation === 'forward_for_approval');
  const needsReason = status === 'rejected' || override;
  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      await applicationsApi.decide(app.id, status, notes || undefined);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="Record official decision" onClose={onClose}>
      <div className="space-y-3">
        <p className="text-xs text-slate-600">The advisory recommendation is <span className="font-semibold">{AI_LABELS[app.ai_recommendation || 'pending'].label}</span>. You decide; your decision and reasons are recorded in the audit ledger.</p>
        {blocked && <p className="text-xs text-rose-800 bg-rose-50 border border-rose-200 rounded-lg p-2">Approve / verify is unavailable: {bundle.approval_blockers.join('; ')}.</p>}
        <div>
          <label className="label" htmlFor="dec">Decision</label>
          <select id="dec" className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="approved" disabled={blocked}>Approve</option>
            <option value="verified" disabled={blocked}>Mark verified (forward to approving authority)</option>
            <option value="under_review">Keep under review / request hearing</option>
            <option value="rejected">Reject</option>
          </select>
        </div>
        {override && <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2">This differs from the advisory recommendation. Record why.</p>}
        <div>
          <label className="label" htmlFor="notes">Reasons {needsReason && <span className="text-rose-600">(required)</span>}</label>
          <textarea id="notes" rows={4} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
        {error && <p className="text-xs text-rose-600" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={busy} disabled={needsReason && notes.trim().length < 10} onClick={submit}>Record decision</Button>
        </div>
      </div>
    </Modal>
  );
};

/** Amber items only. Sent encrypted; never includes red anomalies or forensic reasons. */
const ClarificationModal: React.FC<{ bundle: TriageBundle; onClose: () => void; onDone: () => void }> = ({ bundle, onClose, onDone }) => {
  const candidates = bundle.findings.filter((f) => bundle.clarification_candidates.includes(f.id));
  const [selected, setSelected] = useState<Set<string>>(new Set(candidates.map((f) => f.id)));
  const [notes, setNotes] = useState('Please supply the items listed below and resubmit.');
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const submit = async () => {
    setBusy(true);
    try {
      await applicationsApi.clarificationRequest(bundle.application.id, notes, days, [...selected]);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };
  return (
    <Modal title="Request clarification (encrypted)" onClose={onClose} wide>
      <div className="space-y-3">
        <p className="text-xs text-slate-600">Only amber items the institution can fix (missing, expired or unreadable documents) can be sent. The request is encrypted to the institution's browser key and carries no forensic reasons; red items stay in this console.</p>
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {candidates.map((f) => (
            <label key={f.id} className="flex items-start gap-2 p-3 rounded-xl border border-amber-200 bg-white text-xs cursor-pointer">
              <input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} className="mt-0.5" />
              <span><span className="font-semibold text-slate-900">{f.finding}</span>{f.fix_hint && <span className="block text-slate-600 mt-0.5">{f.fix_hint}</span>}</span>
            </label>
          ))}
        </div>
        <div className="grid grid-cols-4 gap-3">
          <div className="col-span-3"><label className="label" htmlFor="cnotes">Note to institution</label><textarea id="cnotes" rows={2} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
          <div><label className="label" htmlFor="cdays">Days to respond</label><input id="cdays" type="number" min={1} max={60} className="input" value={days} onChange={(e) => setDays(Number(e.target.value))} /></div>
        </div>
        {error && <p className="text-xs text-rose-600" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={busy} disabled={selected.size === 0 || notes.trim().length < 5} onClick={submit}><Lock className="w-3.5 h-3.5" />Encrypt & send ({selected.size})</Button>
        </div>
      </div>
    </Modal>
  );
};
