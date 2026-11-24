import { parseTime } from "./useApi";
import type { FloodCheck, Readings } from "./types";

/** Dublin Port over the last 48 h, with the 10% AEP threshold for scale, plus the latest value per station. */
export function ReadingsPanel({ readings, node }: { readings?: Readings; node?: FloodCheck["node"] }) {
  const pts = readings?.dublin_port ?? [];
  const W = 760, H = 170, pad = 34;
  let chart = <p className="muted">No Dublin Port readings in the last 48 h.</p>;
  if (pts.length > 1) {
    const t = pts.map((p) => parseTime(p.time));
    const v = pts.map((p) => p.level_m);
    const lo = Math.min(...v, node?.wl_10 ?? Infinity) - 0.2;
    const hi = Math.max(...v, node?.wl_10 ?? -Infinity) + 0.2;
    const X = (x: number) => pad + ((x - t[0]) / (t[t.length - 1] - t[0] || 1)) * (W - pad - 8);
    const Y = (y: number) => 8 + (1 - (y - lo) / (hi - lo)) * (H - 28);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${X(t[i]).toFixed(1)},${Y(p.level_m).toFixed(1)}`).join("");
    const ticks = [lo + 0.2, (lo + hi) / 2, hi - 0.2];
    chart = (
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Dublin Port water level, last 48 hours">
        {ticks.map((y) => (
          <g key={y}>
            <line x1={pad} x2={W - 8} y1={Y(y)} y2={Y(y)} className="grid" />
            <text x={pad - 4} y={Y(y) + 4} className="axis" textAnchor="end">{y.toFixed(1)}</text>
          </g>
        ))}
        {node && (
          <g>
            <line x1={pad} x2={W - 8} y1={Y(node.wl_10)} y2={Y(node.wl_10)} className="threshold" />
            <text x={W - 10} y={Y(node.wl_10) - 4} className="axis" textAnchor="end">10% AEP {node.wl_10.toFixed(2)} m</text>
          </g>
        )}
        <path d={d} className="line" />
        <text x={pad} y={H - 6} className="axis">{new Date(t[0]).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}</text>
        <text x={W - 8} y={H - 6} className="axis" textAnchor="end">now</text>
      </svg>
    );
  }
  return (
    <section className="card">
      <div className="card-head">
        <h2>Water levels</h2>
        <span className="muted">m OD Malin · readings table</span>
      </div>
      {chart}
      <table className="assets">
        <thead>
          <tr><th>Station</th><th>Source</th><th className="num">Level (m)</th><th>Time</th></tr>
        </thead>
        <tbody>
          {(readings?.latest ?? []).map((r) => (
            <tr key={`${r.source}-${r.station}`}>
              <td>{r.station}</td>
              <td>{r.source}</td>
              <td className="num">{r.level_m.toFixed(2)}</td>
              <td className="muted">{new Date(parseTime(r.time)).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
