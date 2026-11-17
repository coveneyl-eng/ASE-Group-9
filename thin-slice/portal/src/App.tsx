import { useEffect, useState } from "react";
import { FloodMap } from "./FloodMap";
import type { BusMessage, FloodForecast, FloodImpact } from "./messages";

const isPublic = new URLSearchParams(location.search).has("public");

async function login(username: string, password: string) {
  const body = new URLSearchParams({ username, password });
  const r = await fetch("/api/approval/token", { method: "POST", body });
  if (!r.ok) throw new Error("Login failed");
  return (await r.json()) as { access_token: string; role: string };
}

function PublicStatusMap() {
  const [impact, setImpact] = useState<FloodImpact>();
  useEffect(() => {
    const load = () =>
      fetch("/api/state").then((r) => r.json()).then((s) => setImpact(s["flood.impacts"]?.data as FloodImpact));
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);
  const unsafe = impact?.impacts.filter((a) => a.status === "unsafe").map((a) => a.name) ?? [];
  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 900, margin: "auto", padding: 16 }}>
      {/* Warning text first so it shows before map tiles on slow connections */}
      <h1>Dublin flood status</h1>
      <p style={{ fontSize: 20 }}>{unsafe.length ? `⚠ Avoid: ${unsafe.join(", ")}` : "No active flood warnings."}</p>
      <FloodMap impact={impact} />
    </main>
  );
}

function OfficialsPortal() {
  const [token, setToken] = useState<string>();
  const [role, setRole] = useState<string>();
  const [feed, setFeed] = useState<BusMessage[]>([]);
  const [impact, setImpact] = useState<FloodImpact>();
  const [forecast, setForecast] = useState<FloodForecast>();
  const [status, setStatus] = useState("disconnected");
  const [result, setResult] = useState("");

  useEffect(() => {
    if (!token) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`);
    ws.onopen = () => setStatus("live");
    ws.onclose = () => setStatus("disconnected");
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data) as BusMessage;
      msg.receivedAt = new Date().toLocaleTimeString();
      setFeed((f) => [msg, ...f].slice(0, 30));
      if (msg.topic === "flood.impacts") setImpact(msg.data as unknown as FloodImpact);
      if (msg.topic === "flood.forecast") setForecast(msg.data as unknown as FloodForecast);
    };
    return () => ws.close();
  }, [token]);

  async function approve() {
    if (!impact || !token) return;
    if (!confirm(`Dispatch responders to flood impact ${impact.id.slice(0, 8)}?`)) return; // explicit confirmation
    const r = await fetch("/api/approval/approvals", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ impact_id: impact.id, trace_id: impact.trace_id, action: "dispatch_responders", confirm: true }),
    });
    setResult(r.ok ? "Dispatch approved and logged" : `Rejected: ${(await r.json()).detail}`);
  }

  if (!token)
    return (
      <form
        style={{ fontFamily: "system-ui", maxWidth: 320, margin: "80px auto", display: "grid", gap: 8 }}
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          try {
            const t = await login(String(f.get("u")), String(f.get("p")));
            setToken(t.access_token);
            setRole(t.role);
          } catch (err) {
            setResult(String(err));
          }
        }}
      >
        <h2>Officials' portal</h2>
        <input name="u" placeholder="username" defaultValue="dispatcher" />
        <input name="p" type="password" placeholder="password" defaultValue="dispatch-demo" />
        <button>Sign in</button>
        <small>{result}</small>
        <a href="?public">Public status map</a>
      </form>
    );

  return (
    <main style={{ fontFamily: "system-ui", padding: 16, display: "grid", gridTemplateColumns: "3fr 2fr", gap: 16 }}>
      <section>
        <h2>Live flood picture <small>({status}, role: {role})</small></h2>
        <FloodMap impact={impact} />
        {forecast && <p>6 h forecast: {forecast.predicted_level_m} m ({forecast.expected_impact})</p>}
        {impact && (
          <p>
            <button onClick={approve}>Approve responder dispatch</button> {result}
          </p>
        )}
      </section>
      <section>
        <h3>Agent messages</h3>
        <ul style={{ fontSize: 13, listStyle: "none", padding: 0 }}>
          {feed.map((m, i) => (
            <li key={i} style={{ borderBottom: "1px solid #ddd", padding: 4 }}>
              <b>{m.receivedAt}</b> <code>{m.topic}</code> {JSON.stringify(m.data).slice(0, 140)}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

export default function App() {
  return isPublic ? <PublicStatusMap /> : <OfficialsPortal />;
}
