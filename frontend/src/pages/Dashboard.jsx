import { useEffect, useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { Building2, ScanSearch, Globe, GlobeLock, Star, PenLine, Send, MailCheck, MessageSquareReply, UserX, Hourglass, DollarSign, Search } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { PageHeader, StatCard, Section, RepliedTag } from "@/components/common";
import { LiveBusinessCard, Timeline, AgentControls, SearchProgress } from "@/components/Live";
import { useLive } from "@/hooks/useLive";
import { api, errMsg, fmtDate } from "@/lib/api";

export default function Dashboard() {
  const { stats } = useOutletContext();
  const { events, state, setState } = useLive(60);
  const [searches, setSearches] = useState([]);
  const [replies, setReplies] = useState([]);

  const load = () => {
    api.get("/searches").then((r) => setSearches(r.data));
    api.get("/inbound?kind=reply").then((r) => setReplies(r.data.slice(0, 5)));
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  const onAction = async (id, a) => {
    try {
      await api.post(`/searches/${id}/${a}`);
      load();
    } catch (e) {
      toast.error(errMsg(e));
    }
  };
  const s = stats || {};
  const slots = (state?.current || []).filter((c) => c.stage && c.stage !== "idle" && c.business).sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
  const cards = [
    ["Businesses discovered", s.discovered, Building2, "stat-discovered"], ["Businesses assessed", s.assessed, ScanSearch, "stat-assessed"],
    ["With websites", s.with_website, Globe, "stat-with-website"], ["Without websites", s.without_website, GlobeLock, "stat-without-website"],
    ["Qualified prospects", s.qualified, Star, "stat-qualified", "text-emerald-500", "Grade A + B"], ["Emails prepared", s.emails_prepared, PenLine, "stat-emails-prepared"],
    ["Emails sent", s.emails_sent, Send, "stat-emails-sent", null, s.test_sends ? `${s.test_sends} test sends` : null], ["Emails delivered", s.emails_delivered, MailCheck, "stat-emails-delivered"],
    ["Replies received", s.replies, MessageSquareReply, "stat-replies", "text-emerald-500"], ["Unsubscribes", s.unsubscribes, UserX, "stat-unsubscribes"],
    ["Awaiting review", s.awaiting_review, Hourglass, "stat-awaiting-review", "text-amber-500"],
    ["AI spend (est.)", `$${(s.ai_cost_usd || 0).toFixed(2)}`, DollarSign, "stat-ai-cost", null, s.cost_per_qualified_lead != null ? `$${s.cost_per_qualified_lead.toFixed(3)} per qualified lead` : "per qualified lead: —"],
  ];
  return (
    <div className="space-y-8">
      <PageHeader eyebrow="Command centre" title="Dashboard" desc="Everything the agent has discovered, assessed and prepared — updating live.">
        <AgentControls state={state?.state} onChange={setState} />
        <Link to="/search"><Button data-testid="dashboard-new-search-button"><Search className="mr-1 h-4 w-4" />New search</Button></Link>
      </PageHeader>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {cards.map(([t, v, I, id, acc, hint]) => <StatCard key={id} title={t} value={v} icon={I} testid={id} accent={acc} hint={hint} />)}
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <div className="min-w-0 space-y-4">
          <div className="flex items-center justify-between"><h2 className="font-display text-xl font-bold">Live agent</h2><Link to="/live" className="text-sm text-primary" data-testid="dashboard-open-live">Open full view →</Link></div>
          <LiveBusinessCard slot={slots[0] || (state?.current || []).find((c) => c.stage === "searching")} />
        </div>
        <Section title="Activity" right={<span className="eyebrow">streaming</span>}>
          <div className="max-h-[360px] overflow-y-auto pr-1"><Timeline events={events} max={30} /></div>
        </Section>
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <Section title="Prospecting campaigns">
          <div className="space-y-3">
            {searches.slice(0, 6).map((x) => <SearchProgress key={x.id} s={x} onAction={onAction} />)}
            {!searches.length && <div className="text-sm text-muted-foreground">No searches yet. <Link className="text-primary" to="/search">Start one →</Link></div>}
          </div>
        </Section>
        <Section title="Latest replies">
          <div className="space-y-3">
            {replies.map((r) => (
              <Link key={r.id} to={`/prospects/${r.business_id}`} className="block rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3" data-testid={`dashboard-reply-${r.id}`}>
                <div className="flex items-center justify-between gap-2"><span className="font-medium">{r.business_name}</span><RepliedTag /></div>
                <div className="mt-1 text-xs text-muted-foreground">{r.campaign_name} · {fmtDate(r.received_at)}</div>
              </Link>
            ))}
            {!replies.length && <div className="text-sm text-muted-foreground">No replies yet. Replies detected in your mailbox appear here with a green tag.</div>}
          </div>
        </Section>
      </div>
    </div>
  );
}
