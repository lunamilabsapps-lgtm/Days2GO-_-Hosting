import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { RefreshCw, Ban, PenLine, Save, Check, X, ExternalLink, Phone, Mail, MapPin, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, Section, GradeBadge, StatusBadge, RepliedTag } from "@/components/common";
import AssessmentReport from "@/components/AssessmentReport";
import WebsiteDiscovery, { sourceLabel } from "@/components/WebsiteDiscovery";
import { api, errMsg, fmtDate, label } from "@/lib/api";

function DraftEditor({ d, onSaved }) {
  const [subject, setSubject] = useState(d.subject);
  const [body, setBody] = useState(d.body);
  const editable = !["sent", "superseded", "blocked"].includes(d.status);
  const save = async () => {
    try { await api.patch(`/drafts/${d.id}`, { subject, body }); toast.success("Email saved"); onSaved(); } catch (e) { toast.error(errMsg(e)); }
  };
  const act = async (a) => {
    try { await api.post(`/drafts/${d.id}/${a}`); toast.success(`Email ${a}d`); onSaved(); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="space-y-3" data-testid={`draft-${d.id}`}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <StatusBadge status={d.status} testid="draft-status" /><span className="text-muted-foreground">To {d.recipient} · {body.split(/\s+/).filter(Boolean).length} words · {fmtDate(d.created_at)}{d.edited ? " · edited" : ""}</span>
      </div>
      {d.ineligible_reasons?.length > 0 && <div className="rounded-md bg-red-500/10 p-2 text-xs text-red-500">Not eligible: {d.ineligible_reasons.join("; ")}</div>}
      {d.finding_used && <div className="text-xs text-muted-foreground">Based on finding: <span className="text-foreground">{d.finding_used}</span></div>}
      <Input data-testid="draft-subject-input" value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!editable} />
      <Textarea data-testid="draft-body-input" rows={10} value={body} onChange={(e) => setBody(e.target.value)} disabled={!editable} />
      {editable && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={save} data-testid="draft-save-button"><Save className="mr-1 h-4 w-4" />Save edits</Button>
          {["pending_approval", "rejected"].includes(d.status) && <Button size="sm" onClick={() => act("approve")} data-testid="email-approve-button"><Check className="mr-1 h-4 w-4" />Approve</Button>}
          {d.status === "approved" && <Button size="sm" variant="outline" onClick={() => act("unapprove")} data-testid="email-unapprove-button">Unapprove</Button>}
          {d.status !== "rejected" && <Button size="sm" variant="ghost" className="text-red-500" onClick={() => act("reject")} data-testid="email-reject-button"><X className="mr-1 h-4 w-4" />Reject</Button>}
        </div>
      )}
      <p className="text-[11px] text-muted-foreground">Sender identification and an unsubscribe link are added automatically at send time.</p>
    </div>
  );
}

function VisabalBrief({ id, brief, setBrief }) {
  const [err, setErr] = useState("");
  useEffect(() => { api.get(`/prospects/${id}/visabal-brief`).then((r) => setBrief(r.data.text)).catch((e) => setErr(errMsg(e))); }, [id]); // eslint-disable-line
  if (err) return <p className="text-sm text-muted-foreground">{err}</p>;
  return <pre data-testid="visabal-brief-text" className="whitespace-pre-wrap rounded-md bg-muted/60 p-4 font-mono text-xs leading-relaxed">{brief || "Loading…"}</pre>;
}

export default function ProspectDetail() {
  const { id } = useParams();
  const [d, setD] = useState(null);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [brief, setBrief] = useState("");
  const load = () => api.get(`/prospects/${id}`).then((r) => { setD(r.data); setNotes(r.data.business.notes || ""); });
  useEffect(() => { load(); }, [id]); // eslint-disable-line

  if (!d) return <div className="text-muted-foreground">Loading…</div>;
  const b = d.business;
  const post = async (path, body, msg) => {
    try { await api.post(path, body); toast.success(msg); load(); } catch (e) { toast.error(errMsg(e)); }
  };
  const genEmail = async () => {
    setBusy(true);
    try { await api.post(`/prospects/${id}/generate-email`); toast.success("Email generated"); load(); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const saveNotes = async (extra = {}) => {
    try { await api.patch(`/prospects/${id}`, { notes, ...extra }); toast.success("Saved"); load(); } catch (e) { toast.error(errMsg(e)); }
  };
  const draft = d.drafts.find((x) => x.status !== "superseded");
  const review = b.website_status === "website_unverified";
  return (
    <div className="space-y-6">
      <PageHeader eyebrow={<Link to="/prospects" className="hover:text-primary">← Prospects</Link>} title={b.name}
        desc={`${b.category} · ${[b.address, b.suburb, b.city].filter(Boolean).join(", ")}`}>
        {b.reply_status === "replied" && <RepliedTag testid="detail-replied-tag" />}
        <GradeBadge grade={b.grade} score={b.score} testid="detail-grade-badge" />
        <Button variant="outline" size="sm" onClick={() => post(`/prospects/${id}/reassess`, {}, "Reassessment queued")} data-testid="detail-reassess-button"><RefreshCw className="mr-1 h-4 w-4" />Reassess</Button>
        <Button variant="outline" size="sm" className={b.excluded ? "" : "text-red-500"} onClick={() => post(`/prospects/${id}/exclude`, { exclude: !b.excluded, reason: "manually excluded" }, b.excluded ? "Exclusion removed" : "Business permanently excluded")} data-testid="detail-exclude-button"><Ban className="mr-1 h-4 w-4" />{b.excluded ? "Remove exclusion" : "Exclude"}</Button>
      </PageHeader>
      <div className="grid gap-4 md:grid-cols-4">
        <Section className="md:col-span-1" title="Business details">
          <div className="space-y-2 text-sm">
            {b.website ? <a href={b.website} target="_blank" rel="noreferrer" className="flex items-center gap-2 break-all text-primary" data-testid="detail-website-link"><ExternalLink className="h-4 w-4 shrink-0" />{b.website}</a> : <div className="text-amber-500" data-testid="detail-no-website">{{ no_website_found: "No website found after searching", website_unverified: "Possible website — needs your check", website_not_verified: "Website not yet verified" }[b.website_status] || "No website listed"}</div>}
            {b.website_source && <div className="text-xs text-muted-foreground" data-testid="detail-website-source">Website found via {sourceLabel(b.website_source)} · confidence {b.website_confidence}</div>}
            {b.phone && <div className="flex items-center gap-2"><Phone className="h-4 w-4" />{b.phone}</div>}
            {b.primary_email && <div className="flex items-center gap-2 break-all"><Mail className="h-4 w-4 shrink-0" />{b.primary_email}</div>}
            <div className="flex items-start gap-2"><MapPin className="mt-0.5 h-4 w-4 shrink-0" />{b.address || b.suburb}</div>
            <div className="pt-2 text-xs text-muted-foreground">Source: <a className="text-primary" href={b.source_url} target="_blank" rel="noreferrer">{b.source}</a> · discovered {fmtDate(b.discovered_at)}</div>
            <div className="flex flex-wrap gap-1 pt-1"><StatusBadge status={b.website_status} /><StatusBadge status={b.research_status} /><StatusBadge status={b.email_status} /></div>
            {d.siblings.length > 0 && <div className="pt-2 text-xs"><div className="eyebrow mb-1">Other locations</div>{d.siblings.map((s) => <Link key={s.id} to={`/prospects/${s.id}`} className="block text-primary">{s.name} — {s.suburb}</Link>)}</div>}
          </div>
        </Section>
        <Section className="md:col-span-3" title="Notes & follow-up">
          <Textarea data-testid="detail-notes-input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Your private notes" />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => saveNotes()} data-testid="detail-notes-save">Save notes</Button>
            <span className="text-xs text-muted-foreground">Follow-up:</span>
            <select className="native" value={b.follow_up_status || "none"} onChange={(e) => saveNotes({ follow_up_status: e.target.value })} data-testid="detail-followup-select">
              {["none", "planned", "contacted_manually", "won", "lost", "cancelled"].map((x) => <option key={x} value={x}>{label(x)}</option>)}
            </select>
            {b.excluded && <StatusBadge status="excluded" tone="bad" />}
          </div>
        </Section>
      </div>
      <Tabs defaultValue={review ? "website" : "assessment"}>
        <TabsList className="flex-wrap">
          {["assessment", "website", "visabal", "email", "contacts", "outreach", "history"].map((t) => <TabsTrigger key={t} value={t} data-testid={`detail-tab-${t}`} className="capitalize">{t === "assessment" ? "Opportunity report" : t === "visabal" ? "Visabal brief" : t === "website" ? "Website search" : t}</TabsTrigger>)}
        </TabsList>
        <TabsContent value="visabal"><Section title="Research brief for Visabal" right={<Button size="sm" variant="outline" data-testid="visabal-copy-button" onClick={async () => { try { const r = await api.get(`/prospects/${id}/visabal-brief`); await navigator.clipboard.writeText(r.data.text); setBrief(r.data.text); toast.success("Brief copied — paste it into Visabal"); } catch (e) { toast.error(errMsg(e)); } }}>Copy brief</Button>}>
          <VisabalBrief id={id} brief={brief} setBrief={setBrief} />
        </Section></TabsContent>
        <TabsContent value="website"><Section title="Website discovery"><WebsiteDiscovery bid={id} lookup={d.website_lookup} business={b} onChange={load} /></Section></TabsContent>
        <TabsContent value="assessment"><Section><AssessmentReport a={d.assessments[0]} /></Section></TabsContent>
        <TabsContent value="email">
          <Section title="Personalised email" right={<Button size="sm" variant="outline" onClick={genEmail} disabled={busy} data-testid="detail-generate-email">{busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <PenLine className="mr-1 h-4 w-4" />}{draft ? "Regenerate" : "Generate email"}</Button>}>
            {draft ? <DraftEditor key={draft.id + draft.status} d={draft} onSaved={load} /> : <p className="text-sm text-muted-foreground">No email prepared. {b.email_status === "no_contact" ? "No verified public business email was found — the agent never guesses addresses." : ""}</p>}
          </Section>
        </TabsContent>
        <TabsContent value="contacts">
          <Section title="Contacts & consent records">
            <div className="space-y-2 text-sm">
              {d.contacts.map((c) => (
                <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3">
                  <div><span className="font-medium">{c.value}</span> <span className="text-xs text-muted-foreground">({c.type})</span></div>
                  <div className="flex flex-wrap gap-1 text-xs">{c.type === "email" && <StatusBadge status={c.personal ? "personal-looking" : "business role address"} tone={c.personal ? "warn" : "good"} />}<a className="text-primary" href={c.source_url} target="_blank" rel="noreferrer">source</a></div>
                </div>
              ))}
              {!d.contacts.length && <div className="text-muted-foreground">No contacts found.</div>}
              {d.consent.map((c) => <div key={c.id} className="rounded-md bg-muted/50 p-3 text-xs"><b>Consent basis:</b> {label(c.basis)} for {c.email} — {c.evidence} <a className="text-primary" href={c.source_url} target="_blank" rel="noreferrer">source</a> · {fmtDate(c.recorded_at)}</div>)}
            </div>
          </Section>
        </TabsContent>
        <TabsContent value="outreach">
          <Section title="Outreach history">
            <div className="space-y-2 text-sm">
              {d.outbound.map((o) => <div key={o.id} className="rounded-md border p-3"><div className="flex justify-between"><span className="font-medium">{o.subject}</span><StatusBadge status={o.status} /></div><div className="text-xs text-muted-foreground">To {o.actual_to}{o.test_mode ? " (TEST)" : ""} · {fmtDate(o.sent_at)} · {o.message_id}</div><div className="text-xs">{(o.events || []).map((e) => `${e.type} ${fmtDate(e.at)}`).join(" · ")}</div></div>)}
              {d.inbound.map((m) => <div key={m.id} className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3"><div className="flex items-center justify-between"><span className="font-medium">{m.subject}</span>{m.kind === "reply" ? <RepliedTag testid={`detail-inbound-${m.id}`} /> : <StatusBadge status={m.kind} />}</div><div className="text-xs text-muted-foreground">From {m.from} · {fmtDate(m.received_at)} · matched by {label(m.matched_by)}</div><p className="mt-1 text-xs">{m.snippet}</p></div>)}
              {!d.outbound.length && !d.inbound.length && <div className="text-muted-foreground">No outreach yet.</div>}
            </div>
          </Section>
        </TabsContent>
        <TabsContent value="history">
          <Section title="Audit trail">
            <div className="space-y-1 text-xs">
              {[...d.events.map((e) => ({ at: e.created_at, t: `Discovery: ${e.result}${e.reason ? ` (${e.reason})` : ""} via ${e.source}` })), ...d.audit.map((a) => ({ at: a.created_at, t: `${label(a.action)} by ${a.actor}` })), ...d.assessments.map((a) => ({ at: a.assessed_at, t: `Assessment: ${label(a.presence)}, score ${a.score}` }))]
                .sort((x, y) => (y.at || "").localeCompare(x.at || "")).map((x, i) => <div key={i} className="flex gap-3"><span className="w-40 shrink-0 font-mono text-muted-foreground">{fmtDate(x.at)}</span><span>{x.t}</span></div>)}
            </div>
          </Section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
