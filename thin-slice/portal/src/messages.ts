// TypeScript mirrors of smartcity/models.py and the hub's /status response (DRY: keep field names identical).
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
  closed_light_sites: string[];
}

export interface NotificationSent {
  channel: "sms" | "email" | "websocket";
  recipient: string;
  text: string;
  latency_ms: number;
  dry_run: boolean;
}

/** Every Kafka message carries these (smartcity.models.Message). */
export interface MessageBase {
  id: string;
  trace_id: string;
  created_at: string;
  [key: string]: unknown;
}

export interface BusMessage {
  topic: string;
  data: MessageBase;
  receivedAt: number; // ms since epoch, client clock
}

export type CheckStatus = "ok" | "degraded" | "down" | "skipped";

export interface HealthCheck {
  id: string;
  name: string;
  group: string;
  status: CheckStatus;
  detail: string;
  ms: number;
}

export interface TopicActivity {
  topic: string;
  count: number;
  seconds_ago: number | null;
}

export interface SystemStatus {
  checks: HealthCheck[];
  topics: TopicActivity[];
  latency: { alerts_last_hour: number; p95_ms: number | null; last_ms: number | null; target_ms: number };
  generated_at: number;
}
