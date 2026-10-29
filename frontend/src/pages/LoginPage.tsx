import React, { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Cpu, ShieldCheck, Building2, UserCog, Eye, LockKeyhole, Landmark } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { authApi, errorMessage } from '../api/client';
import { Button } from '../components/ui';
import { PwaInstallButton } from '../components/PwaInstallButton';

// Synthetic accounts available in the non-production seeded environment.
const SAMPLE_ACCOUNTS = [
  { group: 'Review and administration', icon: ShieldCheck, items: [
    { label: 'Scrutiny Officer', email: 'scrutiny@aicte-india.org', pass: 'scrutiny123' },
    { label: 'Admin (rules, users)', email: 'admin@aicte-india.org', pass: 'admin123' },
    { label: 'Expert Committee', email: 'expert@aicte-india.org', pass: 'expert123' },
    { label: 'Approving Officer', email: 'approver@aicte-india.org', pass: 'approver123' },
    { label: 'Supervisor', email: 'supervisor@aicte-india.org', pass: 'supervisor123' },
  ] },
  { group: 'Institutions', icon: Building2, items: [
    { label: 'Apex (clean)', email: 'principal@apex.edu.in', pass: 'apex123' },
    { label: 'Zenith (problems)', email: 'principal@zenith.edu.in', pass: 'zenith123' },
    { label: 'Crescent', email: 'principal@crescent.edu.in', pass: 'crescent123' },
  ] },
];

export const LoginPage: React.FC = () => {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [institution, setInstitution] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const doLogin = async (e?: string, p?: string) => {
    setBusy(true);
    setError('');
    try {
      await login(e ?? email, p ?? password);
      navigate('/');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const doRegister = async () => {
    setBusy(true);
    setError('');
    try {
      await authApi.register({ email, password, full_name: fullName, institution_name: institution });
      await doLogin(email, password);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#f2f5f8] px-4 py-5 sm:px-6 sm:py-10">
      <div className="mx-auto max-w-6xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_18px_55px_-32px_rgba(12,49,84,.35)]">
        <div className="h-1.5 bg-gradient-to-r from-[#e68a21] via-white to-[#178457]" aria-hidden="true" />
        <header className="flex flex-col gap-3 border-b border-slate-200 bg-[#10395f] px-5 py-4 text-white sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/25"><Cpu className="h-5 w-5" /></div>
            <div>
              <h1 className="text-lg font-bold leading-tight tracking-wide">VALIDEX <span className="text-amber-300">·</span> SIH26262</h1>
              <p className="text-xs text-blue-100">AICTE application workflow prototype</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 self-start sm:self-auto">
            <div className="flex items-center gap-2 rounded-md border border-white/20 bg-white/10 px-3 py-1.5 text-[11px] font-semibold tracking-wide text-blue-50">
              <Landmark className="h-3.5 w-3.5 text-amber-300" /> INDEPENDENT PROTOTYPE
            </div>
            <PwaInstallButton />
          </div>
        </header>

        <div className="grid md:grid-cols-2">
        <section className="p-5 sm:p-8 lg:p-10">
          <div className="mb-6 border-b border-slate-200 pb-5">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-[.16em] text-[#a35d13]">01 <span className="mx-1 text-slate-300">/</span> Workspace access</p>
            <h2 className="text-2xl font-bold tracking-tight text-[#173b5c]">Sign in to Validex</h2>
            <p className="mt-1.5 text-sm leading-6 text-slate-600">Use your institution or officer account to continue to the approval workspace.</p>
          </div>

          <div className="mb-5 flex gap-1 rounded-lg border border-slate-200 bg-slate-100 p-1 text-xs font-semibold">
            {(['login', 'register'] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)} className={`flex-1 rounded-md py-2.5 transition-colors cursor-pointer ${mode === m ? 'bg-white text-[#123e63] shadow-sm ring-1 ring-slate-200' : 'text-slate-600 hover:text-slate-900'}`}>
                {m === 'login' ? 'Sign in' : 'Register institution'}
              </button>
            ))}
          </div>

          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              mode === 'login' ? doLogin() : doRegister();
            }}
          >
            {mode === 'register' && (
              <>
                <label className="block text-xs font-semibold text-slate-700">Full name<input required value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Enter your full name" aria-label="Full name" className="input mt-1.5" /></label>
                <label className="block text-xs font-semibold text-slate-700">Institution name<input required value={institution} onChange={(e) => setInstitution(e.target.value)} placeholder="Name as registered with AICTE" aria-label="Institution name" className="input mt-1.5" /></label>
              </>
            )}
            <label className="block text-xs font-semibold text-slate-700">Email address<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@institution.edu.in" aria-label="Email" className="input mt-1.5" autoComplete="username" /></label>
            <label className="block text-xs font-semibold text-slate-700">Password<input required type="password" minLength={mode === 'register' ? 8 : 1} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password" aria-label="Password" className="input mt-1.5" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} /></label>
            {error && <p className="text-xs text-rose-600 font-medium" role="alert">{error}</p>}
            <Button type="submit" variant="primary" busy={busy} className="w-full justify-center py-3 !bg-[#124d7b] hover:!bg-[#0d3c61] !shadow-none">
              <LockKeyhole className="mr-2 h-4 w-4" />
              {mode === 'login' ? 'Sign in' : 'Create institution account'}
            </Button>
            {mode === 'register' && <p className="text-[11px] text-slate-500">AICTE staff accounts in this prototype are provisioned by an administrator.</p>}
          </form>
        </section>

        <aside className="border-t border-slate-200 bg-[#f7f9fb] p-5 sm:p-8 lg:p-10 md:border-l md:border-t-0">
          <div className="mb-5 border-b border-slate-200 pb-4">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-[.16em] text-[#a35d13]">02 <span className="mx-1 text-slate-300">/</span> Workspace access</p>
            <h2 className="flex items-center gap-2 text-lg font-bold text-[#173b5c]"><Eye className="h-4 w-4 text-[#1769a2]" /> Sample access profiles</h2>
            <p className="mt-1 text-xs leading-5 text-slate-600">Evaluation profiles use synthetic records. Select a role to open its workspace.</p>
          </div>
          {SAMPLE_ACCOUNTS.map((g) => (
            <div key={g.group} className="mb-4">
              <p className="text-[11px] uppercase font-bold tracking-wider text-[#355c78] mb-2 flex items-center gap-1.5"><g.icon className="w-3.5 h-3.5" /> {g.group}</p>
              <div className="grid grid-cols-1 gap-2">
                {g.items.map((d) => (
                  <button key={d.email} onClick={() => doLogin(d.email, d.pass)} disabled={busy} className="flex min-h-12 items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left transition-colors hover:border-[#7ea6c3] hover:bg-[#f3f8fb] cursor-pointer disabled:opacity-50">
                    <span className="text-xs font-semibold text-slate-800 flex items-center gap-2"><UserCog className="w-3.5 h-3.5 text-[#1769a2] shrink-0" />{d.label}</span>
                    <span className="truncate text-[10px] text-slate-500 font-mono sm:text-[11px]">{d.email}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </aside>
        </div>
        <footer className="border-t border-slate-200 bg-white px-5 py-3 text-center text-[10px] leading-5 text-slate-500 sm:px-8 sm:text-left">
          Validex is an independent SIH26262 portal model and is not an official AICTE service. Evaluation profiles use synthetic records. On iPhone or iPad, use Share → Add to Home Screen.
        </footer>
      </div>
    </main>
  );
};
