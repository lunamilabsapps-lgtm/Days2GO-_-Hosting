import { CheckCircle2, MessageSquareReply } from "lucide-react";
import { label } from "@/lib/api";

const GRADE = {
  A: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  B: "bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30",
  C: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30",
  D: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
};

export const GradeBadge = ({ grade, score, testid = "prospect-grade-badge" }) =>
  grade ? (
    <span data-testid={testid} className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-xs font-bold ${GRADE[grade]}`}>
      {grade}
      {score != null && <span className="font-medium opacity-80">{score}</span>}
    </span>
  ) : (
    <span className="text-xs text-muted-foreground">—</span>
  );

export const RepliedTag = ({ testid = "green-replied-tag" }) => (
  <span data-testid={testid} className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-1 text-[11px] font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
    <MessageSquareReply className="h-3 w-3" /> Replied
  </span>
);

const TONE = {
  good: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/25",
  info: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border-cyan-500/25",
  warn: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/25",
  bad: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/25",
  muted: "bg-muted text-muted-foreground border-border",
};
const STATUS_TONE = {
  running: "info", completed: "good", assessed: "good", delivered: "good", sent: "good", approved: "good", website_exists: "good",
  replied: "good", eligible: "good", paused: "warn", pending_approval: "warn", draft: "warn", pending: "muted", assessing: "info",
  stopped: "bad", failed: "bad", bounced: "bad", complained: "bad", ineligible: "bad", blocked: "bad", unsubscribed: "bad",
  no_website: "warn", no_website_listed: "warn", website_unavailable: "bad", social_media_only: "warn", under_construction: "warn",
  test_dry_run: "muted", test_sent: "info", searching: "info", needs_research: "warn", send_failed: "bad",
};

export const StatusBadge = ({ status, tone, testid }) => (
  <span data-testid={testid} className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-medium capitalize ${TONE[tone || STATUS_TONE[status] || "muted"]}`}>
    {label(status)}
  </span>
);

export const PageHeader = ({ eyebrow, title, desc, children }) => (
  <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between fade-in">
    <div>
      {eyebrow && <div className="eyebrow mb-2">{eyebrow}</div>}
      <h1 className="text-3xl font-extrabold tracking-tight md:text-4xl">{title}</h1>
      {desc && <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{desc}</p>}
    </div>
    {children && <div className="flex flex-wrap gap-2">{children}</div>}
  </div>
);

export const StatCard = ({ title, value, hint, icon: Icon, accent, testid }) => (
  <div data-testid={testid} className="panel group p-4 transition-colors hover:bg-accent/40 fade-in">
    <div className="flex items-center justify-between">
      <span className="eyebrow">{title}</span>
      {Icon && <Icon className={`h-4 w-4 ${accent || "text-muted-foreground"}`} />}
    </div>
    <div className="mt-3 font-display text-3xl font-bold tracking-tight">{value ?? "—"}</div>
    {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
  </div>
);

export const Empty = ({ icon: Icon = CheckCircle2, title, desc, children }) => (
  <div className="panel flex flex-col items-center justify-center px-6 py-14 text-center">
    <Icon className="mb-3 h-8 w-8 text-muted-foreground" />
    <div className="font-display text-lg font-semibold">{title}</div>
    {desc && <p className="mt-1 max-w-md text-sm text-muted-foreground">{desc}</p>}
    {children && <div className="mt-4">{children}</div>}
  </div>
);

export const Field = ({ label: l, children, hint }) => (
  <label className="block space-y-1.5">
    <span className="text-xs font-medium text-muted-foreground">{l}</span>
    {children}
    {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
  </label>
);

export const Section = ({ title, children, right, className = "" }) => (
  <div className={`panel p-5 ${className}`}>
    {(title || right) && (
      <div className="mb-4 flex items-center justify-between gap-2">
        <h3 className="font-display text-base font-semibold">{title}</h3>
        {right}
      </div>
    )}
    {children}
  </div>
);
