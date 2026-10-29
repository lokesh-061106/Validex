import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Plus, ArrowRight, FolderOpen } from 'lucide-react';
import { errorMessage, portalApi } from '../api/client';
import type { PortalApplication } from '../types';
import { Button, Card, Empty, Modal, Pill, Spinner, fmtDay } from '../components/ui';
import { PORTAL_STATUS } from './PortalApplicationPage';
import { useAuth } from '../context/AuthContext';

export const InstitutionHomePage: React.FC = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [apps, setApps] = useState<PortalApplication[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ category: 'eoa', academic_year: '2026-2027', permanent_id: '', requested_intake: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => { portalApi.list().then(setApps); }, []);

  const create = async () => {
    setBusy(true);
    setError('');
    try {
      const app = await portalApi.create({
        category: form.category, academic_year: form.academic_year,
        permanent_id: form.permanent_id || undefined,
        requested_intake: form.requested_intake ? Number(form.requested_intake) : undefined,
      });
      navigate(`/applications/${app.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">My Applications</h1>
          <p className="text-sm text-slate-500 mt-0.5">{user?.institution_name}</p>
        </div>
        <Button variant="primary" onClick={() => setCreating(true)}><Plus className="w-4 h-4" /> New application</Button>
      </div>

      <Card>
        <ol className="grid md:grid-cols-4 gap-4 text-xs">
          {[
            ['1. Create a draft', 'Choose the application category; the checklist is set from the AICTE Approval Process Handbook.'],
            ['2. Upload documents', 'Upload each document in its checklist slot. Each file is sealed with a chain-of-custody watermark on receipt.'],
            ['3. Submit', 'AICTE officers scrutinise the application against the handbook norms.'],
            ['4. Respond', 'If anything is missing or expired, an encrypted clarification request arrives here.'],
          ].map(([t, d]) => (
            <li key={t}><p className="font-bold text-slate-900">{t}</p><p className="text-slate-500 mt-1">{d}</p></li>
          ))}
        </ol>
      </Card>

      <div className="glass-panel rounded-2xl overflow-hidden">
        {apps === null ? (
          <div className="flex justify-center p-10"><Spinner /></div>
        ) : apps.length === 0 ? (
          <Empty title="No applications yet" hint="Create a draft to start." icon={<FolderOpen className="w-9 h-9 text-slate-400" />} />
        ) : (
          <ul className="divide-y divide-slate-100">
            {apps.map((a) => (
              <li key={a.id}>
                <Link to={`/applications/${a.id}`} className="flex items-center justify-between px-5 py-4 hover:bg-slate-50">
                  <div>
                    <p className="font-mono text-xs font-bold text-indigo-700">{a.application_number}</p>
                    <p className="text-[11px] text-slate-500 uppercase">{a.category.replace('_', ' ')} · AY {a.academic_year} · updated {fmtDay(a.updated_at)}</p>
                    {a.rectification_due && a.status === 'clarification_requested' && <p className="text-[11px] text-amber-700 font-semibold mt-0.5">Respond by {fmtDay(a.rectification_due)}</p>}
                  </div>
                  <div className="flex items-center gap-3"><Pill tone={PORTAL_STATUS[a.status].tone}>{PORTAL_STATUS[a.status].label}</Pill><ArrowRight className="w-4 h-4 text-slate-400" /></div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {creating && (
        <Modal title="New application" onClose={() => setCreating(false)}>
          <div className="space-y-3">
            <div>
              <label className="label" htmlFor="cat">Category</label>
              <select id="cat" className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="eoa">Extension of Approval (EoA)</option>
                <option value="change_intake">Change in intake</option>
                <option value="new_institution">New institution</option>
                <option value="closure">Closure</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="pid">AICTE permanent ID</label>
                <input id="pid" className="input" placeholder="1-2345678901" value={form.permanent_id} onChange={(e) => setForm({ ...form, permanent_id: e.target.value })} />
              </div>
              <div>
                <label className="label" htmlFor="intake">Requested intake</label>
                <input id="intake" type="number" min={0} className="input" value={form.requested_intake} onChange={(e) => setForm({ ...form, requested_intake: e.target.value })} />
              </div>
            </div>
            <div>
              <label className="label" htmlFor="ay">Academic year</label>
              <input id="ay" className="input" value={form.academic_year} onChange={(e) => setForm({ ...form, academic_year: e.target.value })} />
            </div>
            {error && <p className="text-xs text-rose-600" role="alert">{error}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <Button onClick={() => setCreating(false)}>Cancel</Button>
              <Button variant="primary" busy={busy} onClick={create}>Create draft</Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
