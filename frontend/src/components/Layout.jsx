import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, Search, Activity, MapPin, Users, Globe, Mail, MessageSquare, Bell, BookOpen, Cpu, Settings,
  Sun, Moon, LogOut, Menu, X, DollarSign, FlaskConical,
} from "lucide-react";
import { api, setToken } from "@/lib/api";

const NAV = [
  ["/", "Dashboard", LayoutDashboard, "dashboard"],
  ["/search", "New Search", Search, "new-search"],
  ["/live", "Live Agent Activity", Activity, "live-agent"],
  ["/coverage", "Geographic Coverage", MapPin, "coverage"],
  ["/prospects", "Prospects", Users, "prospects"],
  ["/assessments", "Website Assessments", Globe, "assessments"],
  ["/campaigns", "Email Campaigns", Mail, "campaigns"],
  ["/replies", "Replies", MessageSquare, "replies"],
  ["/notifications", "Notifications", Bell, "notifications"],
  ["/services", "Service Catalogue", BookOpen, "services"],
  ["/integrations", "Integrations", Cpu, "integrations"],
  ["/settings", "Settings", Settings, "settings"],
];

const AgentPill = ({ st }) => {
  const state = st?.state;
  const alive = st?.worker_alive;
  const color = !alive ? "text-red-500" : state === "running" ? "text-emerald-500" : state === "paused" ? "text-amber-500" : "text-slate-400";
  const text = !alive ? "Worker offline" : state === "running" ? (st.active_searches ? "Agent working" : "Agent idle") : `Agent ${state}`;
  return (
    <span data-testid="agent-status-pill" className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium">
      <span className={`h-2 w-2 rounded-full bg-current ${color} ${alive && state === "running" ? "pulse-dot" : ""}`} />
      {text}
    </span>
  );
};

export default function Layout() {
  const nav = useNavigate();
  const [dark, setDark] = useState(() => localStorage.getItem("bc_theme") !== "light");
  const [open, setOpen] = useState(false);
  const [st, setSt] = useState(null);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("bc_theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    const load = () => {
      api.get("/agent/state").then((r) => setSt(r.data)).catch(() => {});
      api.get("/stats").then((r) => setStats(r.data)).catch(() => {});
    };
    load();
    const t = setInterval(load, 8000);
    window.addEventListener("agent-changed", load);
    return () => {
      clearInterval(t);
      window.removeEventListener("agent-changed", load);
    };
  }, []);

  const logout = () => {
    setToken(null);
    nav("/login");
  };

  return (
    <div className="flex min-h-screen">
      <aside className={`fixed inset-y-0 left-0 z-40 w-64 transform bg-[hsl(var(--sidebar))] text-slate-200 transition-transform lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-16 items-center gap-3 border-b border-white/5 px-5">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-cyan-500 font-display text-sm font-extrabold text-slate-950">BC</div>
          <div>
            <div className="font-display text-sm font-bold leading-tight text-white">Bright Coda</div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-slate-400">Local Business Scout</div>
          </div>
          <button className="ml-auto lg:hidden" onClick={() => setOpen(false)} data-testid="sidebar-close"><X className="h-5 w-5" /></button>
        </div>
        <nav className="space-y-0.5 overflow-y-auto p-3" style={{ maxHeight: "calc(100vh - 64px)" }}>
          {NAV.map(([to, name, Icon, id]) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)} data-testid={`sidebar-nav-${id}`}
              className={({ isActive }) => `flex items-center gap-3 rounded-md px-3 py-2 text-[13px] transition-colors ${isActive ? "bg-cyan-500/15 text-cyan-300" : "text-slate-400 hover:bg-white/5 hover:text-white"}`}>
              <Icon className="h-4 w-4" />
              <span className="flex-1">{name}</span>
              {id === "replies" && stats?.unhandled_replies > 0 && (
                <span data-testid="sidebar-replies-badge" className="rounded-full bg-emerald-500 px-1.5 text-[10px] font-bold text-white">{stats.unhandled_replies}</span>
              )}
              {id === "notifications" && stats?.unread_notifications > 0 && (
                <span className="rounded-full bg-cyan-500/30 px-1.5 text-[10px] font-bold text-cyan-200">{stats.unread_notifications}</span>
              )}
            </NavLink>
          ))}
        </nav>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setOpen(false)} />}
      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur-xl md:px-8">
          <button className="lg:hidden" onClick={() => setOpen(true)} data-testid="sidebar-open"><Menu className="h-5 w-5" /></button>
          <AgentPill st={st} />
          {st?.test_mode && (
            <span data-testid="test-mode-pill" className="hidden items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-600 dark:text-amber-400 sm:flex">
              <FlaskConical className="h-3 w-3" /> Test mode
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <span data-testid="cost-tracker-widget" className="hidden items-center gap-1 rounded-full border px-3 py-1 font-mono text-xs md:flex" title="Estimated AI spend">
              <DollarSign className="h-3 w-3" />{(stats?.ai_cost_usd ?? 0).toFixed(2)} AI
            </span>
            <button data-testid="notification-bell" onClick={() => nav("/notifications")} className="relative rounded-md p-2 hover:bg-accent">
              <Bell className="h-4 w-4" />
              {stats?.unread_notifications > 0 && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-cyan-500" />}
            </button>
            <button data-testid="theme-toggle-button" onClick={() => setDark(!dark)} className="rounded-md p-2 hover:bg-accent">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            <button data-testid="logout-button" onClick={logout} className="rounded-md p-2 hover:bg-accent" title="Sign out"><LogOut className="h-4 w-4" /></button>
          </div>
        </header>
        <main className="min-w-0 flex-1 px-4 py-8 md:px-8 lg:px-10">
          <Outlet context={{ stats, st }} />
        </main>
      </div>
    </div>
  );
}
