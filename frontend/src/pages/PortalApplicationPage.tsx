import React, { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Send } from 'lucide-react';
import { errorMessage, notificationsApi, portalApi } from '../api/client';
import type { NotificationItem, PortalApplication } from '../types';
import { Button, Empty, Pill, Spinner, fmtDay } from '../components/ui';
import { UploadSlots } from '../components/UploadSlots';
import { SecureNoticeCard } from './NoticesPage';

export const PORTAL_STATUS: Record<PortalApplication['status'], { label: string; tone: string }> = {
  draft: { label: 'Draft', tone: 'slate' },
  received: { label: 'Received by AICTE', tone: 'indigo' },
  under_review: { label: 'Under review', tone: 'sky' },
  clarification_requested: { label: 'Clarification requested', tone: 'amber' },
  approved: { label: 'Approved', tone: 'emerald' },
  rejected: { label: 'Not approved', tone: 'rose' },
};

/** Institution view of an application: what was submitted and received, never how it was assessed. */
export const PortalApplicationPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [app, setApp] = useState<PortalApplication | null>(null);
  const [notices, setNotices] = useState<NotificationItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!id) return;
    const [a, n] = await Promise.all([portalApi.get(id), notificationsApi.list(id)]);
    setApp(a);
    setNotices(n);
  }, [id]);

  useEffect(() => { load().catch((e) => setError(errorMessage(e))); }, [load]);

  if (error && !app) return <Empty title="Could not load application" hint={error} />;
  if (!app) return <div className="flex justify-center p-16"><Spinner /></div>;

  const editable = app.status === 'draft' || app.status === 'clarification_requested';
  const status = PORTAL_STATUS[app.status];
  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      await portalApi.submit(app.id);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <Link to="/" className="inline-flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-800"><ArrowLeft className="w-3.5 h-3.5" />Back</Link>
      <div className="glass-panel rounded-2xl p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm font-bold text-indigo-700 px-3 py-1 rounded-lg bg-indigo-50 border border-indigo-200">{app.application_number}</span>
            <Pill tone={status.tone}>{status.label}</Pill>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">{app.institution_name}</h1>
          <p className="text-xs text-slate-500">
            AICTE ID {app.permanent_id || '—'} · intake {app.requested_intake ?? '—'} · AY {app.academic_year}
            {app.rectification_due && app.status === 'clarification_requested' && <span className="text-amber-700 font-semibold"> · respond by {fmtDay(app.rectification_due)}</span>}
          </p>
        </div>
        {editable && (
          <Button variant="primary" onClick={submit} busy={busy}>
            <Send className="w-3.5 h-3.5" />{app.status === 'draft' ? 'Submit to AICTE' : 'Resubmit'}
          </Button>
        )}
      </div>
      {error && <p className="text-xs text-rose-600" role="alert">{error}</p>}

      {notices.length > 0 && (
        <div className="space-y-3">
          {notices.map((n) => <SecureNoticeCard key={n.id} n={n} onAck={async (x) => { await notificationsApi.acknowledge(x.id); load(); }} />)}
        </div>
      )}

      <UploadSlots app={app} editable={editable} onChanged={load} />
    </div>
  );
};
