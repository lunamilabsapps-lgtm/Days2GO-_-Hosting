import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, Loader2, MapPinned, Rocket } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { PageHeader, Section, Field } from "@/components/common";
import { api, errMsg } from "@/lib/api";

const STATES = ["Victoria", "New South Wales", "Queensland", "South Australia", "Western Australia", "Tasmania", "Australian Capital Territory", "Northern Territory"];

export default function NewSearch() {
  const nav = useNavigate();
  const [instruction, setInstruction] = useState("Find all butchers in Melbourne");
  const [f, setF] = useState({ country: "Australia", state: "Victoria", city: "Melbourne", radius_km: 25, direction: "all", category: "butchers", subcategory: "", max_businesses: 0, mode: "research", force_refresh: false });
  const [cats, setCats] = useState([]);
  const [zones, setZones] = useState(null);
  const [region, setRegion] = useState(null);
  const [sel, setSel] = useState(new Set());
  const [busy, setBusy] = useState("");
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    api.get("/categories").then((r) => setCats(r.data));
  }, []);

  const parse = async () => {
    setBusy("parse");
    try {
      const r = await api.post("/searches/parse", { instruction });
      setF((p) => ({ ...p, ...Object.fromEntries(Object.entries(r.data).filter(([k, v]) => v && k in p)) }));
      setZones(null);
      toast.success("Instruction understood — check the details and resolve the area");
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const resolve = async () => {
    setBusy("resolve");
    try {
      const r = await api.post("/regions/resolve", { country: f.country, state: f.state, city: f.city, radius_km: Number(f.radius_km), direction: f.direction });
      setRegion(r.data.region);
      setZones(r.data.zones);
      setSel(new Set(r.data.zones.map((z) => z.id)));
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const start = async () => {
    setBusy("start");
    try {
      await api.post("/searches", { instruction, region_id: region.id, zone_ids: zones.filter((z) => sel.has(z.id)).map((z) => z.id), category: f.category, subcategory: f.subcategory, max_businesses: Number(f.max_businesses) || 0, mode: f.mode, force_refresh: f.force_refresh });
      toast.success("Search started — watch the agent work");
      nav("/live");
    } catch (e) {
      toast.error(errMsg(e));
    } finally {
      setBusy("");
    }
  };

  const toggle = (id) => setSel((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader eyebrow="Prospecting" title="New Search" desc="Tell the agent what to find. It will split the area into suburbs and cover each one systematically." />
      <Section>
        <div className="eyebrow mb-2">Instruction</div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input data-testid="search-instruction-input" className="h-12 text-base" value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="Find independent cafes in Geelong" />
          <Button data-testid="search-parse-button" className="h-12" onClick={parse} disabled={busy === "parse"}>{busy === "parse" ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Sparkles className="mr-1 h-4 w-4" />}Understand</Button>
        </div>
      </Section>
      <Section title="Search configuration">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Country"><Input data-testid="search-country-input" value={f.country} onChange={(e) => set("country", e.target.value)} /></Field>
          <Field label="State"><select data-testid="search-state-select" className="native w-full" value={f.state} onChange={(e) => set("state", e.target.value)}>{STATES.map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="City"><Input data-testid="search-city-input" value={f.city} onChange={(e) => set("city", e.target.value)} /></Field>
          <Field label="Radius (km)"><Input data-testid="search-radius-input" type="number" value={f.radius_km} onChange={(e) => set("radius_km", e.target.value)} /></Field>
          <Field label="Area"><select data-testid="search-direction-select" className="native w-full" value={f.direction} onChange={(e) => set("direction", e.target.value)}>
            {["all", "inner", "north", "south", "east", "west"].map((d) => <option key={d} value={d}>{d === "all" ? "Whole area" : d === "inner" ? "Inner (≤10 km)" : `${d[0].toUpperCase() + d.slice(1)}ern suburbs`}</option>)}</select></Field>
          <Field label="Business category" hint="Pick or type a custom category">
            <Input data-testid="search-category-input" list="cats" value={f.category} onChange={(e) => set("category", e.target.value)} />
            <datalist id="cats">{cats.map((c) => <option key={c} value={c} />)}</datalist>
          </Field>
          <Field label="Subcategory (optional)" hint="Matched against business names"><Input data-testid="search-subcategory-input" value={f.subcategory} onChange={(e) => set("subcategory", e.target.value)} /></Field>
          <Field label="Max businesses" hint="0 = until sources are exhausted"><Input data-testid="search-max-input" type="number" value={f.max_businesses} onChange={(e) => set("max_businesses", e.target.value)} /></Field>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-6">
          <div className="flex rounded-lg border p-1" data-testid="search-mode-toggle">
            {[["research", "Research & draft only"], ["outreach", "Outreach mode"]].map(([k, l]) => (
              <button key={k} data-testid={`search-mode-${k}`} onClick={() => set("mode", k)} className={`rounded-md px-3 py-1.5 text-sm ${f.mode === k ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}>{l}</button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm"><Switch data-testid="search-force-refresh" checked={f.force_refresh} onCheckedChange={(v) => set("force_refresh", v)} />Re-search zones already covered</label>
          <Button data-testid="search-resolve-button" variant="outline" onClick={resolve} disabled={busy === "resolve"}>{busy === "resolve" ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <MapPinned className="mr-1 h-4 w-4" />}Resolve area into suburbs</Button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">Outreach mode still never sends automatically — every email must be approved and sent through a campaign.</p>
      </Section>
      {zones && (
        <Section title={`${sel.size} of ${zones.length} search zones selected`} right={
          <div className="flex gap-2"><Button size="sm" variant="ghost" onClick={() => setSel(new Set(zones.map((z) => z.id)))} data-testid="zones-select-all">All</Button><Button size="sm" variant="ghost" onClick={() => setSel(new Set())} data-testid="zones-select-none">None</Button></div>}>
          <p className="mb-3 text-xs text-muted-foreground">{region?.display_name} · zones from OpenStreetMap place data. Coverage is limited to what OpenStreetMap contains.</p>
          <div className="flex max-h-72 flex-wrap gap-1.5 overflow-y-auto" data-testid="zones-list">
            {zones.map((z) => (
              <button key={z.id} onClick={() => toggle(z.id)} data-testid={`zone-chip-${z.id}`} className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${sel.has(z.id) ? "border-primary/50 bg-primary/10 text-primary" : "text-muted-foreground"}`}>
                {z.name} <span className="opacity-60">{z.distance_km}km</span>
              </button>
            ))}
          </div>
          <div className="mt-5 flex justify-end"><Button data-testid="search-start-button" size="lg" onClick={start} disabled={!sel.size || busy === "start"}><Rocket className="mr-2 h-4 w-4" />Start search</Button></div>
        </Section>
      )}
    </div>
  );
}
