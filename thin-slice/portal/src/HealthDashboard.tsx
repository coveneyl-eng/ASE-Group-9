import { useEffect, useMemo, useState } from "react";
import { call, parseTime, type Session } from "./api";
import type { BusMessage, CheckStatus, HealthCheck, MessageBase, SystemStatus } from "./messages";

const POLL_MS = 3000;
const GROUP_ORDER = [
  "Field network", "Event bus", "Agents · Ingest", "Agents · Flood", "Agents · Traffic", "Agents · Event",
  "Data", "Communication", "City systems", "Edge", "Observability",
];
const STATUS_LABEL: Record<CheckStatus, string> = { ok: "Healthy", degraded: "Degraded", down: "Down", skipped: "Not deployed" };

/** The flood path one reading takes, in order. Each stage is "done" when a message with the trace id appears. */
const STAGES: { id: string; name: string; tech: string; branch?: true; match: (m: BusMessage) => boolean }[] = [
  { id: "sensor", name: "Sensor reading", tech: "MQTT over TLS", match: (m) => m.topic === "flood.readings" },
  { id: "bridge", name: "MQTT bridge", tech: "Kafka flood.readings", match: (m) => m.topic === "flood.readings" },
  { id: "detect", name: "Flood Detector", tech: "flood.events", match: (m) => m.topic === "flood.events" },
  { id: "scope", name: "Flood Scope", tech: "PostGIS → flood.impacts", match: (m) => m.topic === "flood.impacts" },
  { id: "reroute", name: "Rerouting", tech: "pgRouting + traffic lights", branch: true, match: (m) => m.topic === "traffic.reroute" },
  { id: "sms", name: "SMS alert", tech: "SMSAPI", branch: true, match: (m) => m.topic === "notifications.sent" && m.data.channel === "sms" },
  { id: "email", name: "Email alert", tech: "Gmail API", branch: true, match: (m) => m.topic === "notifications.sent" && m.data.channel === "email" },
  { id: "portal", name: "This dashboard", tech: "WebSocket via NGINX", match: (m) => m.topic === "flood.impacts" },
];

function ago(seconds: number | null) {
  if (seconds === null) return "never";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function Summary({ checks }: { checks: HealthCheck[] }) {
  const deployed = checks.filter((c) => c.status !== "skipped");
  const healthy = deployed.filter((c) => c.status === "ok").length;
  const down = deployed.filter((c) => c.status === "down").length;
  const degraded = deployed.filter((c) => c.status === "degraded").length;
  const tone = down ? "down" : degraded ? "degraded" : "ok";
  return (
    <div className={`summary summary-${tone}`}>
      <div className="summary-big">
        {healthy}/{deployed.length}
      </div>
      <div>
        <div className="summary-title">
          {down ? `${down} component${down > 1 ? "s" : ""} down` : degraded ? "Running with warnings" : "All components healthy"}
        </div>
        <div className="muted">
          {degraded ? `${degraded} degraded · ` : ""}
          {checks.length - deployed.length} not deployed in this environment
        </div>
      </div>
    </div>
  );
}

function Pipeline({ messages, trace }: { messages: BusMessage[]; trace?: string }) {
  const traced = useMemo(() => (trace ? messages.filter((m) => m.data.trace_id === trace) : []), [messages, trace]);
  const reading = traced.find((m) => m.topic === "flood.readings");
  const t0 = reading ? parseTime(String(reading.data.observed_at)) : undefined;
  const offset = (m: MessageBase) => (t0 === undefined ? undefined : parseTime(m.created_at) - t0);

  return (
    <section className="card">
      <div className="card-head">
        <h2>Live flood pipeline</h2>
        <span className="muted">{trace ? `trace ${trace.slice(0, 8)}` : "waiting for a flood reading"}</span>
      </div>
      <ol className="pipeline">
        {STAGES.map((s, i) => {
          const fork = s.branch && !STAGES.at(i - 1)?.branch;
          const hit = traced.find(s.match);
          let time = "";
          if (hit && s.id === "sensor") time = "t = 0";
          else if (hit && (s.id === "sms" || s.id === "email")) time = `${Math.round(Number(hit.data.latency_ms))} ms`;
          else if (hit && s.id === "portal") time = "received";
          else if (hit) time = `${Math.max(0, Math.round(offset(hit.data) ?? 0))} ms`;
          const cls = `stage${hit ? " done" : trace ? " waiting" : ""}${s.branch ? " branch" : ""}`;
          return (
            <li key={s.id} className={cls}>
              {fork && <span className="fork muted">in parallel after Flood Scope</span>}
              <span className="dot" />
              <span className="stage-name">{s.name}</span>
              <span className="stage-tech">{s.tech}</span>
              <span className="stage-time">{time}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function TestFlood({ session, onSent }: { session: Session; onSent: (trace: string) => void }) {
  const [level, setLevel] = useState(3.2);
  const [state, setState] = useState("");
  const allowed = session.role === "emergency_responder";
  async function send() {
    setState("Sending…");
    try {
      const r = await call<{ trace_id: string }>(session, "/api/hub/simulate-flood", {
        method: "POST",
        body: JSON.stringify({ level_m: level }),
      });
      onSent(r.trace_id);
      setState(`Sent to the field broker, trace ${r.trace_id.slice(0, 8)}`);
    } catch (e) {
      setState(String(e));
    }
  }
  return (
    <section className="card">
      <div className="card-head">
        <h2>Test flood reading</h2>
      </div>
      <p className="muted">
        Publishes one reading on the Dodder at Ringsend gauge through Mosquitto, exactly as a field sensor would. The
        flood threshold there is 2.5 m.
      </p>
      <div className="row">
        <label>
          Level (m){" "}
          <input type="number" step="0.1" min="0" max="10" value={level} onChange={(e) => setLevel(Number(e.target.value))} />
        </label>
        <button onClick={send} disabled={!allowed}>
          Send reading
        </button>
      </div>
      <p className="muted small">{allowed ? state : `Only emergency responders can send test readings (you are ${session.role}).`}</p>
    </section>
  );
}

function Latency({ latency }: { latency: SystemStatus["latency"] }) {
  const p95 = latency.p95_ms;
  const pct = p95 === null ? 0 : Math.min(100, (p95 / latency.target_ms) * 100);
  const within = p95 !== null && p95 <= latency.target_ms;
  return (
    <section className="card">
      <div className="card-head">
        <h2>Sensor-to-alert latency</h2>
        <span className="muted">last hour</span>
      </div>
      <div className="latency-big">
        {p95 === null ? "–" : `${(p95 / 1000).toFixed(2)} s`} <span className="muted">p95</span>
      </div>
      <div className="bar">
        <div className={within ? "bar-fill ok" : "bar-fill down"} style={{ width: `${pct}%` }} />
      </div>
      <div className="muted small">
        Target 95% within {latency.target_ms / 1000} s · {latency.alerts_last_hour} alerts · last{" "}
        {latency.last_ms === null ? "–" : `${Math.round(latency.last_ms)} ms`}
      </div>
    </section>
  );
}

function Topics({ topics, messages }: { topics: SystemStatus["topics"]; messages: BusMessage[] }) {
  const recent = new Set(messages.filter((m) => Date.now() - m.receivedAt < 4000).map((m) => m.topic));
  return (
    <section className="card">
      <div className="card-head">
        <h2>Kafka topics</h2>
        <span className="muted">messages seen by the hub</span>
      </div>
      <table className="topics">
        <tbody>
          {topics.map((t) => (
            <tr key={t.topic} className={recent.has(t.topic) ? "flash" : ""}>
              <td>
                <code>{t.topic}</code>
              </td>
              <td className="num">{t.count}</td>
              <td className="muted">{ago(t.seconds_ago)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Components({ checks }: { checks: HealthCheck[] }) {
  const groups = GROUP_ORDER.map((g) => ({ g, items: checks.filter((c) => c.group === g) })).filter((x) => x.items.length);
  return (
    <section className="card">
      <div className="card-head">
        <h2>Components</h2>
        <span className="muted">probed every {POLL_MS / 1000} s</span>
      </div>
      <div className="groups">
        {groups.map(({ g, items }) => (
          <div key={g} className="group">
            <h3>{g}</h3>
            {items.map((c) => (
              <div key={c.id} className={`check check-${c.status}`} title={`${STATUS_LABEL[c.status]} · checked in ${c.ms} ms`}>
                <span className="dot" aria-label={STATUS_LABEL[c.status]} />
                <div>
                  <div className="check-name">{c.name}</div>
                  <div className="check-detail">{c.detail}</div>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

export function HealthDashboard({ session, messages }: { session: Session; messages: BusMessage[] }) {
  const [status, setStatus] = useState<SystemStatus>();
  const [error, setError] = useState("");
  const [sentTrace, setSentTrace] = useState<string>();

  useEffect(() => {
    let alive = true;
    const load = () =>
      call<SystemStatus>(session, "/api/hub/status")
        .then((s) => alive && (setStatus(s), setError("")))
        .catch((e) => alive && setError(String(e)));
    load();
    const id = setInterval(load, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [session]);

  // Follow the reading this user sent; otherwise the latest reading that turned into a flood event.
  const trace = sentTrace ?? messages.find((m) => m.topic === "flood.events")?.data.trace_id;

  if (!status)
    return <p className="muted pad">{error ? `Cannot reach the WebSocket hub: ${error}` : "Probing components…"}</p>;
  return (
    <div className="dashboard">
      {error && <div className="banner">Status is stale: {error}</div>}
      <div className="top-row">
        <Summary checks={status.checks} />
        <Latency latency={status.latency} />
      </div>
      <div className="main-grid">
        <div className="col">
          <Pipeline messages={messages} trace={trace} />
          <TestFlood session={session} onSent={setSentTrace} />
          <Topics topics={status.topics} messages={messages} />
        </div>
        <Components checks={status.checks} />
      </div>
    </div>
  );
}
