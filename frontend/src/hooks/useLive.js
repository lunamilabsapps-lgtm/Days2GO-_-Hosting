import { useEffect, useRef, useState } from "react";
import { API, getToken, api } from "@/lib/api";

export function useLive(maxEvents = 200) {
  const [events, setEvents] = useState([]);
  const [state, setState] = useState(null);
  const [connected, setConnected] = useState(false);
  const esRef = useRef(null);

  useEffect(() => {
    api.get("/activity?limit=60").then((r) => setEvents(r.data.reverse())).catch(() => {});
    api.get("/agent/state").then((r) => setState(r.data)).catch(() => {});
    const es = new EventSource(`${API}/stream?token=${getToken()}`);
    esRef.current = es;
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("activity", (e) => {
      const ev = JSON.parse(e.data);
      setEvents((prev) => (prev.some((p) => p.seq === ev.seq) ? prev : [ev, ...prev].slice(0, maxEvents)));
    });
    es.addEventListener("state", (e) => setState(JSON.parse(e.data)));
    return () => {
      es.close();
    };
  }, [maxEvents]);

  return { events, state, setState, connected };
}
