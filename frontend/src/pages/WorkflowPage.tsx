import React, { useEffect, useState } from 'react';
import { GitBranch, Save } from 'lucide-react';
import { errorMessage, workflowApi } from '../api/client';
import type { ApplicationStatus, WorkflowTransitionItem } from '../types';
import { Button, Card } from '../components/ui';

const STATUSES: ApplicationStatus[] = ['draft', 'submitted', 'under_review', 'deficiency_found', 'verified', 'approved', 'rejected'];
const ROLES = ['institution', 'scrutiny', 'expert', 'approver', 'supervisor', 'admin', 'system'];

export const WorkflowPage: React.FC = () => {
  const [rows, setRows] = useState<WorkflowTransitionItem[]>([]);
  const [from, setFrom] = useState<ApplicationStatus>('draft');
  const [to, setTo] = useState<ApplicationStatus>('submitted');
  const [roles, setRoles] = useState<string[]>(['institution']);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const refresh = async () => setRows(await workflowApi.list());
  useEffect(() => { refresh().catch((e) => setMessage(errorMessage(e))); }, []);

  const save = async (edge: { from_status: string; to_status: string; allowed_roles: string[]; is_active: boolean }) => {
    if (reason.trim().length < 5) { setMessage('Enter a change reason (at least 5 characters).'); return; }
    setBusy(true); setMessage('');
    try {
      await workflowApi.configure({ ...edge, change_reason: reason.trim() });
      setReason(''); await refresh(); setMessage('Workflow transition saved and added to the audit history.');
    } catch (e) { setMessage(errorMessage(e)); } finally { setBusy(false); }
  };

  const add = () => save({ from_status: from, to_status: to, allowed_roles: roles, is_active: true });
  const toggleRole = (role: string) => setRoles((current) => current.includes(role) ? current.filter((r) => r !== role) : [...current, role]);

  return <div className="max-w-6xl mx-auto p-6 space-y-6">
    <header><h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2"><GitBranch className="w-6 h-6 text-indigo-600" />Approval workflow configuration</h1>
      <p className="mt-1 text-sm text-slate-600">Configure allowed application status transitions and responsible roles. Decisions remain subject to separate authorization and evidence checks.</p></header>
    {message && <div role="status" className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">{message}</div>}
    <Card title="Add or update a transition">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="text-sm font-medium">From<select value={from} onChange={(e) => setFrom(e.target.value as ApplicationStatus)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2">{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></label>
        <label className="text-sm font-medium">To<select value={to} onChange={(e) => setTo(e.target.value as ApplicationStatus)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2">{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></label>
        <fieldset className="md:col-span-2"><legend className="text-sm font-medium">Allowed roles</legend><div className="mt-2 flex flex-wrap gap-4">{ROLES.map((role) => <label key={role} className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={roles.includes(role)} onChange={() => toggleRole(role)} />{role}</label>)}</div></fieldset>
        <label className="md:col-span-2 text-sm font-medium">Reason for change<input value={reason} onChange={(e) => setReason(e.target.value)} minLength={5} maxLength={1000} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label>
        <Button disabled={busy || !roles.length || from === to} onClick={add}><Save className="mr-2 h-4 w-4" />Save transition</Button>
      </div>
    </Card>
    <Card title="Configured transitions">
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b text-xs uppercase text-slate-500"><th className="py-3">Transition</th><th>Allowed roles</th><th>Enabled</th><th /></tr></thead><tbody>
        {rows.map((row) => <tr key={row.id} className="border-b border-slate-100"><td className="py-3 font-mono">{row.from_status} → {row.to_status}</td><td>{row.allowed_roles.join(', ')}</td><td>{row.is_active ? 'Yes' : 'No'}</td><td className="text-right"><Button variant="secondary" disabled={busy} onClick={() => save({ from_status: row.from_status, to_status: row.to_status, allowed_roles: row.allowed_roles, is_active: !row.is_active })}>{row.is_active ? 'Disable' : 'Enable'}</Button></td></tr>)}
      </tbody></table></div>
    </Card>
  </div>;
};
