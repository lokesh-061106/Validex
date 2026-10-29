import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileText, AlertTriangle, CheckCircle2, Clock, ShieldAlert, Copy, RefreshCw, Hourglass, Timer, Download } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell } from 'recharts';
import { dashboardApi } from '../api/client';
import type { DashboardStats, RiskDistributionItem, AlertItem, ActivityItem, Metrics } from '../types';
import { Button, Card, Empty, SeverityIcon, fmtDate } from '../components/ui';
import { useAuth } from '../context/AuthContext';

const Stat: React.FC<{ label: string; value: React.ReactNode; hint?: string; icon: React.ElementType; tone: string }> = ({ label, value, hint, icon: Icon, tone }) => (
  <div className="glass-panel rounded-2xl p-4">
    <div className="flex items-center justify-between">
      <p className="text-[11px] uppercase font-bold tracking-wider text-slate-500">{label}</p>
      <Icon className={`w-4 h-4 ${tone}`} />
    </div>
    <p className="text-2xl font-bold font-mono text-slate-900 mt-1">{value}</p>
    {hint && <p className="text-[11px] text-slate-500 mt-0.5">{hint}</p>}
  </div>
);

export const DashboardPage: React.FC = () => {
  const { user } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [risk, setRisk] = useState<RiskDistributionItem[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [s, r, a, act, m] = await Promise.all([
        dashboardApi.getStats(), dashboardApi.getRiskDistribution(), dashboardApi.getAlerts(), dashboardApi.getRecentActivity(), dashboardApi.getMetrics(),
      ]);
      setStats(s); setRisk(r); setAlerts(a); setActivity(act); setMetrics(m);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`);

  const exportReport = async () => {
    const blob = await dashboardApi.exportReport();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = 'validex-applications-report.csv'; link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">{user?.role === 'supervisor' ? 'Supervisor Dashboard' : user?.role === 'approver' ? 'Approval Dashboard' : user?.role === 'admin' ? 'Platform Administration Dashboard' : 'Scrutiny Dashboard'}</h1>
          <p className="text-sm text-slate-500 mt-0.5">Applications awaiting action, unresolved discrepancies and cases needing authorized review</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={exportReport}><Download className="w-3.5 h-3.5" /> CSV report</Button>
          <Button onClick={load} busy={loading}><RefreshCw className="w-3.5 h-3.5" /> Refresh</Button>
          <Link to="/applications" className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-xs font-semibold text-white">Open review queue</Link>
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Stat label="Awaiting review" value={stats.awaiting_review} hint={`${stats.total_applications} submitted in total`} icon={Clock} tone="text-sky-600" />
          <Stat label="High risk (≥60)" value={stats.high_risk_flagged} hint="Prioritised in the queue" icon={ShieldAlert} tone="text-rose-600" />
          <Stat label="Deficiency notices" value={stats.deficiency_found} hint={`${stats.overdue_rectifications} past rectification date`} icon={AlertTriangle} tone="text-amber-600" />
          <Stat label="Decided" value={stats.approved + stats.rejected} hint={`${stats.approved} approved · ${stats.rejected} rejected`} icon={CheckCircle2} tone="text-emerald-600" />
          <Stat label="Tampering suspected" value={stats.tamper_suspected_count} hint="Documents with medium/high indicators" icon={FileText} tone="text-rose-600" />
          <Stat label="Duplicate / re-used evidence" value={stats.duplicate_flags} hint="Across all institutions" icon={Copy} tone="text-amber-600" />
          <Stat label="Pending source checks" value={stats.pending_source_verifications} hint="Unavailable or pending; auto-retry" icon={Hourglass} tone="text-sky-600" />
          <Stat label="Avg processing / doc" value={stats.avg_processing_seconds_per_document != null ? `${stats.avg_processing_seconds_per_document}s` : '—'} hint={`${stats.total_documents_processed} documents processed`} icon={Timer} tone="text-indigo-600" />
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        <Card title="Open alerts" className="lg:col-span-2" actions={<span className="text-[11px] text-slate-500">critical first</span>}>
          {alerts.length === 0 ? (
            <Empty title="No open alerts" />
          ) : (
            <ul className="divide-y divide-slate-100">
              {alerts.map((a) => (
                <li key={a.id}>
                  <Link to={`/applications/${a.application_id}`} className="flex items-start gap-3 py-2.5 hover:bg-slate-50 rounded-lg px-2 -mx-2">
                    <SeverityIcon severity={a.severity} className="w-4 h-4 mt-0.5 shrink-0" />
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-slate-900 truncate">{a.title}</p>
                      <p className="text-[11px] text-slate-500 truncate">{a.application_number} · {a.institution_name} · {a.check_type}</p>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Risk distribution">
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={risk} margin={{ left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
                <XAxis dataKey="category" tick={{ fontSize: 10 }} interval={0} />
                <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                  {risk.map((r) => <Cell key={r.category} fill={r.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        <Card title="Evaluation metrics (live)">
          {metrics && (
            <dl className="text-xs space-y-2">
              <div className="flex justify-between"><dt className="text-slate-500">Source checks completed automatically</dt><dd className="font-mono font-semibold">{pct(metrics.verification.automated_completion_rate)}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Total source checks</dt><dd className="font-mono font-semibold">{metrics.verification.total_checks}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">AI ↔ official agreement</dt><dd className="font-mono font-semibold">{pct(metrics.decisions.ai_human_agreement_rate)} <span className="text-slate-400">({metrics.decisions.decided} decided)</span></dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Avg / max processing</dt><dd className="font-mono font-semibold">{metrics.processing.avg_seconds_per_document ?? '—'}s / {metrics.processing.max_seconds ?? '—'}s</dd></div>
              <div className="pt-2 border-t border-slate-100">
                <dt className="text-slate-500 mb-1">Verification outcomes</dt>
                <dd className="flex flex-wrap gap-1">{Object.entries(metrics.verification.by_status).map(([k, v]) => <span key={k} className="px-1.5 py-0.5 rounded bg-slate-100 font-mono">{k}: {v}</span>)}</dd>
              </div>
            </dl>
          )}
          <p className="text-[11px] text-slate-400 mt-3">Offline accuracy on the labelled synthetic set: see EVALUATION.md.</p>
        </Card>

        <Card title="Recent activity (audit ledger)" className="lg:col-span-2">
          {activity.length === 0 ? (
            <Empty title="No activity yet" />
          ) : (
            <ul className="space-y-2">
              {activity.map((a) => (
                <li key={a.id} className="flex items-center justify-between text-xs">
                  <span className="truncate"><span className="font-semibold text-slate-800">{a.action}</span> <span className="text-slate-500">· {a.institution_name} · {a.user_name}</span> {a.details && <span className="text-slate-400">· {a.details}</span>}</span>
                  <span className="text-[11px] text-slate-400 shrink-0 ml-3">{fmtDate(a.timestamp)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
};
