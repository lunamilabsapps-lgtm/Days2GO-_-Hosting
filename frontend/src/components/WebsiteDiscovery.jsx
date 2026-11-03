import { useState } from "react";
import { Check, X, Search, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/common";
import { api, errMsg, fmtDate, label } from "@/lib/api";

const SOURCE = {
  google_maps_via_serper: "Google Maps listing", google_search_via_serper: "Google search", brave_search: "Brave search",
  existing_scout_record: "another Scout record", manual_confirmation: "confirmed by you",
};
export const sourceLabel = (s) => (s || "").split(",").map((x) => SOURCE[x] || label(x)).join(" + ");

function Candidate({ c, onConfirm }) {
  return (
    <div className="rounded-md border p-3" data-testid={`website-candidate-${c.domain}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <a href={c.final_url || c.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 font-medium text-primary"><ExternalLink className="h-3.5 w-3.5" />{c.domain}</a>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs" data-testid={`website-candidate-score-${c.domain}`}>{c.score}/100</span>
          <Button size="sm" onClick={() => onConfirm(c.final_url || c.url)} data-testid={`website-confirm-${c.domain}`}><Check className="mr-1 h-4 w-4" />This is their website</Button>
        </div>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">Found via {sourceLabel((c.providers || []).join(","))}{c.listing?.address ? ` · Maps listing: ${c.listing.title}, ${c.listing.address}` : ""}</div>
      <ul className="mt-1 list-disc pl-4 text-xs">{(c.signals || []).map((s, i) => <li key={i}>{s}</li>)}</ul>
    </div>
  );
}

export default function WebsiteDiscovery({ bid, lookup, business, onChange }) {
  const [url, setUrl] = useState("");
  const post = async (path, body, msg) => {
    try { await api.post(`/prospects/${bid}/website/${path}`, body); toast.success(msg); setUrl(""); onChange(); } catch (e) { toast.error(errMsg(e)); }
  };
  const confirm = (u) => post("confirm", { url: u }, "Website saved — reassessment queued");
  const listed = business.website && !business.website_source;
  return (
    <div className="space-y-3 text-sm" data-testid="website-discovery-panel">
      {lookup ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <StatusBadge status={lookup.status} testid="website-lookup-status" />
          <span className="text-muted-foreground">{lookup.confirmed_by && lookup.status === "found" ? `Confirmed by you ${fmtDate(lookup.confirmed_at)}` : `Searched ${fmtDate(lookup.searched_at)}${lookup.tiers?.length ? ` · ${lookup.tiers.map(label).join(" → ")}` : ""}`}{lookup.confidence ? ` · confidence ${lookup.confidence}` : ""}</span>
        </div>
      ) : <p className="text-muted-foreground">{listed ? "Website taken from the business listing — no search needed." : "No website search has run yet."}</p>}
      {lookup?.errors?.length > 0 && <div className="rounded-md bg-red-500/10 p-2 text-xs text-red-500">{lookup.errors.join("; ")}</div>}
      {lookup?.status === "needs_review" && <div className="rounded-md bg-amber-500/10 p-2 text-xs text-amber-600 dark:text-amber-400">The match isn't certain, so no email will be prepared until you confirm or reject the website.</div>}
      {(lookup?.candidates || []).filter((c) => c.domain !== lookup.chosen_domain || lookup.status !== "found").map((c) => <Candidate key={c.domain} c={c} onConfirm={confirm} />)}
      {!listed && (
        <div className="flex flex-wrap gap-2">
          <Input className="h-9 w-64" placeholder="Enter the website yourself" value={url} onChange={(e) => setUrl(e.target.value)} data-testid="website-manual-input" />
          <Button size="sm" variant="outline" disabled={!url} onClick={() => confirm(url)} data-testid="website-manual-save"><Check className="mr-1 h-4 w-4" />Save website</Button>
          <Button size="sm" variant="outline" onClick={() => post("search", {}, "Website search queued")} data-testid="website-search-again"><Search className="mr-1 h-4 w-4" />Search again</Button>
          {lookup && lookup.status !== "rejected_by_user" && <Button size="sm" variant="ghost" className="text-red-500" onClick={() => post("reject", {}, "Marked as no website")} data-testid="website-reject-all"><X className="mr-1 h-4 w-4" />None of these / no website</Button>}
        </div>
      )}
    </div>
  );
}
