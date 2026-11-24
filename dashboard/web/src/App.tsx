import { useState } from "react";
import { FloodMap } from "./FloodMap";
import { FloodPanel } from "./FloodPanel";
import { HealthPanel } from "./HealthPanel";
import { LivePanel } from "./LivePanel";
import { ReadingsPanel } from "./ReadingsPanel";
import { useLiveFeed, usePoll } from "./useApi";
import type { FloodCheck, Health, Readings } from "./types";

export default function App() {
  const [whatIf, setWhatIf] = useState<number | null>(null);
  const health = usePoll<Health>("/api/health", 5000);
  const readings = usePoll<Readings>("/api/readings", 30000);
  const flood = usePoll<FloodCheck>(whatIf === null ? "/api/flood" : `/api/flood?level=${whatIf}`, 30000);
  const live = useLiveFeed();

  return (
    <div className="shell">
      <header className="topbar">
        <strong>Dublin flood thin slice</strong>
        <span className="muted">OPW · Marine Institute · Met Éireann · NTA · GSI · OSM · CSO → PostGIS + Kafka</span>
      </header>
      <main className="grid">
        <div className="col">
          <FloodPanel check={flood.data} whatIf={whatIf} onReset={() => setWhatIf(null)} />
          <section className="card map-card">
            <FloodMap check={flood.data} />
          </section>
          <ReadingsPanel readings={readings.data} node={flood.data?.node} />
        </div>
        <div className="col">
          <LivePanel messages={live.messages} state={live.state} onSimulated={setWhatIf} />
          <HealthPanel health={health.data} error={health.error} />
        </div>
      </main>
    </div>
  );
}
