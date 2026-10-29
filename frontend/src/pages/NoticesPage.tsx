import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Lock, CheckCircle2, KeyRound } from 'lucide-react';
import { notificationsApi } from '../api/client';
import type { ClarificationPayload, NotificationItem } from '../types';
import { useAuth } from '../context/AuthContext';
import { decryptNotice } from '../lib/secureInbox';
import { Button, Card, DOC_LABELS, Empty, Pill, Spinner, fmtDate, fmtDay } from '../components/ui';

/** A clarification request, decrypted in this browser with the institution's private key. */
export const SecureNoticeCard: React.FC<{ n: NotificationItem; onAck?: (n: NotificationItem) => void; showLink?: boolean }> = ({ n, onAck, showLink }) => {
  const { user } = useAuth();
  const [payload, setPayload] = useState<ClarificationPayload | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!user || !n.encrypted_payload) return;
    decryptNotice<ClarificationPayload>(user.id, n.encrypted_payload)
      .then(setPayload)
      .catch(() => setError('This request was encrypted to a key held by another browser or device. Open it there, or ask AICTE to re-issue it.'));
  }, [user, n]);

  return (
    <Card
      title={<span className="flex items-center gap-2"><Lock className="w-4 h-4 text-indigo-600" />{n.subject}</span>}
      actions={<Pill tone={n.status === 'resolved' ? 'emerald' : n.status === 'acknowledged' ? 'sky' : 'amber'}>{n.status}</Pill>}
    >
      <p className="text-[11px] text-slate-500 mb-3">
        Sent {fmtDate(n.created_at)} · respond by <span className="font-semibold text-amber-700">{fmtDay(n.due_date)}</span> · end-to-end encrypted
      </p>
      {!n.encrypted_payload ? (
        <p className="text-xs text-slate-600">{n.body}</p>
      ) : error ? (
        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2 flex gap-2"><KeyRound className="w-4 h-4 shrink-0" />{error}</p>
      ) : !payload ? (
        <div className="flex justify-center p-4"><Spinner /></div>
      ) : (
        <>
          {payload.note && <p className="text-xs text-slate-700 mb-2">{payload.note}</p>}
          <ol className="space-y-2">
            {payload.items.map((it, i) => (
              <li key={i} className="p-3 rounded-xl bg-slate-50 border border-slate-200">
                <p className="text-xs font-semibold text-slate-900">{it.doc_type ? `${DOC_LABELS[it.doc_type] || it.doc_type}: ` : ''}{it.request}</p>
                <p className="text-xs text-slate-600 mt-1"><span className="font-semibold text-indigo-700">What to do:</span> {it.what_to_do}</p>
              </li>
            ))}
          </ol>
        </>
      )}
      <div className="flex justify-end gap-2 mt-3">
        {showLink && <Link to={`/applications/${n.application_id}`} className="text-xs font-semibold text-indigo-600 px-3 py-2">Open application →</Link>}
        {onAck && n.status === 'sent' && <Button variant="primary" onClick={() => onAck(n)}><CheckCircle2 className="w-3.5 h-3.5" /> Acknowledge</Button>}
      </div>
    </Card>
  );
};

export const NoticesPage: React.FC = () => {
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  useEffect(() => { notificationsApi.list().then(setItems); }, []);
  const ack = async (n: NotificationItem) => {
    const updated = await notificationsApi.acknowledge(n.id);
    setItems((prev) => prev?.map((x) => (x.id === n.id ? updated : x)) || null);
  };
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Clarification Requests</h1>
        <p className="text-sm text-slate-500 mt-0.5">Requests from AICTE are encrypted to this browser. Supply the listed documents, then resubmit.</p>
      </div>
      {items === null ? <div className="flex justify-center p-10"><Spinner /></div> : items.length === 0 ? <Empty title="No clarification requests" /> : items.map((n) => <SecureNoticeCard key={n.id} n={n} onAck={ack} showLink />)}
    </div>
  );
};
