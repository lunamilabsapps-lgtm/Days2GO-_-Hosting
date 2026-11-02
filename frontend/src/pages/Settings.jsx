import { useEffect, useState } from "react";
import { Save, Download, Trash2, DatabaseBackup } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, Section, Field, StatusBadge } from "@/components/common";
import { api, errMsg, fmtDate, label, authUrl } from "@/lib/api";

function Form({ section, data, fields, onSaved, note }) {
  const [v, setV] = useState(data);
  useEffect(() => setV(data), [data]);
  const save = async () => {
    try { await api.put(`/settings/${section}`, v); toast.success("Settings saved"); onSaved(); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <Section title={label(section)} right={<Button size="sm" onClick={save} data-testid={`settings-save-${section}`}><Save className="mr-1 h-4 w-4" />Save</Button>}>
      {note && <p className="mb-4 text-xs text-muted-foreground">{note}</p>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {fields.map(([k, l, type, hint]) => (
          type === "bool" ? (
            <label key={k} className="flex items-center gap-2 text-sm"><Switch checked={!!v[k]} onCheckedChange={(x) => setV({ ...v, [k]: x })} data-testid={`setting-${section}-${k}`} />{l}</label>
          ) : type === "textarea" ? (
            <Field key={k} label={l} hint={hint}><textarea rows={7} className="w-full rounded-md border border-input bg-background p-2 text-sm" value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} data-testid={`setting-${section}-${k}`} /></Field>
          ) : type?.startsWith?.("select:") ? (
            <Field key={k} label={l} hint={hint}><select className="native w-full" value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} data-testid={`setting-${section}-${k}`}>{type.slice(7).split(",").map((o) => <option key={o}>{o}</option>)}</select></Field>
          ) : (
            <Field key={k} label={l} hint={hint}><Input type={type || "text"} value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: type === "number" ? Number(e.target.value) : e.target.value })} data-testid={`setting-${section}-${k}`} /></Field>
          )
        ))}
      </div>
    </Section>
  );
}

function Weights({ scoring, onSaved }) {
  const [w, setW] = useState(scoring.weights);
  const [min, setMin] = useState(scoring.min_grade_for_email);
  const save = async () => { try { await api.put("/settings/scoring", { weights: w, min_grade_for_email: min }); toast.success("Scoring saved"); onSaved(); } catch (e) { toast.error(errMsg(e)); } };
  return (
    <Section title="Lead scoring weights" right={<Button size="sm" onClick={save} data-testid="settings-save-scoring"><Save className="mr-1 h-4 w-4" />Save</Button>}>
      <p className="mb-4 text-xs text-muted-foreground">Score = weighted average of factors (0–100). A 80–100 · B 65–79 · C 45–64 · D below 45. Applies to new assessments.</p>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Object.entries(w).map(([k, val]) => <Field key={k} label={label(k)}><Input type="number" value={val} onChange={(e) => setW({ ...w, [k]: Number(e.target.value) })} data-testid={`weight-${k}`} /></Field>)}
        <Field label="Minimum grade to prepare email"><select className="native w-full" value={min} onChange={(e) => setMin(e.target.value)} data-testid="setting-min-grade">{"ABCD".split("").map((g) => <option key={g}>{g}</option>)}</select></Field>
      </div>
    </Section>
  );
}

function Suppressions() {
  const [items, setItems] = useState([]);
  const [v, setV] = useState({ value: "", type: "email", reason: "manual" });
  const load = () => api.get("/suppressions").then((r) => setItems(r.data));
  useEffect(() => { load(); }, []);
  const add = async () => { try { await api.post("/suppressions", v); setV({ ...v, value: "" }); load(); } catch (e) { toast.error(errMsg(e)); } };
  const del = async (id) => { try { await api.delete(`/suppressions/${id}`); load(); } catch (e) { toast.error(errMsg(e)); } };
  return (
    <Section title="Suppression & exclusion list" right={<span className="eyebrow">{items.length} entries</span>}>
      <div className="mb-4 flex flex-wrap gap-2">
        <Input className="h-9 max-w-xs" placeholder="email@business.com.au or domain.com.au" value={v.value} onChange={(e) => setV({ ...v, value: e.target.value })} data-testid="suppression-value-input" />
        <select className="native" value={v.type} onChange={(e) => setV({ ...v, type: e.target.value })} data-testid="suppression-type-select"><option value="email">Email</option><option value="domain">Domain</option></select>
        <Input className="h-9 max-w-[180px]" value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} data-testid="suppression-reason-input" />
        <Button size="sm" onClick={add} disabled={!v.value} data-testid="suppression-add-button">Add</Button>
      </div>
      <div className="max-h-96 space-y-1 overflow-y-auto text-sm">
        {items.map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-accent/50" data-testid={`suppression-${s.id}`}>
            <span className="truncate">{s.label} <span className="text-xs text-muted-foreground">({s.type})</span></span>
            <span className="flex items-center gap-2"><StatusBadge status={s.reason} tone="bad" /><span className="text-xs text-muted-foreground">{fmtDate(s.created_at)}</span>
              {!["unsubscribed", "spam complaint"].includes(s.reason) && s.type !== "business" && <button onClick={() => del(s.id)} data-testid={`suppression-delete-${s.id}`}><Trash2 className="h-3.5 w-3.5 text-muted-foreground" /></button>}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Reports() {
  const [c, setC] = useState(null);
  const [r, setR] = useState([]);
  useEffect(() => { api.get("/reports/costs").then((x) => setC(x.data)); api.get("/reports/searches").then((x) => setR(x.data)); }, []);
  return (
    <div className="space-y-6">
      {c && (
        <Section title="AI cost tracking" right={<span className="font-mono text-sm" data-testid="report-total-cost">${c.total_usd.toFixed(3)}</span>}>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-md bg-muted/60 p-3"><div className="eyebrow">Cost per qualified lead</div><div className="mt-1 font-display text-2xl font-bold" data-testid="report-cpql">{c.cost_per_qualified_lead != null ? `$${c.cost_per_qualified_lead.toFixed(3)}` : "—"}</div></div>
            <div className="rounded-md bg-muted/60 p-3"><div className="eyebrow">Cost per assessment</div><div className="mt-1 font-display text-2xl font-bold">{c.cost_per_assessment != null ? `$${c.cost_per_assessment.toFixed(3)}` : "—"}</div></div>
            <div className="rounded-md bg-muted/60 p-3"><div className="eyebrow">Qualified / assessed</div><div className="mt-1 font-display text-2xl font-bold">{c.qualified} / {c.assessed}</div></div>
          </div>
          <div className="mt-4 space-y-1 text-xs">{c.by_purpose.map((p) => <div key={p._id} className="flex justify-between"><span className="capitalize">{p._id} ({p.calls} calls, ~{p.in + p.out} tokens)</span><span className="font-mono">${p.cost.toFixed(4)}</span></div>)}</div>
          <p className="mt-3 text-[11px] text-muted-foreground">{c.note}</p>
        </Section>
      )}
      <Section title="Campaign performance by search">
        <div className="overflow-x-auto"><table className="w-full text-sm" data-testid="search-report-table">
          <thead><tr className="border-b text-left">{["Search", "Status", "Zones", "Businesses", "A/B/C/D", "Sent", "Replies", "AI cost"].map((h) => <th key={h} className="eyebrow p-2 font-normal">{h}</th>)}</tr></thead>
          <tbody>{r.map((s) => <tr key={s.id} className="border-b last:border-0"><td className="p-2 capitalize">{s.category} · {s.city}</td><td className="p-2"><StatusBadge status={s.status} /></td><td className="p-2">{s.progress.zones_done}/{s.progress.zones_total}</td><td className="p-2">{s.businesses}</td><td className="p-2 font-mono text-xs">{s.grades.A}/{s.grades.B}/{s.grades.C}/{s.grades.D}</td><td className="p-2">{s.sent}</td><td className="p-2">{s.replies}</td><td className="p-2 font-mono text-xs">${s.ai_cost_usd.toFixed(3)}</td></tr>)}</tbody>
        </table></div>
      </Section>
    </div>
  );
}

function Backups({ cfg, onSaved }) {
  const [b, setB] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/backups").then((r) => setB(r.data));
  useEffect(() => { load(); }, []);
  const run = async () => { setBusy(true); try { await api.post("/backups"); toast.success("Backup created"); load(); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); } };
  return (
    <div className="space-y-6">
      <Form section="backups" data={cfg} onSaved={onSaved} fields={[["enabled", "Automatic backups", "bool"], ["interval_hours", "Every (hours)", "number"], ["keep", "Keep last N backups", "number"]]} />
      <Section title="Backup files" right={<Button size="sm" onClick={run} disabled={busy} data-testid="backup-now-button"><DatabaseBackup className="mr-1 h-4 w-4" />Back up now</Button>}>
        <div className="space-y-1 text-sm">
          {b?.files.map((f) => <div key={f.name} className="flex items-center justify-between rounded-md px-2 py-1.5 hover:bg-accent/50"><span className="font-mono text-xs">{f.name}</span><span className="flex items-center gap-3 text-xs text-muted-foreground">{f.size_kb} KB · {fmtDate(f.created)}<a href={authUrl(`/backups/${f.name}`)} data-testid={`backup-download-${f.name}`}><Download className="h-4 w-4" /></a></span></div>)}
          {!b?.files.length && <div className="text-muted-foreground">No backups yet.</div>}
        </div>
      </Section>
    </div>
  );
}

function Audit() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/audit?limit=300").then((r) => setItems(r.data)); }, []);
  return (
    <Section title="Audit trail">
      <div className="max-h-[60vh] space-y-0.5 overflow-y-auto text-xs" data-testid="audit-list">
        {items.map((a) => <div key={a.id} className="flex gap-3 rounded px-2 py-1 hover:bg-accent/40"><span className="w-40 shrink-0 font-mono text-muted-foreground">{fmtDate(a.created_at)}</span><span className="w-48 shrink-0 font-medium">{label(a.action)}</span><span className="truncate text-muted-foreground">{a.entity}{a.entity_id ? ` · ${a.entity_id}` : ""} · {a.actor}</span></div>)}
      </div>
    </Section>
  );
}

export default function SettingsPage() {
  const [s, setS] = useState(null);
  const load = () => api.get("/settings").then((r) => setS(r.data));
  useEffect(() => { load(); }, []);
  if (!s) return <div className="text-muted-foreground">Loading…</div>;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Administration" title="Settings" />
      <Tabs defaultValue="sending">
        <TabsList className="flex-wrap">{["sending", "compliance", "research", "suppression", "reports", "backups", "audit"].map((t) => <TabsTrigger key={t} value={t} className="capitalize" data-testid={`settings-tab-${t}`}>{t}</TabsTrigger>)}</TabsList>
        <TabsContent value="sending" className="space-y-6">
          <Form section="sender" data={s.sender} onSaved={load} note="Shown in every email footer for Spam Act sender identification."
            fields={[["name", "Sender name"], ["email", "Sender email (on verified domain)"], ["reply_to", "Reply-to email (your Hostinger mailbox)"], ["domain", "Verified sending domain"], ["business_name", "Business name"], ["business_status", "Business status"], ["abn", "ABN"], ["business_address", "Business address"], ["business_description", "Business description (used by the AI)"], ["website", "Website"], ["signature_name", "Your name"], ["signature_block", "Email signature (added to every email)", "textarea"], ["location", "Where you're based"], ["experience", "Your experience (mentioned in emails)"], ["mobile", "Mobile (in emails & signature)"]]} />
          <Form section="sending" data={s.sending} onSaved={load} note="Test mode redirects every send to the test recipient and adds [TEST] to the subject. Real prospects can never be emailed while it is on."
            fields={[["test_mode", "Test mode (no real prospect emails)", "bool"], ["test_recipient", "Test recipient"], ["daily_limit", "Daily sending limit", "number"], ["campaign_limit", "Campaign sending limit", "number"], ["interval_seconds", "Interval between emails (s)", "number"], ["hours_start", "Sending hours start (0-23)", "number"], ["hours_end", "Sending hours end (0-23)", "number"], ["timezone", "Time zone", "select:Australia/Melbourne,Australia/Sydney,Australia/Brisbane,Australia/Adelaide,Australia/Perth,Australia/Hobart,Australia/Darwin"], ["weekdays_only", "Weekdays only", "bool"]]} />
        </TabsContent>
        <TabsContent value="compliance">
          <Form section="compliance" data={s.compliance} onSaved={load} note="Australian Spam Act 2003: emails are only prepared for business role addresses conspicuously published on the business's own website, where the message relates to the business's role and the site doesn't refuse commercial email. Every recipient gets a consent record, sender identification and a working unsubscribe. Confirm both checkboxes once you have reviewed these rules and the service catalogue."
            fields={[["configured", "I have reviewed and confirm the compliance settings", "bool"], ["offer_reviewed", "I have reviewed the Bright Coda offer catalogue", "bool"], ["allow_personal_addresses", "Use any email published by the business (incl. gmail/outlook)", "bool"], ["default_basis", "Consent basis recorded", "select:inferred_conspicuous_publication,express_consent"]]} />
        </TabsContent>
        <TabsContent value="research" className="space-y-6">
          <Form section="research" data={s.research} onSaved={load}
            fields={[["reassess_days", "Reassess websites after (days)", "number"], ["rediscovery_days", "Rediscover areas after (days)", "number"], ["concurrency", "Parallel researchers (1-4)", "number"], ["request_delay_seconds", "Delay between requests (s)", "number"], ["zone_radius_m", "Search radius per suburb (m)", "number"], ["screenshots", "Capture website screenshots", "bool"], ["ai_model", "AI model"], ["ai_input_cost_per_mtok", "AI input $ / million tokens", "number"], ["ai_output_cost_per_mtok", "AI output $ / million tokens", "number"]]} />
          <Weights scoring={s.scoring} onSaved={load} />
        </TabsContent>
        <TabsContent value="suppression"><Suppressions /></TabsContent>
        <TabsContent value="reports"><Reports /></TabsContent>
        <TabsContent value="backups"><Backups cfg={s.backups} onSaved={load} /></TabsContent>
        <TabsContent value="audit"><Audit /></TabsContent>
      </Tabs>
    </div>
  );
}
