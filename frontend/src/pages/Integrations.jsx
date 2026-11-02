import { useEffect, useState } from "react";
import { Brain, Send, Webhook, Inbox, Map, MapPin, Camera, Loader2, PlugZap, Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { PageHeader, Field, StatusBadge } from "@/components/common";
import { api, errMsg, fmtDate } from "@/lib/api";

function Card({ id, icon: I, title, desc, ok, children, onTest }) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const test = async () => {
    setBusy(true);
    try { const r = await api.post(`/integrations/test/${id}`); setRes(r.data); } catch (e) { setRes({ ok: false, message: errMsg(e) }); } finally { setBusy(false); }
  };
  return (
    <div className="panel space-y-4 p-5" data-testid={`integration-${id}`}>
      <div className="flex items-start gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-primary/10 text-primary"><I className="h-5 w-5" /></div>
        <div className="flex-1"><div className="flex items-center gap-2 font-display font-semibold">{title}<StatusBadge status={ok ? "configured" : "setup required"} tone={ok ? "good" : "warn"} testid={`integration-status-${id}`} /></div><p className="text-xs text-muted-foreground">{desc}</p></div>
        {onTest !== false && <Button size="sm" variant="outline" onClick={test} disabled={busy} data-testid={`integration-test-${id}`}>{busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <PlugZap className="mr-1 h-4 w-4" />}Test</Button>}
      </div>
      {children}
      {res && <div data-testid={`integration-result-${id}`} className={`rounded-md p-2 text-xs ${res.ok ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" : "bg-red-500/10 text-red-500"}`}>{res.ok ? "✓ " : "✗ "}{res.message}</div>}
    </div>
  );
}

export default function Integrations() {
  const [st, setSt] = useState(null);
  const [s, setS] = useState(null);
  const [resend, setResend] = useState({ api_key: "", webhook_secret: "" });
  const [imap, setImap] = useState(null);
  const load = () => {
    api.get("/integrations/status").then((r) => setSt(r.data));
    api.get("/settings").then((r) => { setS(r.data); setImap(r.data.imap); });
  };
  useEffect(() => { load(); }, []);
  const save = async (section, body) => {
    try { await api.put(`/settings/${section}`, body); toast.success("Saved securely"); setResend({ api_key: "", webhook_secret: "" }); load(); } catch (e) { toast.error(errMsg(e)); }
  };
  if (!st || !s) return <div className="text-muted-foreground">Loading…</div>;
  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader eyebrow="Administration" title="Integrations" desc="Outbound (Resend) and inbound (IMAP) email are independent — change either without touching the other. Secrets are encrypted at rest and never sent back to the browser." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card id="ai" icon={Brain} title="AI analysis & writing" desc={`Claude (${st.ai.model}) via Emergent universal key`} ok={st.ai.configured} />
        <Card id="overpass" icon={Map} title="OpenStreetMap Overpass" desc="Business discovery source adapter (official public API)" ok>
          <div className="text-xs text-muted-foreground">Endpoints (tried in order): {st.overpass.endpoints.join(", ")}</div>
        </Card>
        <Card id="nominatim" icon={MapPin} title="OpenStreetMap Nominatim" desc="City boundary and area resolution" ok />
        <Card id="screenshots" icon={Camera} title="Website screenshots" desc="Headless browser for previews and mobile checks" ok={st.screenshots.configured} />
        <Card id="resend" icon={Send} title="Resend (outbound email)" desc="Your own Resend account and verified sending domain" ok={st.resend.configured}>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={`API key ${s.resend.api_key_set ? `(saved ${s.resend.api_key_hint})` : ""}`}><Input type="password" placeholder="re_…" value={resend.api_key} onChange={(e) => setResend({ ...resend, api_key: e.target.value })} data-testid="resend-api-key-input" /></Field>
            <div className="flex items-end"><Button onClick={() => save("resend", { api_key: resend.api_key })} disabled={!resend.api_key} data-testid="resend-save-key">Save key</Button></div>
          </div>
          <p className="text-xs text-muted-foreground">Sender name, address, domain and reply-to are in Settings → Sender. Current sender: {st.resend.sender || "not set"}</p>
        </Card>
        <Card id="resend_webhook" icon={Webhook} title="Resend webhooks" desc="Delivery, bounce and complaint events" ok={st.resend_webhook.configured} onTest={false}>
          <Field label="Webhook URL (add in Resend → Webhooks; events: delivered, bounced, complained, failed)">
            <div className="flex gap-2"><Input readOnly value={st.resend_webhook.url} data-testid="webhook-url" /><Button variant="outline" size="icon" onClick={() => { navigator.clipboard.writeText(st.resend_webhook.url); toast.success("Copied"); }}><Copy className="h-4 w-4" /></Button></div>
          </Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={`Signing secret ${s.resend.webhook_secret_set ? `(saved ${s.resend.webhook_secret_hint})` : ""}`}><Input type="password" placeholder="whsec_…" value={resend.webhook_secret} onChange={(e) => setResend({ ...resend, webhook_secret: e.target.value })} data-testid="resend-webhook-secret-input" /></Field>
            <div className="flex items-end"><Button onClick={() => save("resend", { webhook_secret: resend.webhook_secret })} disabled={!resend.webhook_secret} data-testid="resend-save-webhook">Save secret</Button></div>
          </div>
          <p className="text-xs text-muted-foreground">Last event: {st.resend_webhook.last_event ? `${st.resend_webhook.last_event.type} at ${fmtDate(st.resend_webhook.last_event.received_at)}` : "none received"}</p>
        </Card>
        <Card id="imap" icon={Inbox} title="Mailbox reply detection (IMAP)" desc="Watches your Hostinger mailbox read-only; matches by Message-ID, In-Reply-To, References and sender" ok={st.imap.configured && st.imap.enabled}>
          {imap && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Host"><Input value={imap.host} onChange={(e) => setImap({ ...imap, host: e.target.value })} data-testid="imap-host-input" /></Field>
              <Field label="Port"><Input type="number" value={imap.port} onChange={(e) => setImap({ ...imap, port: Number(e.target.value) })} data-testid="imap-port-input" /></Field>
              <Field label="SSL/TLS"><select className="native w-full" value={imap.security || "ssl"} onChange={(e) => setImap({ ...imap, security: e.target.value, port: e.target.value === "ssl" ? 993 : 143 })} data-testid="imap-security-select">
                <option value="ssl">SSL/TLS (port 993)</option><option value="starttls">STARTTLS (port 143)</option><option value="none">None (not recommended)</option></select></Field>
              <Field label="Username"><Input value={imap.username} onChange={(e) => setImap({ ...imap, username: e.target.value })} data-testid="imap-username-input" /></Field>
              <Field label={`Password ${s.imap.password_set ? `(saved ${s.imap.password_hint})` : ""}`}><Input type="password" value={imap.password} onChange={(e) => setImap({ ...imap, password: e.target.value })} data-testid="imap-password-input" /></Field>
              <Field label="Folder"><Input value={imap.folder} onChange={(e) => setImap({ ...imap, folder: e.target.value })} /></Field>
              <Field label="Check every (seconds)"><Input type="number" value={imap.poll_seconds} onChange={(e) => setImap({ ...imap, poll_seconds: Number(e.target.value) })} /></Field>
              <label className="flex items-center gap-2 text-sm"><Switch checked={imap.enabled} onCheckedChange={(v) => setImap({ ...imap, enabled: v })} data-testid="imap-enabled-switch" />Monitoring enabled</label>
              <div className="flex justify-end"><Button onClick={() => save("imap", imap)} data-testid="imap-save-button">Save mailbox</Button></div>
            </div>
          )}
          {st.imap.health?.last_poll && <p className="text-xs text-muted-foreground">Last check {fmtDate(st.imap.health.last_poll)}{st.imap.health.error ? ` — error: ${st.imap.health.error}` : ` — ${st.imap.health.new} new`}</p>}
        </Card>
      </div>
    </div>
  );
}
