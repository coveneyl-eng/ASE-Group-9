import { useState } from "react";
import { call, type Session } from "./api";
import { FloodMap } from "./FloodMap";
import type { BusMessage, FloodForecast, FloodImpact } from "./messages";

/** One readable line per message; anything unrecognised falls back to its id. */
function summary(m: BusMessage): string {
  const d = m.data as Record<string, any>;
  switch (m.topic) {
    case "flood.readings": return `${d.sensor_id} ${d.kind} = ${d.value} (${d.source})`;
    case "flood.events": return `Flood at ${d.sensor_id}: ${d.level_m} m ≥ ${d.threshold_m} m`;
    case "flood.impacts": {
      const unsafe = d.impacts.filter((a: any) => a.status === "unsafe").map((a: any) => a.name);
      return `${unsafe.length} unsafe: ${unsafe.join(", ") || "none"}`;
    }
    case "flood.forecast": return `${d.predicted_level_m} m in ${d.horizon_hours} h (${d.expected_impact})`;
    case "traffic.reroute": return `Route via edges ${d.path_edges.join("→")}, lights ${d.closed_light_sites.join(", ") || "none"} held red`;
    case "traffic.signals": return `${d.junction_id}: lights ${d.site_ids.join(", ")} ${d.state} ${d.seconds} s`;
    case "traffic.flow": case "traffic.congestion": return `${d.junction_id}: ${d.level}, speed ratio ${d.speed_ratio}`;
    case "notifications.sent": return `${d.channel} to ${d.recipient} in ${Math.round(d.latency_ms)} ms${d.dry_run ? " (dry run)" : ""}`;
    case "event.upcoming": case "event.watch": return `${d.event_name} at ${d.venue}`;
    case "event.plans": return `${d.event_name}: venue ${d.venue_access}, +${d.predicted_extra_cars} cars`;
    case "event.transport": return `+${d.extra_buses} buses via ${d.routes.join(", ")}`;
    case "dispatch.approved": return `${d.action} approved by ${d.approved_by} (${d.role})`;
    default: return d.id;
  }
}

/** Officials' operations view: live flood picture, approval of responder dispatch, raw agent messages. */
export function Operations({ session, messages }: { session: Session; messages: BusMessage[] }) {
  const [result, setResult] = useState("");
  const impact = messages.find((m) => m.topic === "flood.impacts")?.data as unknown as FloodImpact | undefined;
  const forecast = messages.find((m) => m.topic === "flood.forecast")?.data as unknown as FloodForecast | undefined;

  async function approve() {
    if (!impact) return;
    if (!confirm(`Dispatch responders to flood impact ${impact.id.slice(0, 8)}?`)) return; // explicit confirmation
    try {
      await call(session, "/api/approval/approvals", {
        method: "POST",
        body: JSON.stringify({ impact_id: impact.id, trace_id: impact.trace_id, action: "dispatch_responders", confirm: true }),
      });
      setResult("Dispatch approved and logged");
    } catch (e) {
      setResult(`Rejected: ${e}`);
    }
  }

  return (
    <div className="ops">
      <section className="card">
        <div className="card-head">
          <h2>Live flood picture</h2>
          {forecast && (
            <span className="muted">
              6 h forecast {forecast.predicted_level_m} m ({forecast.expected_impact})
            </span>
          )}
        </div>
        <FloodMap impact={impact} />
        {impact && (
          <p className="row">
            <button onClick={approve}>Approve responder dispatch</button> <span className="muted">{result}</span>
          </p>
        )}
      </section>
      <section className="card">
        <div className="card-head">
          <h2>Agent messages</h2>
        </div>
        <ul className="feed">
          {messages.slice(0, 40).map((m) => (
            <li key={`${m.data.id}-${m.topic}`}>
              <span className="muted">{new Date(m.receivedAt).toLocaleTimeString()}</span> <code>{m.topic}</code>{" "}
              {summary(m)}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
