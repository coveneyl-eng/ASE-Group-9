// Mirrors the JSON returned by dashboard/api/app.py (keep field names identical).
export type Status = "ok" | "degraded" | "down";
export type LayerStatus = "ok" | "empty" | "missing";
export type Grade = "safe" | "caution" | "unsafe";

export interface Component {
  name: string;
  status: Status;
  detail: string;
  ms: number;
}

export interface Layer {
  group: string;
  source: string; // load_all.py's source name
  table: string;
  status: LayerStatus;
  rows: number | null;
  detail: string;
}

export interface Health {
  components: Component[];
  layers: Layer[];
  live: { connected_clients: number; messages_seen: number; last_message_s_ago: number | null };
  generated_at: number;
}

export interface Reading {
  id?: string;
  source: string;
  station: string;
  level_m: number;
  time: string;
}

export interface LiveMessage {
  reading: Reading;
  partition: number;
  offset: number;
  received_at: string;
}

export interface Readings {
  latest: Reading[];
  dublin_port: { time: string; level_m: number }[];
}

export interface Asset {
  kind: string;
  name: string;
  depth: number | null;
  grade: Grade;
  lon: number;
  lat: number;
}

export interface FloodCheck {
  status: "ok" | "partial" | "skipped";
  reason?: string;
  level?: { value: number; source: string; time: string | null; simulated: boolean };
  node?: { wl_10: number; wl_05: number; wl_01: number } | null;
  band?: "10%" | "0.5%" | "0.1%" | null;
  assets?: { total: number; by_grade: Partial<Record<Grade, number>>; by_kind: Record<string, number>; items: Asset[] };
  small_areas_touched?: number | null;
  extent?: GeoJSON.Geometry | null;
}
