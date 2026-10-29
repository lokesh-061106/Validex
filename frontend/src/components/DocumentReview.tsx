import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FileText, Image as ImageIcon, Layers, ScanSearch, ChevronLeft, ChevronRight, RefreshCw, Copy, History } from 'lucide-react';
import { documentsApi, verificationApi } from '../api/client';
import type { Box, DocumentDetail, DocumentItem } from '../types';
import { AuthImage, Button, Card, ComparisonTable, DOC_LABELS, EvidenceViewer, METHOD_LABEL, Pill, Spinner, VerificationPill, cx, fmtDate } from './ui';

const HIDDEN_KEYS = new Set([
  'classification', 'ocr', 'forensics', 'raw_text_snippet', 'field_locations', 'duplicates', 'infrastructure', 'detected_dates', 'pincodes',
  'has_evidence_image', 'has_ela_heatmap', 'has_annotated_image', 'forgery_score', 'forgery_level', 'ocr_confidence', 'processing_seconds',
]);

const statusDot = (d: DocumentItem) =>
  d.status === 'flagged' ? 'bg-rose-500' : d.status === 'validated' ? 'bg-emerald-500' : d.status === 'failed' ? 'bg-slate-400' : 'bg-amber-400';

export const DocumentReview: React.FC<{ documents: DocumentItem[]; initialId?: string | null; isOfficial: boolean }> = ({ documents, initialId, isOfficial }) => {
  const current = useMemo(() => documents.filter((d) => d.is_current), [documents]);
  const [selectedId, setSelectedId] = useState<string | null>(initialId || current[0]?.id || null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [view, setView] = useState<'page' | 'evidence' | 'ela' | 'annotated'>('page');
  const [showFields, setShowFields] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (initialId) setSelectedId(initialId); }, [initialId]);

  const load = useCallback(async (id: string) => {
    setDetail(null);
    const d = await documentsApi.get(id);
    setDetail(d);
    setView(d.doc_type === 'lab_photo' && d.extracted_data?.has_annotated_image ? 'annotated' : 'page');
  }, []);

  useEffect(() => { if (selectedId) load(selectedId); }, [selectedId, load]);

  const move = useCallback((delta: number) => {
    const idx = current.findIndex((d) => d.id === selectedId);
    const next = current[(idx + delta + current.length) % current.length];
    if (next) setSelectedId(next.id);
  }, [current, selectedId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'INPUT' || (e.target as HTMLElement)?.tagName === 'TEXTAREA') return;
      if (e.key === 'ArrowRight' || e.key === 'j') move(1);
      if (e.key === 'ArrowLeft' || e.key === 'k') move(-1);
      if (e.key === 'f') setShowFields((v) => !v);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [move]);

  const data = detail?.extracted_data || {};
  const forensics = data.forensics || {};
  const boxes: (Box & { tone?: string })[] = useMemo(() => {
    const out: (Box & { tone?: string })[] = [];
    (forensics.indicators || []).forEach((i: any) => (i.boxes || []).forEach((b: Box) => (b.page ?? 0) === 0 && out.push({ ...b, label: b.label || i.method })));
    if (showFields) {
      Object.entries(data.field_locations || {}).forEach(([k, loc]: [string, any]) => {
        if (loc && 'x' in loc && (loc.page ?? 0) === 0) out.push({ ...loc, label: k, tone: 'field' });
      });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail, showFields]);

  const rerunVerification = async () => {
    if (!detail) return;
    setBusy(true);
    try {
      await verificationApi.trigger(detail.id);
      await load(detail.id);
    } finally {
      setBusy(false);
    }
  };

  if (current.length === 0) return <p className="text-sm text-slate-500">No documents uploaded.</p>;

  const fields = Object.entries(data).filter(([k, v]) => !HIDDEN_KEYS.has(k) && !k.endsWith('_iso') && !k.endsWith('_ocr_raw') && (typeof v !== 'object' || v === null));
  const isImage = detail?.mime_type.startsWith('image/');
  const isVideo = detail?.mime_type.startsWith('video/');

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-2 space-y-1">
        {current.map((d) => (
          <button key={d.id} onClick={() => setSelectedId(d.id)} className={cx('w-full text-left px-3 py-2 rounded-xl border text-xs cursor-pointer', d.id === selectedId ? 'bg-indigo-50 border-indigo-300' : 'bg-white border-slate-200 hover:bg-slate-50')}>
            <span className="flex items-center gap-2 font-semibold text-slate-800"><span className={cx('w-2 h-2 rounded-full shrink-0', statusDot(d))} />{DOC_LABELS[d.doc_type]}</span>
            <span className="block text-[10px] text-slate-500 truncate mt-0.5">{d.original_filename}</span>
          </button>
        ))}
        <p className="text-[10px] text-slate-400 pt-2">Keys: ←/→ document · F field boxes</p>
      </div>

      <div className="col-span-12 lg:col-span-6">
        {!detail ? (
          <div className="flex justify-center p-16"><Spinner /></div>
        ) : (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex gap-1">
                {!isVideo && <Button variant={view === 'page' ? 'primary' : 'secondary'} onClick={() => setView('page')}><FileText className="w-3.5 h-3.5" />Document</Button>}
                {data.has_evidence_image && <Button variant={view === 'evidence' ? 'primary' : 'secondary'} onClick={() => setView('evidence')}><ScanSearch className="w-3.5 h-3.5" />Tamper evidence</Button>}
                {data.has_ela_heatmap && <Button variant={view === 'ela' ? 'primary' : 'secondary'} onClick={() => setView('ela')}><Layers className="w-3.5 h-3.5" />ELA heatmap</Button>}
                {data.has_annotated_image && <Button variant={view === 'annotated' ? 'primary' : 'secondary'} onClick={() => setView('annotated')}><ImageIcon className="w-3.5 h-3.5" />CV detections</Button>}
              </div>
              <div className="flex items-center gap-1">
                <Button variant="ghost" onClick={() => move(-1)} aria-label="Previous document"><ChevronLeft className="w-4 h-4" /></Button>
                <Button variant="ghost" onClick={() => move(1)} aria-label="Next document"><ChevronRight className="w-4 h-4" /></Button>
              </div>
            </div>
            {view === 'page' && !isVideo && (
              <EvidenceViewer path={documentsApi.pageUrl(detail.id, 0)} boxes={isImage ? boxes.filter((b) => b.tone !== 'field') : boxes} alt={detail.original_filename} />
            )}
            {view !== 'page' && <AuthImage path={documentsApi.evidenceUrl(detail.id, view)} alt={`${view} for ${detail.original_filename}`} className="w-full rounded-xl border border-slate-200" />}
            {isVideo && view === 'page' && <p className="text-xs text-slate-500">Video walkthrough: see CV detections for the analysed keyframe.</p>}
            <div className="flex items-center gap-3 text-[11px] text-slate-500">
              <span className="flex items-center gap-1"><span className="w-3 h-3 border-2 border-rose-600 rounded-sm" />tampering indicator</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 border-2 border-indigo-500 rounded-sm" />extracted field</span>
              <span>OCR: {data.ocr?.engine || '—'} ({Math.round((data.ocr?.confidence || 0) * 100)}%)</span>
            </div>
          </div>
        )}
      </div>

      <div className="col-span-12 lg:col-span-4 space-y-3">
        {detail && (
          <>
            <Card title={detail.original_filename} actions={<Pill tone={detail.status === 'flagged' ? 'rose' : detail.status === 'validated' ? 'emerald' : 'amber'}>{detail.status}</Pill>}>
              <p className="text-[11px] text-slate-500 mb-2">{DOC_LABELS[detail.doc_type]} · {(detail.file_size / 1024).toFixed(0)} KB · uploaded {fmtDate(detail.uploaded_at)}</p>
              {data.classification?.mismatch && <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2 mb-2">{data.classification.mismatch}</p>}
              {fields.length > 0 ? (
                <dl className="text-xs grid grid-cols-2 gap-x-3 gap-y-1.5">
                  {fields.map(([k, v]) => (
                    <React.Fragment key={k}>
                      <dt className="text-slate-500 font-mono truncate" title={k}>{k}</dt>
                      <dd className="text-slate-900 font-medium break-words">{String(v)}{data[`${k}_ocr_raw`] && <span className="block text-[10px] text-slate-400">OCR read: {data[`${k}_ocr_raw`]}</span>}</dd>
                    </React.Fragment>
                  ))}
                </dl>
              ) : (
                <p className="text-xs text-slate-500">No structured fields for this document type.</p>
              )}
            </Card>

            {data.infrastructure && (
              <Card title="Infrastructure analysis (advisory)">
                <p className="text-[11px] text-slate-500 mb-2">Model: {data.infrastructure.model || 'unavailable'} · status {data.infrastructure.status} · {data.infrastructure.frames_analyzed} frame(s)</p>
                <ul className="space-y-1.5 text-xs">
                  {data.infrastructure.compliance_flags.map((f: any) => (
                    <li key={f.object} className="flex justify-between gap-2"><span className="text-slate-700">{f.equipment}</span><Pill tone={f.status === 'compliant' ? 'emerald' : f.status === 'deficient' ? 'rose' : 'sky'}>{f.message}</Pill></li>
                  ))}
                </ul>
                {(data.infrastructure.evidence_quality?.issues || []).map((i: string) => <p key={i} className="text-[11px] text-amber-700 mt-2">⚠ {i}</p>)}
              </Card>
            )}

            <Card title="Source verification" actions={isOfficial && <Button variant="ghost" busy={busy} onClick={rerunVerification}><RefreshCw className="w-3.5 h-3.5" />Re-verify</Button>}>
              {detail.verifications.length === 0 ? (
                <p className="text-xs text-slate-500">Not verified yet.</p>
              ) : (
                <div className="space-y-3">
                  {latestPerMethod(detail.verifications).map((v) => (
                    <div key={v.id} className="border border-slate-200 rounded-xl p-3">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-xs font-semibold text-slate-800">{METHOD_LABEL[v.method]} · {v.source_authority}</span>
                        <VerificationPill status={v.status} />
                      </div>
                      {v.reason && <p className="text-[11px] text-slate-600 mb-2">{v.reason}</p>}
                      {v.field_comparison && v.field_comparison.length > 0 && <ComparisonTable rows={v.field_comparison} />}
                      <p className="text-[10px] text-slate-400 mt-1">
                        {fmtDate(v.verified_at)}{v.attempts && v.attempts > 1 ? ` · attempt ${v.attempts}` : ''}{v.next_retry_at ? ` · next retry ${fmtDate(v.next_retry_at)}` : ''}
                        {v.request_identifiers && Object.keys(v.request_identifiers).length > 0 && ` · sent: ${Object.values(v.request_identifiers).join(', ')}`}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card title={`Tampering indicators — ${forensics.level || 'not run'}`}>
              {(forensics.indicators || []).length === 0 ? (
                <p className="text-xs text-slate-500">No indicators. Checks run: {(forensics.checks_run || []).join(', ') || '—'}</p>
              ) : (
                <ul className="space-y-2">
                  {forensics.indicators.map((i: any, idx: number) => (
                    <li key={idx} className="text-xs">
                      <span className="font-semibold text-slate-800">{i.method}</span> <Pill tone={i.strength === 'strong' ? 'rose' : i.strength === 'medium' ? 'amber' : 'slate'}>{i.strength}</Pill>
                      <p className="text-slate-600 mt-0.5">{i.description}</p>
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-[10px] text-slate-400 mt-2">{forensics.disclaimer}</p>
            </Card>

            {(data.duplicates || []).length > 0 && (
              <Card title={<span className="flex items-center gap-1.5"><Copy className="w-4 h-4 text-amber-600" />Duplicates / re-use</span>}>
                <ul className="space-y-1.5 text-xs">
                  {data.duplicates.map((d: any, i: number) => <li key={i}><span className="font-semibold">{d.reason}</span> — {d.application_number} ({d.institution_name}), {d.filename}</li>)}
                </ul>
              </Card>
            )}

            {detail.versions.length > 1 && (
              <Card title={<span className="flex items-center gap-1.5"><History className="w-4 h-4" />Versions</span>}>
                <ul className="text-xs space-y-1">
                  {detail.versions.map((v) => (
                    <li key={v.id} className="flex justify-between"><button className="text-indigo-700 hover:underline cursor-pointer truncate" onClick={() => setSelectedId(v.id)}>{v.filename}</button><span className="text-slate-500">{v.is_current ? 'current' : 'superseded'} · {fmtDate(v.uploaded_at)}</span></li>
                  ))}
                </ul>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
};

function latestPerMethod<T extends { method: string; verified_at: string }>(items: T[]): T[] {
  const map = new Map<string, T>();
  [...items].sort((a, b) => a.verified_at.localeCompare(b.verified_at)).forEach((v) => map.set(v.method, v));
  return [...map.values()];
}
