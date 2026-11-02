import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Mail, Play, Pause, Square, CheckCheck, Plus, FlaskConical } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, Section, GradeBadge, StatusBadge, Empty } from "@/components/common";
import { api, errMsg, fmtDate } from "@/lib/api";

export default function Campaigns() {
  const [drafts, setDrafts] = useState([]);
  const [camps, setCamps] = useState([]);
  const [status, setStatus] = useState("pending_approval");
  const [sel, setSel] = useState(new Set());
  const [name, setName] = useState("");
  const [open, setOpen] = useState(null);
  const [outs, setOuts] = useState([]);
  const [settings, setSettings] = useState(null);

  const load = () => {
    const req = (window.__draftsReq = (window.__draftsReq || 0) + 1);
    api.get(`/drafts?status=${status}`).then((r) => { if (req === window.__draftsReq) setDrafts(r.data); });
    api.get("/campaigns").then((r) => setCamps(r.data));
  };
  useEffect(() => { load(); }, [status]); // eslint-disable-line
  useEffect(() => { api.get("/settings").then((r) => setSettings(r.data)); const t = setInterval(() => api.get("/campaigns").then((r) => setCamps(r.data)), 10000); return () => clearInterval(t); }, []);
  useEffect(() => { if (open) api.get(`/campaigns/${open}/outbound`).then((r) => setOuts(r.data)); }, [open, camps]);

  const create = async () => {
    try {
      const r = await api.post("/campaigns", { name: name || `Campaign ${new Date().toLocaleDateString("en-AU")}`, draft_ids: [...sel] });
      toast.success(`Campaign created with ${r.data.added} email(s)`);
      setSel(new Set()); setName(""); load();
    } catch (e) { toast.error(errMsg(e)); }
  };
  const act = async (id, a) => {
    try { const r = await api.post(`/campaigns/${id}/${a}`); toast.success(a === "approve-all" ? `${r.data.approved} email(s) approved` : `Campaign ${{ start: "started", resume: "resumed", pause: "paused", stop: "stopped" }[a]}`); load(); } catch (e) { toast.error(errMsg(e)); }
  };
  const approve = async (id) => { try { await api.post(`/drafts/${id}/approve`); toast.success("Approved"); load(); } catch (e) { toast.error(errMsg(e)); } };
  const toggle = (id) => setSel((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const s = settings;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Outreach" title="Email Campaigns" desc="Nothing is ever sent just because it was generated. Review, approve, then run a campaign.">
        <Button variant="outline" data-testid="drafts-rewrite-button" onClick={async () => { toast.info("Rewriting unedited pending emails…"); try { const r = await api.post("/drafts/rewrite-pending"); toast.success(`${r.data.rewritten} email(s) rewritten`); load(); } catch (e) { toast.error(errMsg(e)); } }}>Rewrite pending emails</Button>
      </PageHeader>
      {s && (s.sending.test_mode ? (
        <div className="panel flex items-start gap-3 border-amber-500/40 p-4 text-sm" data-testid="campaign-test-mode-banner"><FlaskConical className="h-5 w-5 shrink-0 text-amber-500" /><div><b>Test mode is ON.</b> Campaigns send only to <span className="font-mono">{s.sending.test_recipient}</span>{s.resend.api_key_set ? "" : " — and since no Resend key is configured, sends are logged as dry runs only"}. Real prospects cannot be emailed until you switch test mode off in Settings.</div></div>
      ) : (!s.compliance.configured || !s.compliance.offer_reviewed || !s.resend.api_key_set) && (
        <div className="panel border-red-500/40 p-4 text-sm text-red-500" data-testid="campaign-setup-banner">Live sending is blocked until compliance settings, offer review, sender details and the Resend API key are configured.</div>
      ))}
      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Section title="Prepared emails" right={
          <select className="native" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="drafts-status-filter">
            {["pending_approval", "approved", "ineligible", "rejected", "sent", "blocked"].map((x) => <option key={x} value={x}>{x.replace("_", " ")}</option>)}
          </select>}>
          {!drafts.length ? <Empty icon={Mail} title="No emails here" desc="Personalised emails appear as the agent qualifies prospects." /> : (
            <div className="space-y-2">
              {drafts.map((d) => (
                <div key={d.id} className="rounded-lg border p-3" data-testid={`draft-row-${d.id}`}>
                  <div className="flex items-start gap-3">
                    {["pending_approval", "approved"].includes(d.status) && !d.campaign_id && <input type="checkbox" className="mt-1" checked={sel.has(d.id)} onChange={() => toggle(d.id)} data-testid={`draft-select-${d.id}`} />}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2"><Link to={`/prospects/${d.business_id}`} className="font-medium hover:text-primary">{d.business_name}</Link><GradeBadge grade={d.business?.grade} score={d.business?.score} testid={`draft-grade-${d.id}`} /><StatusBadge status={d.status} />{d.campaign_id && <span className="text-xs text-muted-foreground">in campaign</span>}</div>
                      <div className="mt-1 text-sm">{d.subject}</div>
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{d.body}</p>
                      {d.ineligible_reasons?.length > 0 && <div className="mt-1 text-xs text-red-500">{d.ineligible_reasons.join("; ")}</div>}
                    </div>
                    {d.status === "pending_approval" && <Button size="sm" variant="outline" onClick={() => approve(d.id)} data-testid={`draft-approve-${d.id}`}>Approve</Button>}
                  </div>
                </div>
              ))}
            </div>
          )}
          {sel.size > 0 && (
            <div className="mt-4 flex flex-wrap gap-2 rounded-lg bg-muted/60 p-3">
              <Input className="h-9 max-w-xs" placeholder="Campaign name" value={name} onChange={(e) => setName(e.target.value)} data-testid="campaign-name-input" />
              <Button onClick={create} data-testid="campaign-create-button"><Plus className="mr-1 h-4 w-4" />Create campaign ({sel.size})</Button>
            </div>
          )}
        </Section>
        <Section title="Campaigns">
          <div className="space-y-3">
            {camps.map((c) => (
              <div key={c.id} className="rounded-lg border p-4" data-testid={`campaign-card-${c.id}`}>
                <div className="flex items-center justify-between gap-2"><button className="font-medium hover:text-primary" onClick={() => setOpen(open === c.id ? null : c.id)} data-testid={`campaign-open-${c.id}`}>{c.name}</button><StatusBadge status={c.status} testid={`campaign-status-${c.id}`} /></div>
                <div className="mt-1 text-xs text-muted-foreground">{Object.entries(c.drafts || {}).filter(([k]) => k !== "sent").map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ")} · {c.sent_count} sent · {c.delivered} delivered · {c.replies} replies · {c.bounces} bounces</div>
                {c.waiting_reason && c.status === "running" && <div className="mt-1 text-xs text-amber-500">Waiting: {c.waiting_reason}</div>}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => act(c.id, "approve-all")} data-testid={`campaign-approve-all-${c.id}`}><CheckCheck className="mr-1 h-4 w-4" />Approve eligible</Button>
                  {["draft", "stopped", "completed"].includes(c.status) && <Button size="sm" onClick={() => act(c.id, "start")} data-testid={`campaign-start-${c.id}`}><Play className="mr-1 h-4 w-4" />Start</Button>}
                  {c.status === "running" && <Button size="sm" variant="outline" onClick={() => act(c.id, "pause")} data-testid={`campaign-pause-${c.id}`}><Pause className="mr-1 h-4 w-4" />Pause</Button>}
                  {c.status === "paused" && <Button size="sm" onClick={() => act(c.id, "resume")} data-testid={`campaign-resume-${c.id}`}><Play className="mr-1 h-4 w-4" />Resume</Button>}
                  {["running", "paused"].includes(c.status) && <Button size="sm" variant="ghost" className="text-red-500" onClick={() => act(c.id, "stop")} data-testid={`campaign-stop-${c.id}`}><Square className="mr-1 h-4 w-4" />Stop</Button>}
                </div>
                {open === c.id && (
                  <div className="mt-3 space-y-1 border-t pt-3 text-xs">
                    {outs.map((o) => <div key={o.id} className="flex justify-between gap-2"><span>{o.business_name} → {o.actual_to}{o.test_mode ? " (test)" : ""}</span><span className="flex gap-2"><StatusBadge status={o.status} /><span className="text-muted-foreground">{fmtDate(o.sent_at)}</span></span></div>)}
                    {!outs.length && <div className="text-muted-foreground">Nothing sent yet.</div>}
                  </div>
                )}
              </div>
            ))}
            {!camps.length && <div className="text-sm text-muted-foreground">Select approved or pending emails to create a campaign.</div>}
          </div>
        </Section>
      </div>
    </div>
  );
}
