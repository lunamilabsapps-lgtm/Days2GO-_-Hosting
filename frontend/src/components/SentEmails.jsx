import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Send, ChevronDown, ChevronRight } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Section, StatusBadge, RepliedTag, Empty } from "@/components/common";
import { api, fmtDate, label } from "@/lib/api";

function Row({ o }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr onClick={() => setOpen(!open)} data-testid={`sent-row-${o.id}`}
        className={`cursor-pointer border-b last:border-0 ${o.replied ? "bg-emerald-500/15 hover:bg-emerald-500/25" : "hover:bg-accent/40"}`}>
        <td className="p-3">{open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</td>
        <td className="p-3"><Link to={`/prospects/${o.business_id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:text-primary">{o.business_name}</Link><div className="text-xs text-muted-foreground">{o.to}{o.test_mode ? " (test)" : ""}</div></td>
        <td className="p-3">{o.kind === "followup" ? <StatusBadge status="follow-up" tone="info" /> : null} {o.subject}</td>
        <td className="p-3 text-xs text-muted-foreground">{o.campaign_name || "—"}</td>
        <td className="p-3 text-xs text-muted-foreground">{fmtDate(o.sent_at || o.created_at)}</td>
        <td className="p-3"><StatusBadge status={o.status} /></td>
        <td className="p-3 text-xs">{label(o.followup_status)}</td>
        <td className="p-3">{o.replied ? <RepliedTag testid={`sent-replied-${o.id}`} /> : <span className="text-xs text-muted-foreground">No reply</span>}</td>
      </tr>
      {open && (
        <tr className="border-b bg-muted/30"><td colSpan={8} className="p-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <div><div className="eyebrow mb-1">Email sent</div><pre className="whitespace-pre-wrap font-sans text-sm">{o.body || "—"}</pre></div>
            <div>
              <div className="eyebrow mb-1">Reply</div>
              {o.reply ? <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm"><div className="font-medium">{o.reply.subject}</div><div className="text-xs text-muted-foreground">From {o.reply.from} · {fmtDate(o.reply.received_at)}{o.reply.sentiment ? ` · ${o.reply.sentiment}` : ""}</div><p className="mt-2 whitespace-pre-line text-xs">{o.reply.snippet}</p></div>
                : <div className="text-sm text-muted-foreground">{o.replied ? "Marked as replied." : "No reply detected yet."}</div>}
              <div className="mt-3 text-xs text-muted-foreground">Events: {(o.events || []).map((e) => `${e.type} ${fmtDate(e.at)}`).join(" · ") || "none"}</div>
            </div>
          </div>
        </td></tr>
      )}
    </>
  );
}

export default function SentEmails() {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [replied, setReplied] = useState("");
  useEffect(() => {
    const load = () => api.get(`/outbound?q=${encodeURIComponent(q)}&replied=${replied}`).then((r) => setItems(r.data));
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [q, replied]);
  const nReplied = items.filter((o) => o.replied).length;
  return (
    <Section title={`Sent emails (${items.length}) · ${nReplied} replied`} right={
      <div className="flex gap-2">
        <Input className="h-9 w-48" placeholder="Business or email…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="sent-search-input" />
        <select className="native" value={replied} onChange={(e) => setReplied(e.target.value)} data-testid="sent-replied-filter"><option value="">All</option><option value="yes">Replied</option><option value="no">No reply</option></select>
      </div>}>
      {!items.length ? <Empty icon={Send} title="Nothing sent yet" desc="Emails appear here as soon as a campaign sends them." /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="sent-emails-table">
            <thead><tr className="border-b text-left"><th className="w-8" />{["Business", "Subject", "Campaign", "Sent", "Delivery", "Follow-up", "Reply"].map((h) => <th key={h} className="eyebrow p-3 font-normal">{h}</th>)}</tr></thead>
            <tbody>{items.map((o) => <Row key={o.id} o={o} />)}</tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
