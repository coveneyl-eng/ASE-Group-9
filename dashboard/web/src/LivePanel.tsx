import { useState } from "react";
import { clock, type FeedState } from "./useApi";
import type { LiveMessage, Reading } from "./types";

/** The Kafka topic as it happens, plus a button that sends a simulated Dublin Port reading through it. */
export function LivePanel({ messages, state, onSimulated }: {
  messages: LiveMessage[];
  state: FeedState;
  onSimulated: (level: number) => void;
}) {
  const [level, setLevel] = useState(2.9);
  const [note, setNote] = useState("");

  async function send() {
    setNote("Publishing to Kafka…");
    try {
      const r = await fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ level_m: level }),
      });
      const body = (await r.json()) as Reading & { detail?: string };
      if (!r.ok) throw new Error(body.detail ?? r.statusText);
      setNote(`Published ${body.id?.slice(0, 8)}; watch it arrive below`);
      onSimulated(level);
    } catch (e) {
      setNote(`Failed: ${e instanceof Error ? e.message : e}`);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>Kafka · flood.readings</h2>
        <span className={`conn conn-${state}`}>{state === "live" ? "Live" : state}</span>
      </div>
      <div className="row">
        <label>
          Simulate Dublin Port at{" "}
          <input type="number" step="0.1" value={level} onChange={(e) => setLevel(Number(e.target.value))} /> m
        </label>
        <button onClick={send}>Send through Kafka</button>
      </div>
      <p className="muted small">
        {note || "Same message format as load_all.py's SIM_LEVEL. The flood check then shows what that level would flood."}
      </p>
      <ul className="feed">
        {messages.length === 0 && <li className="muted">Waiting for messages… run load_all.py or send a simulated reading.</li>}
        {messages.map((m) => (
          <li key={`${m.partition}-${m.offset}`} className={m.reading.source === "simulated" ? "sim" : ""}>
            <span className="muted">{clock(m.received_at)}</span>
            <code>#{m.offset}</code>
            <span>{m.reading.station}</span>
            <b>{Number(m.reading.level_m).toFixed(2)} m</b>
            <span className="muted">{m.reading.source}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
