import React, { useRef, useState } from 'react';
import { Upload, CheckCircle2, RefreshCw, Loader2 } from 'lucide-react';
import { documentsApi, errorMessage } from '../api/client';
import type { DocumentType, PortalApplication, PortalDocument } from '../types';
import { DOC_LABELS, Pill, cx, fmtDate } from './ui';

type Item = PortalApplication['checklist'][number];

/**
 * Institution upload slot. Deliberately "blind": after upload it only ever shows
 * "Document received". No progress, stages, flags or analysis are exposed to institutions.
 */
const Slot: React.FC<{ app: PortalApplication; item: Item; doc?: PortalDocument; editable: boolean; onChanged: () => void }> = ({ app, item, doc, editable, onChanged }) => {
  const input = useRef<HTMLInputElement>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  const onFile = async (file?: File) => {
    if (!file) return;
    setError('');
    setSending(true);
    try {
      if (doc) await documentsApi.replace(doc.id, file);
      else await documentsApi.upload(app.id, file, item.doc_type);
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSending(false);
      if (input.current) input.current.value = '';
    }
  };

  const accept = item.doc_type === 'lab_photo' ? 'image/jpeg,image/png,video/mp4'
    : item.doc_type === 'campus_boundary' ? '.geojson,application/geo+json,application/json' : 'application/pdf,image/jpeg,image/png';

  return (
    <div className={cx('p-4 rounded-xl border bg-white', doc ? 'border-slate-300' : 'border-dashed border-slate-300')}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-bold text-slate-900">{DOC_LABELS[item.doc_type] || item.title}</p>
          <p className="text-[11px] text-slate-500">{item.description}</p>
        </div>
        {!doc && <Pill tone="amber">Required</Pill>}
      </div>
      {doc && (
        <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-700">
          <CheckCircle2 className="w-4 h-4 text-slate-500 shrink-0" />
          <span className="min-w-0"><span className="font-semibold">Document received</span> · <span className="truncate">{doc.original_filename}</span> · {fmtDate(doc.uploaded_at)}</span>
        </div>
      )}
      {sending && <p className="mt-2 text-[11px] text-slate-600 flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" />Uploading…</p>}
      {error && <p className="text-[11px] text-rose-600 mt-2" role="alert">{error}</p>}
      {editable && !sending && (
        <>
          <input ref={input} type="file" className="hidden" accept={accept} onChange={(e) => onFile(e.target.files?.[0])} aria-label={`Upload ${DOC_LABELS[item.doc_type]}`} />
          <button onClick={() => input.current?.click()} className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-700 hover:text-indigo-900 cursor-pointer">
            {doc ? <><RefreshCw className="w-3.5 h-3.5" />Replace file</> : <><Upload className="w-3.5 h-3.5" />Upload</>}
          </button>
        </>
      )}
    </div>
  );
};

export const UploadSlots: React.FC<{ app: PortalApplication; editable: boolean; onChanged: () => void }> = ({ app, editable, onChanged }) => {
  const docs = app.documents.filter((d) => d.is_current);
  const covered = new Set(app.checklist.map((c) => c.doc_type));
  const extras = docs.filter((d) => !covered.has(d.doc_type as DocumentType));
  return (
    <div className="space-y-3">
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
        {app.checklist.map((item) => (
          <Slot key={item.doc_type} app={app} item={item} doc={docs.find((d) => d.doc_type === item.doc_type)} editable={editable} onChanged={onChanged} />
        ))}
      </div>
      {extras.length > 0 && <p className="text-[11px] text-slate-500">Other uploads: {extras.map((d) => d.original_filename).join(', ')}</p>}
      <p className="text-[11px] text-slate-500">
        Every file is sealed with a chain-of-custody watermark on receipt. {editable ? '' : 'Documents can be changed while the application is a draft or when AICTE requests clarification.'}
      </p>
    </div>
  );
};
