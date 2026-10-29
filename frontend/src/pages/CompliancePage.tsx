import React, { useEffect, useState } from 'react';
import { Pencil, Plus, History } from 'lucide-react';
import { complianceApi, errorMessage } from '../api/client';
import type { ComplianceRule } from '../types';
import { useAuth } from '../context/AuthContext';
import { Button, Card, DOC_LABELS, Modal, Pill, Spinner, fmtDate } from '../components/ui';

const OPS = ['>=', '>', '<=', '<', '==', '!=', 'exists', 'not_expired', 'in', 'is_true'];
const CATEGORIES = ['eoa', 'new_institution', 'change_intake', 'closure', 'other'];

const describe = (r: ComplianceRule) => {
  const c = r.conditions || {};
  const parts: string[] = [];
  if (c.requires_doc) parts.push(`requires ${DOC_LABELS[c.requires_doc] || c.requires_doc}`);
  if (c.check) {
    const v = c.check.value;
    const val = v && typeof v === 'object' && 'fact' in v ? v.fact : v;
    parts.push(`${c.check.fact} ${c.check.op}${val !== undefined ? ` ${val}` : ''}`);
  }
  return parts.join(' · ');
};

const RuleEditor: React.FC<{ rule?: ComplianceRule; onClose: () => void; onSaved: () => void }> = ({ rule, onClose, onSaved }) => {
  const c = rule?.conditions || {};
  const initialValue = c.check?.value;
  const [f, setF] = useState({
    rule_code: rule?.rule_code || '',
    title: rule?.title || '',
    description: rule?.description || '',
    category: rule?.category || 'statutory',
    severity: rule?.severity || 'critical',
    applies_to: rule?.applies_to || [],
    requires_doc: c.requires_doc || '',
    fact: c.check?.fact || '',
    op: c.check?.op || '>=',
    valueKind: initialValue && typeof initialValue === 'object' ? 'fact' : typeof initialValue === 'number' ? 'number' : 'text',
    value: initialValue && typeof initialValue === 'object' ? initialValue.fact : initialValue ?? '',
    label: c.check?.label || '',
    fix_hint: c.fix_hint || '',
    on_missing_fact: c.on_missing_fact || 'manual_review',
    is_active: rule?.is_active ?? true,
    reason: '',
  });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setF((p) => ({ ...p, [k]: v }));

  const save = async () => {
    setBusy(true);
    setError('');
    const conditions: Record<string, any> = { ...(rule?.conditions || {}), fix_hint: f.fix_hint || undefined, on_missing_fact: f.on_missing_fact };
    if (f.requires_doc) conditions.requires_doc = f.requires_doc; else delete conditions.requires_doc;
    if (f.fact) {
      const value = ['exists', 'not_expired', 'is_true'].includes(f.op) ? undefined
        : f.valueKind === 'number' ? Number(f.value) : f.valueKind === 'fact' ? { fact: f.value } : f.value;
      conditions.check = { fact: f.fact, op: f.op, ...(value !== undefined ? { value } : {}), label: f.label || undefined };
    } else delete conditions.check;
    const body: any = { title: f.title, description: f.description, category: f.category, severity: f.severity, applies_to: f.applies_to, conditions, is_active: f.is_active };
    try {
      if (rule) await complianceApi.updateRule(rule.id, { ...body, change_reason: f.reason });
      else await complianceApi.createRule({ ...body, rule_code: f.rule_code });
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={rule ? `Edit ${rule.rule_code} (v${rule.version} → v${rule.version + 1})` : 'New rule'} onClose={onClose} wide>
      <div className="grid grid-cols-2 gap-3">
        {!rule && <div><label className="label" htmlFor="code">Rule code</label><input id="code" className="input" value={f.rule_code} onChange={(e) => set('rule_code', e.target.value)} /></div>}
        <div className={rule ? 'col-span-2' : ''}><label className="label" htmlFor="title">Title</label><input id="title" className="input" value={f.title} onChange={(e) => set('title', e.target.value)} /></div>
        <div className="col-span-2"><label className="label" htmlFor="desc">Description / handbook basis</label><textarea id="desc" rows={2} className="input" value={f.description} onChange={(e) => set('description', e.target.value)} /></div>
        <div><label className="label" htmlFor="cat">Category</label><select id="cat" className="input" value={f.category} onChange={(e) => set('category', e.target.value)}>{['safety', 'infrastructure', 'academic', 'financial', 'statutory'].map((x) => <option key={x}>{x}</option>)}</select></div>
        <div><label className="label" htmlFor="sev">Severity when failed</label><select id="sev" className="input" value={f.severity} onChange={(e) => set('severity', e.target.value)}><option>critical</option><option>warning</option><option>info</option></select></div>
        <div className="col-span-2">
          <span className="label">Applies to (none = all)</span>
          <div className="flex flex-wrap gap-2">{CATEGORIES.map((cat) => (
            <label key={cat} className="text-xs flex items-center gap-1"><input type="checkbox" checked={f.applies_to.includes(cat)} onChange={(e) => set('applies_to', e.target.checked ? [...f.applies_to, cat] : f.applies_to.filter((x: string) => x !== cat))} />{cat}</label>
          ))}</div>
        </div>
        <div><label className="label" htmlFor="req">Required document</label><select id="req" className="input" value={f.requires_doc} onChange={(e) => set('requires_doc', e.target.value)}><option value="">— none —</option>{Object.entries(DOC_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div><label className="label" htmlFor="label">Check label</label><input id="label" className="input" value={f.label} onChange={(e) => set('label', e.target.value)} /></div>
        <div className="col-span-2 grid grid-cols-6 gap-2 items-end">
          <div className="col-span-3"><label className="label" htmlFor="fact">Fact (docs.*, records.*, infra.*, app.*, computed.*)</label><input id="fact" className="input font-mono" placeholder="docs.land_document.land_area_acres" value={f.fact} onChange={(e) => set('fact', e.target.value)} /></div>
          <div><label className="label" htmlFor="op">Operator</label><select id="op" className="input" value={f.op} onChange={(e) => set('op', e.target.value)}>{OPS.map((o) => <option key={o}>{o}</option>)}</select></div>
          <div><label className="label" htmlFor="vk">Value type</label><select id="vk" className="input" value={f.valueKind} onChange={(e) => set('valueKind', e.target.value)}><option value="number">number</option><option value="text">text</option><option value="fact">fact ref</option></select></div>
          <div><label className="label" htmlFor="val">Value</label><input id="val" className="input font-mono" value={f.value} onChange={(e) => set('value', e.target.value)} /></div>
        </div>
        <div className="col-span-2"><label className="label" htmlFor="fix">Fix instruction shown to institutions</label><textarea id="fix" rows={2} className="input" value={f.fix_hint} onChange={(e) => set('fix_hint', e.target.value)} /></div>
        <div><label className="label" htmlFor="miss">If value cannot be read</label><select id="miss" className="input" value={f.on_missing_fact} onChange={(e) => set('on_missing_fact', e.target.value)}><option value="manual_review">Manual review</option><option value="fail">Treat as failed</option><option value="skip">Skip rule</option></select></div>
        <label className="text-xs flex items-center gap-2 mt-5"><input type="checkbox" checked={f.is_active} onChange={(e) => set('is_active', e.target.checked)} />Active</label>
        {rule && <div className="col-span-2"><label className="label" htmlFor="why">Reason for change (audited, required)</label><input id="why" className="input" placeholder="e.g. APH 2027-28 revised land norms" value={f.reason} onChange={(e) => set('reason', e.target.value)} /></div>}
      </div>
      {error && <p className="text-xs text-rose-600 mt-3" role="alert">{error}</p>}
      <div className="flex justify-end gap-2 mt-4">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" busy={busy} disabled={rule ? f.reason.trim().length < 3 : !f.rule_code} onClick={save}>Save{rule ? ' new version' : ''}</Button>
      </div>
    </Modal>
  );
};

export const CompliancePage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [rules, setRules] = useState<ComplianceRule[] | null>(null);
  const [editing, setEditing] = useState<ComplianceRule | 'new' | null>(null);
  const [history, setHistory] = useState<{ rule: ComplianceRule; items: any[] } | null>(null);

  const load = () => complianceApi.getRules(isAdmin).then(setRules);
  useEffect(() => { load(); }, [isAdmin]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">{isAdmin ? 'Rules Engine' : 'AICTE Checklist & Rules'}</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Configurable rules derived from the Approval Process Handbook. {isAdmin ? 'Edits create a new version and are recorded in the audit ledger — no code change needed.' : 'Thresholds are prototype defaults; AICTE configures the current handbook values.'}
          </p>
        </div>
        {isAdmin && <Button variant="primary" onClick={() => setEditing('new')}><Plus className="w-4 h-4" />New rule</Button>}
      </div>

      {!rules ? <div className="flex justify-center p-10"><Spinner /></div> : (
        <div className="grid md:grid-cols-2 gap-4">
          {rules.map((r) => (
            <Card key={r.id} title={<span>{r.title} {!r.is_active && <Pill>inactive</Pill>}</span>} actions={<Pill tone="indigo">{r.rule_code} · v{r.version}</Pill>}>
              <p className="text-xs text-slate-600">{r.description}</p>
              <p className="text-[11px] font-mono text-slate-500 mt-2 bg-slate-50 rounded-lg p-2">{describe(r)}</p>
              <div className="flex flex-wrap items-center gap-1.5 mt-2">
                <Pill tone={r.severity === 'critical' ? 'rose' : r.severity === 'warning' ? 'amber' : 'sky'}>{r.severity}</Pill>
                <Pill>{r.category}</Pill>
                <span className="text-[11px] text-slate-500">applies to: {r.applies_to?.length ? r.applies_to.join(', ') : 'all categories'}</span>
              </div>
              {r.conditions.fix_hint && <p className="text-[11px] text-slate-500 mt-2"><span className="font-semibold">Fix hint:</span> {r.conditions.fix_hint}</p>}
              {isAdmin && (
                <div className="flex gap-2 mt-3">
                  <Button onClick={() => setEditing(r)}><Pencil className="w-3.5 h-3.5" />Edit</Button>
                  <Button variant="ghost" onClick={async () => setHistory({ rule: r, items: await complianceApi.history(r.id) })}><History className="w-3.5 h-3.5" />History</Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {editing && <RuleEditor rule={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
      {history && (
        <Modal title={`History of ${history.rule.rule_code}`} onClose={() => setHistory(null)}>
          {history.items.length === 0 ? <p className="text-xs text-slate-500">Seeded default (no edits yet).</p> : (
            <ul className="space-y-2 text-xs">
              {history.items.map((h, i) => (
                <li key={i} className="border-b border-slate-100 pb-2">
                  <p className="font-semibold">{h.action === 'RULE_CREATED' ? 'Created' : `v${h.details.from_version} → v${h.details.to_version}`} · {fmtDate(h.at)}</p>
                  {h.details.reason && <p className="text-slate-600">Reason: {h.details.reason}</p>}
                  {h.details.changes?.conditions?.check && <p className="font-mono text-[11px] text-slate-500">{JSON.stringify(h.details.changes.conditions.check)}</p>}
                </li>
              ))}
            </ul>
          )}
        </Modal>
      )}
    </div>
  );
};
