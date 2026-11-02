import { useEffect, useState } from "react";
import { Plus, Save, Archive, BookOpen } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { PageHeader, Field, Empty } from "@/components/common";
import { api, errMsg } from "@/lib/api";

const BLANK = { name: "", description: "", features: [], pricing: "", delivery_scope: "", optional_extras: "", hosting: "", maintenance: "", terms: "", approved: false, active: true };

function ServiceCard({ svc, onDone }) {
  const [s, setS] = useState({ ...svc, featuresText: (svc.features || []).join("\n") });
  const set = (k, v) => setS((p) => ({ ...p, [k]: v }));
  const save = async () => {
    const body = { ...s, features: s.featuresText.split("\n").map((x) => x.trim()).filter(Boolean) };
    delete body.featuresText;
    try {
      svc.id ? await api.put(`/services/${svc.id}`, body) : await api.post("/services", body);
      toast.success("Service saved");
      onDone();
    } catch (e) { toast.error(errMsg(e)); }
  };
  const archive = async () => { if (window.confirm("Archive this service?")) { await api.delete(`/services/${svc.id}`); onDone(); } };
  const tid = svc.id || "new";
  return (
    <div className="panel space-y-4 p-5" data-testid={`service-card-${tid}`}>
      <div className="flex flex-wrap items-center gap-3">
        <Input className="max-w-sm font-display text-base font-semibold" value={s.name} onChange={(e) => set("name", e.target.value)} placeholder="Service name" data-testid={`service-name-${tid}`} />
        <label className="flex items-center gap-2 text-xs"><Switch checked={s.approved} onCheckedChange={(v) => set("approved", v)} data-testid={`service-approved-${tid}`} />Approved for AI use</label>
        <label className="flex items-center gap-2 text-xs"><Switch checked={s.active} onCheckedChange={(v) => set("active", v)} data-testid={`service-active-${tid}`} />Active</label>
        <div className="ml-auto flex gap-2">
          {svc.id && <Button size="sm" variant="ghost" onClick={archive} data-testid={`service-archive-${tid}`}><Archive className="h-4 w-4" /></Button>}
          <Button size="sm" onClick={save} data-testid={`service-save-${tid}`}><Save className="mr-1 h-4 w-4" />Save</Button>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Description"><Textarea rows={3} value={s.description} onChange={(e) => set("description", e.target.value)} data-testid={`service-description-${tid}`} /></Field>
        <Field label="Features (one per line)"><Textarea rows={3} value={s.featuresText} onChange={(e) => set("featuresText", e.target.value)} data-testid={`service-features-${tid}`} /></Field>
        <Field label="Pricing" hint="Leave blank and the AI will not mention prices"><Input value={s.pricing} onChange={(e) => set("pricing", e.target.value)} data-testid={`service-pricing-${tid}`} /></Field>
        <Field label="Delivery scope"><Input value={s.delivery_scope} onChange={(e) => set("delivery_scope", e.target.value)} data-testid={`service-scope-${tid}`} /></Field>
        <Field label="Optional extras"><Input value={s.optional_extras} onChange={(e) => set("optional_extras", e.target.value)} /></Field>
        <Field label="Ongoing hosting"><Input value={s.hosting} onChange={(e) => set("hosting", e.target.value)} /></Field>
        <Field label="Maintenance packages"><Input value={s.maintenance} onChange={(e) => set("maintenance", e.target.value)} /></Field>
        <Field label="Terms and conditions"><Input value={s.terms} onChange={(e) => set("terms", e.target.value)} /></Field>
      </div>
    </div>
  );
}

export default function Services() {
  const [items, setItems] = useState([]);
  const [adding, setAdding] = useState(false);
  const load = () => { setAdding(false); api.get("/services").then((r) => setItems(r.data)); };
  useEffect(() => { load(); }, []);
  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader eyebrow="Offer engine" title="Service Catalogue" desc="The agent only pitches services marked 'Approved for AI use', using only the details written here. Visabal stays excluded until its pricing is approved.">
        <Button onClick={() => setAdding(true)} data-testid="service-add-button"><Plus className="mr-1 h-4 w-4" />Add service</Button>
      </PageHeader>
      {adding && <ServiceCard svc={BLANK} onDone={load} />}
      {!items.length && !adding && <Empty icon={BookOpen} title="No services" />}
      {items.map((s) => <ServiceCard key={s.id + (s.updated_at || "")} svc={s} onDone={load} />)}
    </div>
  );
}
