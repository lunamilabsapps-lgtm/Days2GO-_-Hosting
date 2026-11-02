import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MessageSquare, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, RepliedTag, StatusBadge, Empty } from "@/components/common";
import { api, fmtDate, label } from "@/lib/api";

export default function Replies() {
  const [items, setItems] = useState([]);
  const [kind, setKind] = useState("");
  const load = () => api.get(`/inbound?kind=${kind}`).then((r) => setItems(r.data));
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [kind]); // eslint-disable-line
  const handled = async (id) => { await api.post(`/inbound/${id}/handled`); load(); };
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Inbox monitor" title="Replies" desc="Replies detected in your mailbox. Open your own email client to respond — the agent never replies automatically.">
        <select className="native" value={kind} onChange={(e) => setKind(e.target.value)} data-testid="replies-kind-filter">
          <option value="">All inbound</option><option value="reply">Replies</option><option value="ooo">Out of office</option><option value="bounce">Bounces</option>
        </select>
      </PageHeader>
      {!items.length ? <Empty icon={MessageSquare} title="No replies yet" desc="Configure IMAP in Integrations so the agent can watch your mailbox for responses." /> : (
        <div className="space-y-3">
          {items.map((r) => (
            <div key={r.id} className={`panel p-5 ${r.kind === "reply" ? "border-emerald-500/40 bg-emerald-500/[0.04]" : ""}`} data-testid={`reply-card-${r.id}`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  {r.kind === "reply" ? <RepliedTag testid={`reply-tag-${r.id}`} /> : <StatusBadge status={r.kind === "ooo" ? "out of office" : r.kind} tone={r.kind === "bounce" ? "bad" : "warn"} />}
                  <Link to={`/prospects/${r.business_id}`} className="font-display text-lg font-semibold hover:text-primary">{r.business_name}</Link>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {fmtDate(r.received_at)}
                  {r.kind === "reply" && !r.handled && <Button size="sm" variant="outline" onClick={() => handled(r.id)} data-testid={`reply-handled-${r.id}`}><Check className="mr-1 h-3 w-3" />Mark handled</Button>}
                  {r.handled && <StatusBadge status="handled" tone="muted" />}
                </div>
              </div>
              <div className="mt-2 text-sm font-medium">{r.subject}</div>
              <div className="text-xs text-muted-foreground">From {r.from} · Campaign: {r.campaign_name || "—"} · matched by {label(r.matched_by)}</div>
              {r.snippet && <p className="mt-2 whitespace-pre-line text-sm text-muted-foreground">{r.snippet}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
