import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, MessageSquareReply, AlertTriangle, Star, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { PageHeader, Section, Empty, RepliedTag } from "@/components/common";
import { api, fmtDate, label, errMsg } from "@/lib/api";

const ICON = { reply: MessageSquareReply, research_error: AlertTriangle, api_failure: AlertTriangle, delivery_problem: AlertTriangle, high_quality_prospect: Star };

export default function Notifications() {
  const [items, setItems] = useState([]);
  const [prefs, setPrefs] = useState(null);
  const load = () => api.get("/notifications").then((r) => setItems(r.data));
  useEffect(() => { load(); api.get("/settings").then((r) => setPrefs(r.data.notifications)); }, []);
  const readAll = async () => { await api.post("/notifications/read-all"); load(); };
  const read = async (id) => { await api.post(`/notifications/${id}/read`); load(); };
  const savePref = async (k, v) => {
    const n = { ...prefs, [k]: v };
    setPrefs(n);
    try { await api.put("/settings/notifications", n); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Alerts" title="Notifications"><Button variant="outline" onClick={readAll} data-testid="notifications-read-all">Mark all read</Button></PageHeader>
      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <div className="space-y-2">
          {!items.length && <Empty icon={Bell} title="No notifications" />}
          {items.map((n) => {
            const I = ICON[n.type] || CheckCircle2;
            const reply = n.type === "reply";
            return (
              <div key={n.id} onClick={() => !n.read && read(n.id)} data-testid={`notification-${n.id}`}
                className={`panel flex cursor-pointer items-start gap-3 p-4 ${reply ? "border-emerald-500/50 bg-emerald-500/[0.06]" : ""} ${n.read ? "opacity-60" : ""}`}>
                <I className={`mt-0.5 h-4 w-4 shrink-0 ${reply ? "text-emerald-500" : n.priority === "high" ? "text-amber-500" : "text-primary"}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 font-medium">{reply && <RepliedTag testid={`notification-reply-tag-${n.id}`} />}{n.title}{!n.read && <span className="h-2 w-2 rounded-full bg-cyan-500" />}</div>
                  {n.body && <div className="mt-0.5 text-sm text-muted-foreground">{n.body}</div>}
                  <div className="mt-1 text-xs text-muted-foreground">{label(n.type)} · {fmtDate(n.created_at)} {n.link && <Link to={n.link} className="ml-2 text-primary">Open →</Link>}</div>
                </div>
              </div>
            );
          })}
        </div>
        {prefs && (
          <Section title="Notification preferences">
            <div className="space-y-3">
              {Object.entries(prefs).map(([k, v]) => (
                <label key={k} className="flex items-center justify-between text-sm capitalize"><span>{label(k)}{k === "reply" && " (always shown)"}</span><Switch checked={v} disabled={k === "reply"} onCheckedChange={(x) => savePref(k, x)} data-testid={`pref-${k}`} /></label>
              ))}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}
