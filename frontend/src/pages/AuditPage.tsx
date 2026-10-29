import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShieldCheck, ShieldAlert, Hash } from 'lucide-react';
import { auditApi } from '../api/client';
import type { AuditEntry } from '../types';
import { Button, Card, Spinner, fmtDate } from '../components/ui';

export const AuditPage: React.FC = () => {
  const [logs, setLogs] = useState<AuditEntry[] | null>(null);
  const [action, setAction] = useState('');
  const [chain, setChain] = useState<any>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => { setLogs(null); auditApi.getSystemLogs(action || undefined).then(setLogs); }, [action]);

  const verify = async () => {
    setChecking(true);
    try { setChain(await auditApi.verifyChain()); } finally { setChecking(false); }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Audit Ledger</h1>
          <p className="text-sm text-slate-500 mt-0.5">Every automated check, source response, rule change, document view and official action. Entries are hash-chained.</p>
        </div>
        <Button variant="primary" busy={checking} onClick={verify}><ShieldCheck className="w-4 h-4" />Verify chain integrity</Button>
      </div>

      {chain && (
        <div className={`p-4 rounded-xl border text-sm ${chain.valid ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-rose-50 border-rose-200 text-rose-800'}`} role="status">
          <p className="font-semibold flex items-center gap-2">{chain.valid ? <ShieldCheck className="w-4 h-4" /> : <ShieldAlert className="w-4 h-4" />}{chain.valid ? `Chain intact: ${chain.entries_checked} entries verified` : `Integrity problems found in ${chain.problems.length} entr${chain.problems.length === 1 ? 'y' : 'ies'}`}</p>
          {chain.head_hash && <p className="text-[11px] font-mono mt-1">head {chain.head_hash}</p>}
          {chain.problems?.map((p: any) => <p key={p.id} className="text-xs mt-1">{p.action}: {p.problem}</p>)}
        </div>
      )}

      <Card title="Entries" actions={
        <select className="input w-56" value={action} onChange={(e) => setAction(e.target.value)} aria-label="Filter by action">
          <option value="">All actions</option>
          {['APPLICATION_DECISION', 'DEFICIENCY_NOTICE_ISSUED', 'AI_PRESCREENING_COMPLETED', 'DOCUMENT_VERIFIED', 'DOCUMENT_UPLOADED', 'DOCUMENT_REPLACED', 'DOCUMENT_VIEWED', 'RULE_UPDATED', 'USER_LOGIN', 'LOGIN_FAILED'].map((a) => <option key={a}>{a}</option>)}
        </select>
      }>
        {!logs ? <div className="flex justify-center p-8"><Spinner /></div> : (
          <div className="overflow-x-auto" role="region" aria-label="Audit ledger table" tabIndex={0}>
          <table className="w-full min-w-[760px] text-xs">
            <thead><tr className="text-left text-slate-500 border-b border-slate-100"><th className="py-2">Time</th><th>Action</th><th>Actor</th><th>Details</th><th>IP</th><th>Hash</th></tr></thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b border-slate-50 align-top">
                  <td className="py-1.5 pr-2 whitespace-nowrap text-slate-500">{fmtDate(l.created_at)}</td>
                  <td className="pr-2 font-semibold text-slate-800">{l.action}</td>
                  <td className="pr-2">{l.actor}{l.actor_role ? <span className="text-slate-400"> ({l.actor_role})</span> : ''}</td>
                  <td className="pr-2 text-slate-600 max-w-md truncate" title={JSON.stringify(l.details)}>
                    {l.application_id && <Link className="text-indigo-700 mr-1" to={`/applications/${l.application_id}`}>app</Link>}
                    {Object.entries(l.details || {}).filter(([, v]) => typeof v !== 'object').slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                  </td>
                  <td className="pr-2 font-mono text-slate-400">{l.ip_address || '—'}</td>
                  <td className="font-mono text-slate-400" title={l.entry_hash || ''}>{l.entry_hash ? <span className="flex items-center gap-0.5"><Hash className="w-3 h-3" />{l.entry_hash.slice(0, 8)}</span> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </Card>
    </div>
  );
};
