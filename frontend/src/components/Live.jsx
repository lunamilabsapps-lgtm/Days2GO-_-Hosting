import { Globe, Search, Database, Copy, CheckCircle2, ScanLine, Lightbulb, Contact, PenLine, ShieldCheck, Send, ArrowRight, AlertTriangle, MessageSquareReply, Pause, Play, Square, MapPin, Gauge } from "lucide-react";
import { Button } from "@/components/ui/button";
import { GradeBadge, StatusBadge } from "@/components/common";
import { fmtTime, label, shotUrl, api, errMsg } from "@/lib/api";
import { toast } from "sonner";

const STAGES = [
  ["searching", "Search"], ["opening_website", "Open site"], ["analysing_website", "Analyse"], ["identifying_opportunities", "Opportunities"],
  ["finding_contacts", "Contacts"], ["scoring", "Score"], ["generating_email", "Email"], ["checking_eligibility", "Eligibility"],
];

export const KIND_ICON = {
  searching: Search, discovered: MapPin, dedupe: Database, duplicate: Copy, accepted: CheckCircle2, opening: Globe,
  analysing: ScanLine, opportunities: Lightbulb, contacts: Contact, email: PenLine, eligibility: ShieldCheck, hold: Pause,
  sent: Send, next: ArrowRight, error: AlertTriangle, reply: MessageSquareReply, scored: Gauge, zone_done: CheckCircle2,
};

export function AgentControls({ state, onChange }) {
  const act = async (a) => {
    try {
      const r = await api.post(`/agent/${a}`);
      onChange?.(r.data);
      window.dispatchEvent(new Event("agent-changed"));
      toast.success(`Agent ${a === "resume" ? "resumed" : a === "pause" ? "paused" : "stopped"}`);
    } catch (e) {
      toast.error(errMsg(e));
    }
  };
  return (
    <div className="flex gap-2">
      {state === "running" ? (
        <Button data-testid="agent-pause-button" variant="outline" size="sm" onClick={() => act("pause")}><Pause className="mr-1 h-4 w-4" />Pause</Button>
      ) : (
        <Button data-testid="agent-resume-button" size="sm" onClick={() => act("resume")}><Play className="mr-1 h-4 w-4" />Resume</Button>
      )}
      <Button data-testid="agent-stop-button" variant="outline" size="sm" className="text-red-500" onClick={() => window.confirm("Stop all running searches?") && act("stop")}>
        <Square className="mr-1 h-4 w-4" />Stop
      </Button>
    </div>
  );
}

function Pipeline({ stage }) {
  const idx = STAGES.findIndex(([k]) => k === stage);
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="live-stage-pipeline">
      {STAGES.map(([k, n], i) => (
        <span key={k} className={`rounded px-2 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors ${i === idx ? "bg-primary text-primary-foreground" : i < idx ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}`}>{n}</span>
      ))}
    </div>
  );
}

export function LiveBusinessCard({ slot, big = true }) {
  const b = slot?.business;
  const idle = !slot || slot.stage === "idle";
  if (idle || (!b && slot.stage !== "searching")) {
    return (
      <div data-testid="live-prospect-card" className="panel grid-bg flex min-h-[220px] flex-col items-center justify-center p-8 text-center">
        <div className="font-display text-lg font-semibold">Waiting for work</div>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">Start a search and the agent will show each business it researches here.</p>
      </div>
    );
  }
  if (!b) {
    return (
      <div data-testid="live-prospect-card" className="panel relative overflow-hidden p-6">
        <div className="eyebrow">Discovery engine</div>
        <div className="mt-2 font-display text-2xl font-bold">Searching {slot.zone}</div>
        <p className="mt-1 text-sm text-muted-foreground">Querying OpenStreetMap for businesses in this zone…</p>
      </div>
    );
  }
  return (
    <div data-testid="live-prospect-card" className="panel relative overflow-hidden fade-in" key={b.id}>
      <div className={`grid gap-0 ${big ? "md:grid-cols-[1.1fr_1fr]" : ""}`}>
        <div className="min-w-0 space-y-4 p-6">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="eyebrow flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-cyan-500 pulse-dot text-cyan-500" />Researching now</div>
              <h2 data-testid="live-business-name" className="mt-2 truncate font-display text-2xl font-bold md:text-3xl">{b.name}</h2>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <span className="rounded bg-muted px-2 py-0.5 text-xs capitalize">{b.category}</span>
                <span>{b.suburb}{b.city ? `, ${b.city}` : ""}</span>
              </div>
            </div>
            <GradeBadge grade={slot.grade} score={slot.score} testid="live-grade-badge" />
          </div>
          {b.website ? (
            <a href={b.website} target="_blank" rel="noreferrer" className="block truncate font-mono text-xs text-primary hover:underline" data-testid="live-website-link">{b.website}</a>
          ) : (
            <div className="font-mono text-xs text-amber-500">No website listed</div>
          )}
          <Pipeline stage={slot.stage} />
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-md bg-muted/60 p-3"><div className="eyebrow">Current stage</div><div data-testid="live-current-stage" className="mt-1 font-medium capitalize">{label(slot.stage)}</div></div>
            <div className="rounded-md bg-muted/60 p-3"><div className="eyebrow">Contact</div><div className="mt-1 font-medium">{slot.contact_status || "pending"}</div></div>
            <div className="col-span-2 rounded-md bg-muted/60 p-3"><div className="eyebrow">Email</div><div className="mt-1 font-medium capitalize">{label(slot.email_status || "pending")}</div></div>
          </div>
          {slot.findings?.length > 0 && (
            <div>
              <div className="eyebrow mb-2">Verified findings</div>
              <ul className="space-y-1 text-sm">{slot.findings.map((f, i) => <li key={i} className="flex gap-2"><span className="text-primary">›</span>{f}</li>)}</ul>
            </div>
          )}
        </div>
        {big && (
          <div className="relative min-h-[240px] border-t bg-muted/40 md:border-l md:border-t-0">
            {slot.screenshot ? (
              <img data-testid="live-screenshot" src={shotUrl(slot.screenshot)} alt="Website screenshot" className="absolute inset-0 h-full w-full object-cover object-top" />
            ) : (
              <div className="absolute inset-0 grid place-items-center p-6 text-center text-xs text-muted-foreground">
                {b.website ? "Capturing website preview…" : "No website to preview"}
              </div>
            )}
            {["opening_website", "analysing_website"].includes(slot.stage) && <div className="pointer-events-none absolute inset-x-0 top-0 scan-line" />}
          </div>
        )}
      </div>
    </div>
  );
}

export function Timeline({ events, max = 80, filter = "all" }) {
  const groups = { all: null, discovery: ["searching", "discovered", "dedupe", "duplicate", "accepted", "zone_done", "coverage_reused"],
    research: ["opening", "analysing", "opportunities", "contacts", "scored"], email: ["email", "eligibility", "hold", "sent", "reply", "skip_email"], errors: ["error", "robots"] };
  const list = events.filter((e) => !groups[filter] || groups[filter].includes(e.kind)).slice(0, max);
  return (
    <ol className="space-y-0.5" data-testid="activity-timeline">
      {list.map((e) => {
        const Icon = KIND_ICON[e.kind] || ArrowRight;
        const tone = e.level === "error" ? "text-red-500" : e.level === "warn" ? "text-amber-500" : e.level === "success" ? "text-emerald-500" : e.kind === "duplicate" ? "text-muted-foreground" : "text-primary";
        return (
          <li key={e.seq} className="flex items-start gap-3 rounded-md px-2 py-1.5 text-sm fade-in hover:bg-accent/50" data-testid="timeline-event">
            <span className="w-20 shrink-0 whitespace-nowrap pt-0.5 font-mono text-[10px] text-muted-foreground">{fmtTime(e.created_at)}</span>
            <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${tone}`} />
            <span className={`min-w-0 break-words ${e.kind === "duplicate" ? "text-muted-foreground" : ""}`}>{e.message}</span>
          </li>
        );
      })}
      {!list.length && <li className="py-6 text-center text-sm text-muted-foreground">No activity yet.</li>}
    </ol>
  );
}

export const SearchProgress = ({ s, onAction }) => {
  const p = s.progress || {};
  const pct = p.zones_total ? Math.round((p.zones_done / p.zones_total) * 100) : 0;
  return (
    <div className="rounded-lg border p-4" data-testid={`search-row-${s.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium capitalize">{s.category}{s.subcategory ? ` · ${s.subcategory}` : ""} in {s.city}</div>
          <div className="text-xs text-muted-foreground">{p.zones_done}/{p.zones_total} zones · {p.new} new · {p.duplicates} duplicates · {p.assessed} assessed · {s.qualified ?? 0} qualified · {s.mode === "outreach" ? "outreach" : "research & draft"} mode</div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={s.status} testid={`search-status-${s.id}`} />
          {onAction && s.status === "running" && <Button size="sm" variant="outline" data-testid={`search-pause-${s.id}`} onClick={() => onAction(s.id, "pause")}>Pause</Button>}
          {onAction && ["paused", "stopped"].includes(s.status) && <Button size="sm" variant="outline" data-testid={`search-resume-${s.id}`} onClick={() => onAction(s.id, "resume")}>Resume</Button>}
          {onAction && ["running", "paused"].includes(s.status) && <Button size="sm" variant="ghost" className="text-red-500" data-testid={`search-stop-${s.id}`} onClick={() => onAction(s.id, "stop")}>Stop</Button>}
          {onAction && s.status === "completed" && <Button size="sm" variant="outline" data-testid={`search-rerun-${s.id}`} onClick={() => onAction(s.id, "rerun")}>Rediscover</Button>}
        </div>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} /></div>
      {s.current_zone && s.status === "running" && <div className="mt-2 text-xs text-muted-foreground">Current zone: {s.current_zone}</div>}
    </div>
  );
};
