import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Globe } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader, GradeBadge, StatusBadge, Empty } from "@/components/common";
import AssessmentReport from "@/components/AssessmentReport";
import { api, fmtDate, shotUrl } from "@/lib/api";

export default function Assessments() {
  const [items, setItems] = useState([]);
  const [presence, setPresence] = useState("");
  const [grade, setGrade] = useState("");
  const [changed, setChanged] = useState(false);
  const [open, setOpen] = useState(null);
  useEffect(() => {
    api.get(`/assessments?presence=${presence}&grade=${grade}&changed=${changed}&limit=200`).then((r) => setItems(r.data));
  }, [presence, grade, changed]);
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Research" title="Website Assessments" desc="Evidence-based opportunity reports for every assessed business.">
        <select className="native" value={presence} onChange={(e) => setPresence(e.target.value)} data-testid="assess-filter-presence">
          <option value="">Any presence</option>{["website_exists", "no_website", "social_media_only", "website_unavailable", "under_construction"].map((p) => <option key={p} value={p}>{p.replace(/_/g, " ")}</option>)}
        </select>
        <select className="native" value={grade} onChange={(e) => setGrade(e.target.value)} data-testid="assess-filter-grade"><option value="">Any grade</option>{"ABCD".split("").map((g) => <option key={g}>{g}</option>)}</select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={changed} onChange={(e) => setChanged(e.target.checked)} data-testid="assess-filter-changed" />Website changed</label>
      </PageHeader>
      {!items.length ? <Empty icon={Globe} title="No assessments yet" desc="Assessments appear as the agent researches businesses." /> : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((a) => (
            <button key={a.id} onClick={() => setOpen(a)} className="panel overflow-hidden text-left transition-colors hover:border-primary/50" data-testid={`assessment-card-${a.id}`}>
              <div className="relative h-36 bg-muted">
                {a.screenshot ? <img src={shotUrl(a.screenshot)} alt="" className="h-full w-full object-cover object-top" /> : <div className="grid h-full place-items-center text-xs text-muted-foreground">{a.presence.replace(/_/g, " ")}</div>}
              </div>
              <div className="space-y-2 p-4">
                <div className="flex items-start justify-between gap-2"><div className="font-medium">{a.business?.name}</div><GradeBadge grade={a.grade} score={a.score} testid={`assessment-grade-${a.id}`} /></div>
                <div className="text-xs text-muted-foreground">{a.business?.suburb} · {fmtDate(a.assessed_at)}</div>
                <StatusBadge status={a.presence} />
                <p className="line-clamp-2 text-xs text-muted-foreground">{a.summary}</p>
              </div>
            </button>
          ))}
        </div>
      )}
      <Dialog open={!!open} onOpenChange={() => setOpen(null)}>
        <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto" data-testid="assessment-dialog">
          <DialogHeader><DialogTitle>{open?.business?.name} <Link to={`/prospects/${open?.business_id}`} className="ml-2 text-sm text-primary">Open prospect →</Link></DialogTitle></DialogHeader>
          <AssessmentReport a={open} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
