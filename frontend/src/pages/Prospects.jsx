import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Download, Users, Merge } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, GradeBadge, StatusBadge, RepliedTag, Empty } from "@/components/common";
import { api, authUrl, errMsg, fmtDate } from "@/lib/api";

const OPTS = {
  website_status: ["website_exists", "no_website", "no_website_listed", "social_media_only", "website_unavailable", "under_construction"],
  grade: ["A", "B", "C", "D"],
  research_status: ["pending", "assessing", "assessed", "failed"],
  email_status: ["none", "draft", "approved", "sent", "test_sent", "delivered", "bounced", "replied", "unsubscribed", "no_contact", "not_qualified"],
  reply_status: ["none", "replied", "out_of_office"],
};

export default function Prospects() {
  const nav = useNavigate();
  const [f, setF] = useState({ q: "", category: "", city: "", suburb: "", website_status: "", grade: "", research_status: "", email_status: "", reply_status: "", campaign_id: "", search_id: "", discovered_from: "" });
  const [data, setData] = useState({ items: [], total: 0 });
  const [page, setPage] = useState(1);
  const [cats, setCats] = useState([]);
  const [camps, setCamps] = useState([]);
  const [searches, setSearches] = useState([]);
  const [sel, setSel] = useState([]);
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();

  useEffect(() => {
    api.get("/categories").then((r) => setCats(r.data));
    api.get("/campaigns").then((r) => setCamps(r.data));
    api.get("/searches").then((r) => setSearches(r.data));
  }, []);
  useEffect(() => {
    const t = setTimeout(() => api.get(`/prospects?${qs}&page=${page}&page_size=50`).then((r) => setData(r.data)), 250);
    return () => clearTimeout(t);
  }, [qs, page]);

  const set = (k, v) => { setPage(1); setF((p) => ({ ...p, [k]: v })); };
  const Sel = ({ k, opts, all }) => (
    <select className="native" value={f[k]} onChange={(e) => set(k, e.target.value)} data-testid={`filter-${k}`}>
      <option value="">{all}</option>
      {opts.map((o) => (typeof o === "string" ? <option key={o} value={o}>{o.replace(/_/g, " ")}</option> : <option key={o[0]} value={o[0]}>{o[1]}</option>))}
    </select>
  );
  const merge = async () => {
    if (sel.length !== 2) return;
    const [keep, other] = sel;
    if (!window.confirm("Merge the second selected record into the first? The first record is kept.")) return;
    try {
      await api.post("/prospects/merge", { keep_id: keep, merge_id: other });
      toast.success("Records merged");
      setSel([]);
      setPage((p) => p);
      api.get(`/prospects?${qs}&page=${page}&page_size=50`).then((r) => setData(r.data));
    } catch (e) {
      toast.error(errMsg(e));
    }
  };
  const toggle = (id) => setSel((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)));

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={`${data.total} businesses`} title="Prospects" desc="Every business the agent has ever discovered. Nothing is forgotten.">
        {sel.length === 2 && <Button variant="outline" onClick={merge} data-testid="prospects-merge-button"><Merge className="mr-1 h-4 w-4" />Merge duplicates</Button>}
        <a href={authUrl(`/prospects/export.csv?${qs}`)} data-testid="prospects-export-csv"><Button variant="outline"><Download className="mr-1 h-4 w-4" />Export CSV</Button></a>
      </PageHeader>
      <div className="panel flex flex-wrap gap-2 p-3">
        <Input data-testid="prospect-search-input" className="h-9 w-56" placeholder="Business name…" value={f.q} onChange={(e) => set("q", e.target.value)} />
        <Sel k="category" opts={cats} all="All categories" />
        <Input data-testid="filter-city" className="h-9 w-32" placeholder="City" value={f.city} onChange={(e) => set("city", e.target.value)} />
        <Input data-testid="filter-suburb" className="h-9 w-32" placeholder="Suburb" value={f.suburb} onChange={(e) => set("suburb", e.target.value)} />
        <Sel k="website_status" opts={OPTS.website_status} all="Any website" />
        <Sel k="grade" opts={OPTS.grade} all="Any grade" />
        <Sel k="research_status" opts={OPTS.research_status} all="Any research" />
        <Sel k="email_status" opts={OPTS.email_status} all="Any email" />
        <Sel k="reply_status" opts={OPTS.reply_status} all="Any reply" />
        <Sel k="campaign_id" opts={camps.map((c) => [c.id, c.name])} all="Any campaign" />
        <Sel k="search_id" opts={searches.map((s) => [s.id, `${s.category} · ${s.city}`])} all="Any search" />
        <Input data-testid="filter-discovered-from" type="date" className="h-9 w-40" value={f.discovered_from} onChange={(e) => set("discovered_from", e.target.value)} title="Discovered from" />
      </div>
      {!data.items.length ? <Empty icon={Users} title="No prospects match" desc="Adjust filters or start a new search." /> : (
        <div className="panel overflow-x-auto">
          <table className="w-full text-sm" data-testid="prospects-table">
            <thead><tr className="border-b text-left"><th className="w-8 p-3"></th>{["Business", "Suburb", "Website", "Score", "Research", "Email", "Discovered"].map((h) => <th key={h} className="eyebrow p-3 font-normal">{h}</th>)}</tr></thead>
            <tbody>
              {data.items.map((p) => (
                <tr key={p.id} className="cursor-pointer border-b last:border-0 hover:bg-accent/40" onClick={() => nav(`/prospects/${p.id}`)} data-testid={`prospect-row-${p.id}`}>
                  <td className="p-3" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={sel.includes(p.id)} onChange={() => toggle(p.id)} data-testid={`prospect-select-${p.id}`} /></td>
                  <td className="p-3"><div className="flex items-center gap-2 font-medium">{p.name}{p.reply_status === "replied" && <RepliedTag testid={`prospect-replied-${p.id}`} />}</div><div className="text-xs capitalize text-muted-foreground">{p.category}{p.parent_group ? " · multi-location" : ""}{p.excluded ? " · excluded" : ""}</div></td>
                  <td className="p-3 text-muted-foreground">{p.suburb}</td>
                  <td className="p-3"><StatusBadge status={p.website_status} /></td>
                  <td className="p-3"><GradeBadge grade={p.grade} score={p.score} testid={`prospect-grade-${p.id}`} /></td>
                  <td className="p-3"><StatusBadge status={p.research_status} /></td>
                  <td className="p-3"><StatusBadge status={p.email_status} /></td>
                  <td className="p-3 text-xs text-muted-foreground">{fmtDate(p.discovered_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-between p-3 text-xs text-muted-foreground">
            <span>Page {page} of {Math.max(1, Math.ceil(data.total / 50))}</span>
            <div className="flex gap-2"><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="prospects-prev">Prev</Button><Button size="sm" variant="outline" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)} data-testid="prospects-next">Next</Button></div>
          </div>
        </div>
      )}
      <p className="text-xs text-muted-foreground">Tip: tick two rows to manually merge duplicate records. <Link to="/coverage" className="text-primary">View on map →</Link></p>
    </div>
  );
}
