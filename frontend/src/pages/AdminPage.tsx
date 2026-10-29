import React, { useEffect, useState } from 'react';
import { UserPlus, PlugZap, Trash2 } from 'lucide-react';
import { adminApi, errorMessage } from '../api/client';
import type { User } from '../types';
import { useAuth } from '../context/AuthContext';
import { Button, Card, Pill, fmtDay } from '../components/ui';

export const AdminPage: React.FC = () => {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState({ email: '', password: '', full_name: '', role: 'scrutiny' });
  const [outage, setOutage] = useState<{ outage: boolean; mode: string } | null>(null);
  const [purge, setPurge] = useState<any>(null);
  const [msg, setMsg] = useState('');

  const load = () => { adminApi.users().then(setUsers); adminApi.outageStatus().then(setOutage); };
  useEffect(load, []);

  const create = async () => {
    setMsg('');
    try {
      await adminApi.createUser(form);
      setForm({ email: '', password: '', full_name: '', role: 'scrutiny' });
      setMsg('Account created.');
      load();
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Administration</h1>
        <p className="text-sm text-slate-500 mt-0.5">Official accounts, simulated-source controls, and data retention.</p>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Card title="Accounts" className="lg:col-span-2">
          <div className="overflow-x-auto" role="region" aria-label="User accounts table" tabIndex={0}>
          <table className="w-full min-w-[650px] text-xs">
            <thead><tr className="text-left text-slate-500 border-b border-slate-100"><th className="py-2">Name</th><th>Email</th><th>Role</th><th>Since</th><th /></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-slate-50">
                  <td className="py-1.5">{u.full_name}</td>
                  <td className="font-mono text-slate-600">{u.email}</td>
                  <td><Pill tone={u.role === 'institution' ? 'slate' : 'indigo'}>{u.role}</Pill></td>
                  <td className="text-slate-500">{fmtDay(u.created_at)}</td>
                  <td className="text-right">
                    {u.id !== me?.id && <Button variant="ghost" onClick={async () => { await adminApi.setActive(u.id, !u.is_active); load(); }}>{u.is_active ? 'Deactivate' : 'Activate'}</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </Card>

        <div className="space-y-5">
          <Card title={<span className="flex items-center gap-1.5"><UserPlus className="w-4 h-4" />Create official account</span>}>
            <div className="space-y-2">
              <input className="input" placeholder="Full name" aria-label="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
              <input className="input" placeholder="Email" aria-label="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <input className="input" type="password" placeholder="Initial password (8+ chars)" aria-label="Password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <select className="input" aria-label="Role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="scrutiny">Scrutiny officer</option><option value="expert">Expert committee</option><option value="approver">Approving officer</option><option value="supervisor">Supervisor</option><option value="admin">Platform administrator</option>
              </select>
              <Button variant="primary" onClick={create} className="w-full">Create</Button>
              {msg && <p className="text-xs text-slate-600">{msg}</p>}
            </div>
          </Card>

          <Card title={<span className="flex items-center gap-1.5"><PlugZap className="w-4 h-4" />Simulated issuing authorities</span>}>
            <p className="text-xs text-slate-600 mb-2">Mode: <span className="font-mono">{outage?.mode}</span>. Simulate an outage to show “source unavailable” and automatic retry.</p>
            <Button variant={outage?.outage ? 'success' : 'danger'} onClick={async () => { await adminApi.setOutage(!outage?.outage); load(); }}>
              {outage?.outage ? 'Restore sources' : 'Simulate outage'}
            </Button>
          </Card>

          <Card title={<span className="flex items-center gap-1.5"><Trash2 className="w-4 h-4" />Data retention</span>}>
            <p className="text-xs text-slate-600 mb-2">Deletes stored files of decided applications past the retention period; metadata, findings and audit entries are kept.</p>
            <div className="flex gap-2">
              <Button onClick={async () => setPurge(await adminApi.purge(true))}>Dry run</Button>
              <Button variant="danger" onClick={async () => window.confirm('Delete stored files that are past retention?') && setPurge(await adminApi.purge(false))}>Purge now</Button>
            </div>
            {purge && <p className="text-xs text-slate-600 mt-2">{purge.dry_run ? 'Would purge' : 'Purged'} {purge.documents} document(s) older than {purge.retention_days} days.</p>}
          </Card>
        </div>
      </div>
    </div>
  );
};
