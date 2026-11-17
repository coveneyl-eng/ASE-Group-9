// TypeScript mirrors of smartcity/models.py (DRY: keep field names identical).
export interface AssetImpact {
  asset_id: number;
  name: string;
  kind: string;
  status: "safe" | "caution" | "unsafe";
}

export interface FloodImpact {
  id: string;
  trace_id: string;
  event_id: string;
  sensor_id: string;
  extent_geojson: GeoJSON.Geometry;
  impacts: AssetImpact[];
  observed_at: string;
}

export interface FloodForecast {
  horizon_hours: number;
  predicted_level_m: number;
  expected_impact: "none" | "minor" | "major";
}

export interface RerouteCommand {
  impact_id: string;
  path_edges: number[];
  avoided_edges: number[];
  total_cost: number;
}

export interface NotificationSent {
  channel: "sms" | "email" | "websocket";
  recipient: string;
  text: string;
  latency_ms: number;
  dry_run: boolean;
}

export interface BusMessage {
  topic: string;
  data: Record<string, unknown>;
  receivedAt?: string;
}
