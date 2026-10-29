import React, { useEffect, useState } from 'react';
import { CalendarClock, Check, Clock3, RefreshCw } from 'lucide-react';
import { deadlinesApi, errorMessage, portalApi } from '../api/client';
import { useAuth } from '../context/AuthContext';
import type { DeadlineItem, DeadlineKind, PortalApplication } from '../types';
import { Button, Card } from '../components/ui';

const LABELS: Record<DeadlineKind, string> = {
  workflow: 'Workflow deadline', evc: 'EVC visit', undertaking: 'Undertaking',
  lease_expiry: 'Lease expiry', document_expiry: 'Document expiry',
};

export const DeadlinesPage: React.FC = () => {
  const { user } = useAuth();
  const institution = user?.role === 'institution';
  const [items, setItems] = useState<DeadlineItem[]>([]);
  const [applications, setApplications] = useState<PortalApplication[]>([]);
  const [appId, setAppId] = useState('');
  const [kind, setKind] = useState<DeadlineKind>(institution ? 'undertaking' : 'evc');
  const [title, setTitle] = useState('');
  const [dueAt, setDueAt] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const refresh = async () => {
    const [deadlines, apps] = await Promise.all([deadlinesApi.list(), portalApi.list()]);
    setItems(deadlines);
    setApplications(apps);
    setAppId((prev) => prev || apps[0]?.id || '');
  };
  useEffect(() => { refresh().catch((e) => setMessage(errorMessage(e))); }, []);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true); setMessage('');
    try {
      await deadlinesApi.create({ application_id: appId, kind, title, due_at: new Date(dueAt).toISOString(),
        description: description || undefined, remind_before_hours: 24, escalate_after_hours: 24 });
      setTitle(''); setDescription(''); await refresh(); setMessage('Deadline saved. Reminder and escalation state is stored in Validex.');
    } catch (e) { setMessage(errorMessage(e)); } finally { setBusy(false); }
  };

  const runSweep = async () => {
    setBusy(true); setMessage('');
    try {
      const result = await deadlinesApi.processDue(); await refresh();
      setMessage(`Sweep complete: ${result.reminders_created} reminder(s), ${result.escalations_created} escalation(s) created.`);
    } catch (e) { setMessage(errorMessage(e)); } finally { setBusy(false); }
  };

  const complete = async (item: DeadlineItem) => {
    try { await deadlinesApi.complete(item.id); await refresh(); }
    catch (e) { setMessage(errorMessage(e)); }
  };

  return <div className="max-w-6xl mx-auto p-6 space-y-6">
    <div className="flex items-start justify-between gap-4">
      <div><h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2"><CalendarClock className="w-6 h-6 text-indigo-600" />Deadlines & EVC</h1>
        <p className="text-sm text-slate-600 mt-1">Track visits, undertakings and expiry dates. Reminders and escalation are persisted and auditable.</p></div>
      {!institution && <Button onClick={runSweep} disabled={busy}><RefreshCw className="w-4 h-4 mr-2" />Run due sweep</Button>}
    </div>
    {message && <div role="status" className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">{message}</div>}
    <Card>
      <form onSubmit={create} className="grid gap-4 md:grid-cols-2">
        <label className="text-sm font-medium text-slate-700">Application<select required value={appId} onChange={(e) => setAppId(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2">
          {applications.map((a) => <option key={a.id} value={a.id}>{a.application_number} · {a.institution_name}</option>)}
        </select></label>
        <label className="text-sm font-medium text-slate-700">Record type<select value={kind} onChange={(e) => setKind(e.target.value as DeadlineKind)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2">
          {(institution ? ['undertaking', 'lease_expiry', 'document_expiry'] : Object.keys(LABELS)).map((v) => <option key={v} value={v}>{LABELS[v as DeadlineKind]}</option>)}
        </select></label>
        <label className="text-sm font-medium text-slate-700">Title<input required minLength={3} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Fire safety certificate renewal" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
        <label className="text-sm font-medium text-slate-700">Due date and time<input required type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
        <label className="text-sm font-medium text-slate-700 md:col-span-2">Details<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
        <div className="md:col-span-2"><Button type="submit" disabled={busy || !appId || !dueAt || title.trim().length < 3}>Save deadline</Button></div>
      </form>
    </Card>
    <section className="space-y-3" aria-label="Scheduled deadlines">
      {items.length === 0 ? <Card><p className="py-6 text-center text-sm text-slate-500">No deadlines have been recorded.</p></Card> : items.map((item) => <Card key={item.id}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700">{LABELS[item.kind]}</span><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${item.status === 'open' ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-600'}`}>{item.status}</span></div>
            <h2 className="mt-2 font-semibold text-slate-900">{item.title}</h2><p className="text-sm text-slate-600">{applications.find((a) => a.id === item.application_id)?.application_number || item.application_id}</p>
            {item.description && <p className="mt-1 text-sm text-slate-600">{item.description}</p>}
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-600"><Clock3 className="w-4 h-4" />{new Date(item.due_at).toLocaleString()}
            {item.status === 'open' && <Button variant="secondary" onClick={() => complete(item)}><Check className="w-4 h-4 mr-1" />Complete</Button>}
          </div>
        </div>
        {item.escalation_level > 0 && <p className="mt-3 text-xs font-medium text-rose-700">Overdue escalation level {item.escalation_level}</p>}
      </Card>)}
    </section>
  </div>;
};
