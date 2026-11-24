import type { Health } from "./types";

const GROUPS = ["Live feeds", "Static layers", "Kafka → database"];

/** Infrastructure probes + every data layer load_all.py writes, with its row count. */
export function HealthPanel({ health, error }: { health?: Health; error: string }) {
  if (!health) return <section className="card">{error ? `API unreachable: ${error}` : "Checking components…"}</section>;
  const loaded = health.layers.filter((l) => l.status !== "missing").length;
  const down = health.components.filter((c) => c.status === "down").length;
  const tone = down ? "down" : health.components.some((c) => c.status === "degraded") ? "degraded" : "ok";
  return (
    <section className="card">
      <div className={`summary summary-${tone}`}>
        <div className="summary-big">
          {loaded}/{health.layers.length}
        </div>
        <div>
          <div className="summary-title">data layers loaded</div>
          <div className="muted">
            {down ? `${down} component${down > 1 ? "s" : ""} down` : tone === "degraded" ? "running with warnings" : "all components up"}
            {error && " · status may be stale"}
          </div>
        </div>
      </div>

      <h3>Infrastructure</h3>
      {health.components.map((c) => (
        <div key={c.name} className={`check check-${c.status}`} title={`checked in ${c.ms} ms`}>
          <span className="dot" />
          <div>
            <div className="check-name">{c.name}</div>
            <div className="check-detail">{c.detail}</div>
          </div>
        </div>
      ))}

      {GROUPS.map((g) => (
        <div key={g}>
          <h3>{g}</h3>
          {health.layers
            .filter((l) => l.group === g)
            .map((l) => (
              <div key={l.table} className={`check layer-${l.status}`}>
                <span className="dot" />
                <div>
                  <div className="check-name">
                    {l.source} <code className="muted">{l.table}</code>
                  </div>
                  <div className="check-detail">{l.status === "missing" ? "not loaded — see load_all.py output" : l.detail}</div>
                </div>
              </div>
            ))}
        </div>
      ))}
    </section>
  );
}
