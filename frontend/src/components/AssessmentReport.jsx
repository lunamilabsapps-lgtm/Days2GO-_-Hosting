import { CheckCircle2, AlertCircle, Lightbulb, ExternalLink } from "lucide-react";
import { GradeBadge, StatusBadge } from "@/components/common";
import { fmtDate, label, shotUrl } from "@/lib/api";

export default function AssessmentReport({ a }) {
  if (!a) return <div className="text-sm text-muted-foreground">Not assessed yet.</div>;
  const q = Object.entries(a.quality || {});
  return (
    <div className="space-y-6" data-testid="assessment-report">
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={a.presence} testid="assessment-presence" />
        <GradeBadge grade={a.grade} score={a.score} testid="assessment-grade" />
        {a.website_changed && <StatusBadge status="website changed since last assessment" tone="info" />}
        <span className="text-xs text-muted-foreground">Assessed {fmtDate(a.assessed_at)}{a.model ? ` · ${a.model}` : ""}</span>
        {a.final_url && <a href={a.final_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-primary">{a.final_url}<ExternalLink className="h-3 w-3" /></a>}
      </div>
      {a.summary && <p className="text-sm leading-relaxed">{a.summary}</p>}
      {a.presence_note && <p className="rounded-md bg-muted/60 p-3 text-xs">{a.presence_note}</p>}
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          <div>
            <div className="eyebrow mb-2">Verified issues (with evidence)</div>
            <div className="space-y-2">
              {(a.verified_issues || []).map((i, k) => (
                <div key={k} className="rounded-md border border-red-500/20 bg-red-500/5 p-3 text-sm">
                  <div className="flex gap-2 font-medium"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />{i.issue}</div>
                  <div className="mt-1 pl-6 text-xs text-muted-foreground">Evidence: {i.evidence}</div>
                  {i.commercial_impact && <div className="mt-1 pl-6 text-xs">Why it matters: {i.commercial_impact}</div>}
                </div>
              ))}
              {!a.verified_issues?.length && <div className="text-xs text-muted-foreground">No verified issues.</div>}
            </div>
          </div>
          <div>
            <div className="eyebrow mb-2">Potential improvements (not verified)</div>
            <ul className="space-y-1 text-sm">{(a.potential_improvements || []).map((p, k) => <li key={k} className="flex gap-2"><Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" /><span>{p.improvement}<span className="text-muted-foreground"> — {p.reason}</span></span></li>)}</ul>
          </div>
          <div>
            <div className="eyebrow mb-2">Matched Bright Coda opportunities</div>
            <div className="space-y-2">{(a.opportunities || []).map((o, k) => (
              <div key={k} className="flex items-start justify-between gap-3 rounded-md border p-3 text-sm">
                <div><div className="flex items-center gap-2 font-medium"><CheckCircle2 className="h-4 w-4 text-emerald-500" />{o.service_name}</div><div className="mt-1 text-xs text-muted-foreground">{o.reason}</div></div>
                <span className="font-mono text-xs">{o.strength}</span>
              </div>))}
            </div>
          </div>
          {q.length > 0 && (
            <div>
              <div className="eyebrow mb-2">Website quality</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {q.map(([k, v]) => (
                  <div key={k} className="rounded-md bg-muted/50 p-2.5 text-xs">
                    <div className="flex justify-between font-medium capitalize"><span>{label(k)}</span><span className="font-mono">{v?.rating ?? "n/a"}{v?.rating ? "/10" : ""}</span></div>
                    <div className="mt-1 text-muted-foreground">{v?.evidence}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="space-y-4">
          {a.screenshot && <img src={shotUrl(a.screenshot)} alt="Website screenshot" className="w-full rounded-md border" data-testid="assessment-screenshot" />}
          <div className="rounded-md bg-muted/50 p-3 text-xs">
            <div className="eyebrow mb-2">Technical checks</div>
            {Object.entries(a.technical || {}).map(([k, v]) => <div key={k} className="flex justify-between gap-2 py-0.5"><span className="text-muted-foreground">{label(k)}</span><span className="truncate font-mono">{String(v)}</span></div>)}
            {a.features && ["has_viewport_meta", "forms", "has_contact_form", "tel_links", "booking_signals", "ordering_signals", "builder", "copyright_year", "uses_https"].map((k) => (
              <div key={k} className="flex justify-between gap-2 py-0.5"><span className="text-muted-foreground">{label(k)}</span><span className="truncate font-mono">{Array.isArray(a.features[k]) ? a.features[k].join(", ") || "none" : String(a.features[k] ?? "—")}</span></div>
            ))}
          </div>
          {a.score_factors && (
            <div className="rounded-md bg-muted/50 p-3 text-xs">
              <div className="eyebrow mb-2">Score factors</div>
              {Object.entries(a.score_factors).map(([k, v]) => (
                <div key={k} className="py-1"><div className="flex justify-between"><span className="capitalize">{label(k)}</span><span className="font-mono">{v}</span></div><div className="mt-1 h-1 rounded bg-muted"><div className="h-1 rounded bg-primary" style={{ width: `${v}%` }} /></div></div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
