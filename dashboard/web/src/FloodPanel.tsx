import type { FloodCheck, Grade } from "./types";

const GRADE_ORDER: Grade[] = ["unsafe", "caution", "safe"];

/** Water level against the nearest CFRAM node's thresholds: where it sits says which extent is active. */
function Ladder({ level, node }: { level: number; node: NonNullable<FloodCheck["node"]> }) {
  const lo = Math.min(level, node.wl_10) - 0.6;
  const hi = Math.max(level, node.wl_01) + 0.3;
  const H = 180;
  const y = (v: number) => 12 + (1 - (v - lo) / (hi - lo)) * (H - 24);
  const marks = [
    { label: "0.1% AEP", v: node.wl_01 },
    { label: "0.5% AEP", v: node.wl_05 },
    { label: "10% AEP", v: node.wl_10 },
  ];
  return (
    <svg viewBox={`0 0 220 ${H}`} className="ladder" role="img" aria-label={`Dublin Port at ${level.toFixed(2)} m`}>
      <rect x="40" y={y(node.wl_10)} width="60" height={H - 12 - y(node.wl_10)} className="ladder-safe" />
      <rect x="40" y="12" width="60" height={y(node.wl_10) - 12} className="ladder-flood" />
      {marks.map((m) => (
        <g key={m.label}>
          <line x1="36" x2="104" y1={y(m.v)} y2={y(m.v)} className="ladder-mark" />
          <text x="110" y={y(m.v) + 4} className="ladder-label">
            {m.label} · {m.v.toFixed(2)} m
          </text>
        </g>
      ))}
      <line x1="28" x2="112" y1={y(level)} y2={y(level)} className="ladder-level" />
      <text x="4" y={y(level) - 6} className="ladder-level-text">
        {level.toFixed(2)} m
      </text>
    </svg>
  );
}

export function FloodPanel({ check, whatIf, onReset }: { check?: FloodCheck; whatIf: number | null; onReset: () => void }) {
  if (!check) return <section className="card">Running the flood check…</section>;
  const level = check.level;
  return (
    <section className="card">
      <div className="card-head">
        <h2>Flood check · Dublin Port</h2>
        {whatIf !== null && (
          <button className="link" onClick={onReset}>
            Back to the latest real reading
          </button>
        )}
      </div>
      {check.status === "skipped" ? (
        <p className="muted">Skipped: {check.reason}</p>
      ) : (
        <>
          <div className="flood-top">
            {level && check.node && <Ladder level={level.value} node={check.node} />}
            <div>
              <div className={`band band-${check.band ? "active" : "none"}`}>
                {check.band ? `${check.band} AEP coastal extent active` : "Below the 10% AEP level: no flood extent active"}
              </div>
              {level && (
                <p className="muted">
                  {level.simulated ? "What-if level from a simulated reading" : `Latest ${level.source} reading`}
                  {level.time ? ` · ${new Date(level.time).toLocaleString()}` : ""}
                </p>
              )}
              {check.assets && check.band && (
                <>
                  <div className="grades">
                    {GRADE_ORDER.map((g) => (
                      <div key={g} className={`grade grade-${g}`}>
                        <b>{check.assets!.by_grade[g] ?? 0}</b> {g}
                      </div>
                    ))}
                  </div>
                  <p className="muted">
                    {check.assets.total} assets inside the extent
                    {check.small_areas_touched != null && ` · ${check.small_areas_touched} CSO small areas touched`}
                  </p>
                </>
              )}
              {check.status === "partial" && <p className="muted">{check.reason}</p>}
            </div>
          </div>
          {check.assets && check.assets.items.length > 0 && (
            <table className="assets">
              <thead>
                <tr>
                  <th>Grade</th>
                  <th>Kind</th>
                  <th>Name</th>
                  <th className="num">Depth (m)</th>
                </tr>
              </thead>
              <tbody>
                {check.assets.items.slice(0, 12).map((a, i) => (
                  <tr key={`${a.name}-${i}`}>
                    <td>
                      <span className={`pill grade-${a.grade}`}>{a.grade}</span>
                    </td>
                    <td>{a.kind}</td>
                    <td>{a.name}</td>
                    <td className="num">{a.depth === null ? "n/a" : a.depth.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {check.assets && check.assets.total > 12 && (
            <p className="muted small">Showing 12 of {check.assets.total}; all are on the map.</p>
          )}
        </>
      )}
    </section>
  );
}
