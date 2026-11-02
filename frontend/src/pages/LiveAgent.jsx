import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { Section, PageHeader } from "@/components/common";
import { LiveBusinessCard, Timeline, AgentControls } from "@/components/Live";
import { useLive } from "@/hooks/useLive";

export default function LiveAgent() {
  const { events, state, setState, connected } = useLive(300);
  const [filter, setFilter] = useState("all");
  const slots = (state?.current || []).filter((c) => c._id !== "slot0" && c.stage);
  const busy = slots.filter((c) => c.business && c.stage !== "idle").sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  const discovery = (state?.current || []).find((c) => c.stage === "searching" && !c.business);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow={connected ? "● live stream connected" : "○ reconnecting…"} title="Live Agent Activity" desc="Every event below comes from the background worker as it happens.">
        <AgentControls state={state?.state} onChange={setState} />
      </PageHeader>
      {!state?.worker_alive && state && <div className="panel border-red-500/40 p-4 text-sm text-red-500" data-testid="worker-offline-banner">Background worker is not reporting a heartbeat. Check the worker service.</div>}
      {state?.state !== "running" && state && <div className="panel border-amber-500/40 p-4 text-sm text-amber-600 dark:text-amber-400" data-testid="agent-paused-banner">Agent is {state.state}. Press Resume to continue from the last checkpoint.</div>}
      <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <div className="min-w-0 space-y-4">
          <LiveBusinessCard slot={busy[0] || discovery} />
          {busy.slice(1).map((s) => <LiveBusinessCard key={s.updated_at + (s.business?.id || "")} slot={s} big={false} />)}
          {discovery && busy.length > 0 && (
            <div className="panel p-4 text-sm"><span className="eyebrow mr-2">Discovery</span>Searching <b>{discovery.zone}</b></div>
          )}
        </div>
        <Section title="Activity timeline" right={
          <select className="native" value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="timeline-filter">
            <option value="all">All</option><option value="discovery">Discovery</option><option value="research">Research</option><option value="email">Email</option><option value="errors">Errors</option>
          </select>}>
          <div className="max-h-[70vh] overflow-y-auto pr-1"><Timeline events={events} max={300} filter={filter} /></div>
        </Section>
      </div>
    </div>
  );
}
