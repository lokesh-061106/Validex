import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, FileCheck2, ShieldCheck, Camera, History, LogOut, Building2, Cpu, Settings, Bell, FolderOpen, CalendarClock, GitBranch, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';

export const Sidebar: React.FC<{ mobileOpen?: boolean; onNavigate?: () => void }> = ({ mobileOpen = false, onNavigate }) => {
  const { user, logout } = useAuth();
  const role = user?.role;

  const navItems =
    role === 'institution'
      ? [
          { to: '/', label: 'My Applications', icon: FolderOpen },
          { to: '/notices', label: 'Clarification Requests', icon: Bell },
          { to: '/deadlines', label: 'Deadlines & Expiry', icon: CalendarClock },
          { to: '/compliance', label: 'Compliance Checklist', icon: ShieldCheck },
        ]
      : [
          { to: '/', label: 'Dashboard', icon: LayoutDashboard },
          { to: '/applications', label: 'Triage Queue', icon: FileCheck2 },
          { to: '/deadlines', label: 'Deadlines & EVC', icon: CalendarClock },
          { to: '/compliance', label: role === 'admin' ? 'Rules Engine' : 'Norms & Rules', icon: ShieldCheck },
          { to: '/infrastructure', label: 'Infra CV Studio', icon: Camera },
          { to: '/audit', label: 'Audit Ledger', icon: History },
          ...(role === 'admin' ? [{ to: '/admin', label: 'Administration', icon: Settings }] : []),
          ...(role === 'admin' ? [{ to: '/workflow', label: 'Workflow Config', icon: GitBranch }] : []),
        ];

  return (
    <aside className={`fixed inset-y-0 left-0 z-50 flex w-[min(18rem,88vw)] shrink-0 flex-col justify-between border-r border-t-4 border-t-[#e68a21] border-slate-200 bg-white shadow-sm transition-transform md:static md:z-30 md:w-64 md:translate-x-0 ${mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}`}>
      <div>
        <div className="p-4 md:p-6 border-b border-slate-100 flex items-center space-x-3">
          <div className="w-10 h-10 rounded-lg bg-[#10395f] flex items-center justify-center shadow-sm">
            <Cpu className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-slate-900 text-base tracking-tight flex items-center gap-1.5">
              Validex <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200 font-mono font-semibold">SIH26262</span>
            </h1>
            <p className="text-xs text-slate-500 font-medium">{role === 'institution' ? 'Institution Portal' : role === 'admin' ? 'Platform Administration' : role === 'supervisor' ? 'Supervisor Workspace' : role === 'approver' ? 'Approval Workspace' : 'Review Workspace'} · Independent prototype</p>
          </div>
          <button type="button" aria-label="Close navigation menu" onClick={onNavigate} className="ml-auto rounded-lg p-2 text-slate-500 hover:bg-slate-100 md:hidden"><X className="h-5 w-5" /></button>
        </div>

        {user?.institution_name && (
          <div className="mx-4 mt-4 p-2.5 rounded-lg bg-slate-50 border border-slate-200 flex items-center gap-2">
            <Building2 className="w-4 h-4 text-indigo-600 shrink-0" />
            <p className="text-xs text-slate-700 truncate font-medium">{user.institution_name}</p>
          </div>
        )}

        <nav className="p-4 space-y-1 mt-1" aria-label="Main">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                onClick={onNavigate}
                className={({ isActive }) =>
                  `flex items-center space-x-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                    isActive ? 'bg-[#155a8a] text-white shadow-sm font-semibold' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100/80'
                  }`
                }
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </div>

      <div className="p-4 border-t border-slate-100">
        <div className="flex items-center justify-between p-2 rounded-xl bg-slate-50 border border-slate-200">
          <div className="flex items-center space-x-2.5 truncate">
            <div className="w-8 h-8 rounded-lg bg-indigo-100 text-indigo-700 font-bold text-xs flex items-center justify-center shrink-0">
              {user?.full_name ? user.full_name[0] : 'U'}
            </div>
            <div className="truncate">
              <p className="text-xs font-semibold text-slate-800 truncate">{user?.full_name}</p>
              <p className="text-[10px] uppercase font-mono tracking-wider text-indigo-600 font-bold">{user?.role}</p>
            </div>
          </div>
          <button onClick={logout} title="Log out" aria-label="Log out" className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors cursor-pointer">
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </aside>
  );
};
