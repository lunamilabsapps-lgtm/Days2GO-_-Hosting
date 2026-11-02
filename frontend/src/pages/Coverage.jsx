import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MapContainer, TileLayer, CircleMarker, Tooltip } from "react-leaflet";
import { PageHeader, Section, GradeBadge, StatusBadge, Empty } from "@/components/common";
import { api, fmtDate } from "@/lib/api";
import { MapPin } from "lucide-react";

const COLORS = { unsearched: "#64748B", searching: "#06B6D4", completed: "#10B981", needs_research: "#F59E0B" };

export default function Coverage() {
  const [regions, setRegions] = useState([]);
  const [rid, setRid] = useState("");
  const [cat, setCat] = useState("");
  const [zones, setZones] = useState([]);
  const [zone, setZone] = useState(null);
  const [prospects, setProspects] = useState([]);

  useEffect(() => {
    api.get("/regions").then((r) => {
      setRegions(r.data);
      if (r.data[0]) {
        setRid(r.data[0].id);
        setCat(r.data[0].categories[0] || "");
      }
    });
  }, []);
  useEffect(() => {
    if (!rid) return;
    const load = () => api.get(`/coverage?region_id=${rid}${cat ? `&category=${encodeURIComponent(cat)}` : ""}`).then((r) => setZones(r.data));
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [rid, cat]);
  useEffect(() => {
    if (!zone) return;
    api.get(`/prospects?zone_id=${zone.id}${cat ? `&category=${encodeURIComponent(cat)}` : ""}&page_size=100`).then((r) => setProspects(r.data.items));
  }, [zone, cat]);

  const region = regions.find((r) => r.id === rid);
  const counts = Object.fromEntries(Object.keys(COLORS).map((k) => [k, zones.filter((z) => z.status === k).length]));
  if (!regions.length) return <><PageHeader eyebrow="Coverage" title="Geographic Coverage" /><Empty icon={MapPin} title="No areas resolved yet" desc="Start a search to divide a city into suburbs." /></>;
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Coverage" title="Geographic Coverage" desc="Permanent record of which suburbs have been searched, by category and source.">
        <select className="native" value={rid} onChange={(e) => { setRid(e.target.value); setZone(null); }} data-testid="coverage-region-select">
          {regions.map((r) => <option key={r.id} value={r.id}>{r.name} ({r.radius_km} km)</option>)}
        </select>
        <select className="native" value={cat} onChange={(e) => setCat(e.target.value)} data-testid="coverage-category-select">
          <option value="">All categories</option>
          {(region?.categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </PageHeader>
      <div className="flex flex-wrap gap-3">
        {Object.entries(COLORS).map(([k, c]) => (
          <span key={k} className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs" data-testid={`coverage-legend-${k}`}><span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />{k.replace("_", " ")} · {counts[k]}</span>
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
        <div className="panel overflow-hidden" data-testid="suburb-map-container">
          {region && (
            <MapContainer key={rid} center={[region.lat, region.lon]} zoom={10} style={{ height: 560 }} scrollWheelZoom>
              <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              {zones.map((z) => (
                <CircleMarker key={z.id} center={[z.lat, z.lon]} radius={z.prospects ? Math.min(6 + z.prospects * 1.5, 18) : 5}
                  pathOptions={{ color: COLORS[z.status], fillColor: COLORS[z.status], fillOpacity: zone?.id === z.id ? 0.9 : 0.5, weight: zone?.id === z.id ? 3 : 1 }}
                  eventHandlers={{ click: () => setZone(z) }}>
                  <Tooltip>{z.name}: {z.status.replace("_", " ")} · {z.prospects} prospects</Tooltip>
                </CircleMarker>
              ))}
            </MapContainer>
          )}
        </div>
        <Section title={zone ? zone.name : "Select a suburb"} right={zone && <StatusBadge status={zone.status} />}>
          {!zone && <p className="text-sm text-muted-foreground">Click a suburb on the map to see its coverage history and prospects.</p>}
          {zone && (
            <div className="space-y-4" data-testid="suburb-detail">
              {zone.coverage.map((c) => (
                <div key={c.category + c.source} className="rounded-md bg-muted/60 p-3 text-xs">
                  <div className="font-medium capitalize">{c.category.replace("|", " · ")} via {c.source}</div>
                  <div className="text-muted-foreground">Last searched {fmtDate(c.last_searched_at)} · {c.results_count ?? 0} results · {c.new_count ?? 0} new</div>
                  {c.error && <div className="text-red-500">{c.error}</div>}
                </div>
              ))}
              <div className="eyebrow">{prospects.length} prospects</div>
              <div className="max-h-[340px] space-y-1 overflow-y-auto">
                {prospects.map((p) => (
                  <Link key={p.id} to={`/prospects/${p.id}`} className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm hover:bg-accent" data-testid={`suburb-prospect-${p.id}`}>
                    <span className="truncate">{p.name}</span><GradeBadge grade={p.grade} score={p.score} testid={`suburb-prospect-grade-${p.id}`} />
                  </Link>
                ))}
              </div>
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}
