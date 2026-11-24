-- Test fixture: a tiny database shaped exactly like flood-thin-slice/load_all.py's output
-- (same table names, columns and EPSG:2157 geometry). Values are illustrative, NOT real survey data.
--   psql "$DATABASE" -f dashboard/tests/seed.sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;

CREATE OR REPLACE FUNCTION pt(lon float, lat float) RETURNS geometry AS
  $$ SELECT ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 2157) $$ LANGUAGE sql IMMUTABLE;
CREATE OR REPLACE FUNCTION bx(w float, s float, e float, n float) RETURNS geometry AS
  $$ SELECT ST_Transform(ST_MakeEnvelope(w, s, e, n, 4326), 2157) $$ LANGUAGE sql IMMUTABLE;

DROP TABLE IF EXISTS readings, cfram_nodes, flood_extent_coast, flood_extent_river, infrastructure, small_areas,
  saps, dsm, opw_latest, tide_readings, met_warnings, met_forecast, bus_stops, bus_routes, gtfsr_trip_updates;

-- Kafka -> detector -> readings (load_all.setup_db)
CREATE TABLE readings(time timestamptz NOT NULL, source text, station text, level_m double precision,
                      PRIMARY KEY (time, source, station));
INSERT INTO readings
SELECT now() - make_interval(mins => 10 * i), 'marine', 'Dublin Port', round((1.9 * sin(i / 37.0 * pi()))::numeric, 3)
FROM generate_series(0, 287) i;
INSERT INTO readings VALUES (now() - interval '5 minutes', 'opw', '0000009102_0001', 0.61),
                            (now() - interval '5 minutes', 'opw', '0000009104_0001', 0.46),
                            (now() - interval '7 minutes', 'marine', 'Howth Harbour', 1.12);

-- CFRAM coastal nodes: extreme water levels (m OD Malin) per annual exceedance probability
CREATE TABLE cfram_nodes("NODE_ID" text, "WL_10PC" float, "WL_05PC" float, "WL_01PC" float, geometry geometry(Point, 2157));
INSERT INTO cfram_nodes VALUES ('DUBLIN_PORT_01', 2.40, 2.75, 3.00, pt(-6.2190, 53.3455)),
                               ('INLAND_00', 0, 0, 0, pt(-6.2217, 53.3457));

-- CFRAM coastal flood extents per band
CREATE TABLE flood_extent_coast(aep text, geometry geometry(Polygon, 2157));
INSERT INTO flood_extent_coast VALUES ('10%',  bx(-6.2150, 53.3440, -6.1950, 53.3480)),
                                      ('0.5%', bx(-6.2300, 53.3400, -6.1850, 53.3500)),
                                      ('0.1%', bx(-6.2350, 53.3370, -6.1800, 53.3520));
CREATE TABLE flood_extent_river(aep text, geometry geometry(Polygon, 2157));
INSERT INTO flood_extent_river VALUES ('1%', bx(-6.2300, 53.3260, -6.2200, 53.3300));

-- OSM infrastructure (load_all.load_osm kinds: critical, bridge, road, rail, building)
CREATE TABLE infrastructure(osm_id text, kind text, name text, tags text, geometry geometry(Geometry, 2157));
INSERT INTO infrastructure VALUES
  ('n1', 'building', '3Arena', '{}', pt(-6.2287, 53.3474)),
  ('n2', 'critical', 'Ringsend Health Centre', '{"amenity":"clinic"}', pt(-6.2195, 53.3385)),
  ('n3', 'bridge', 'Tom Clarke Bridge', '{"bridge":"yes"}', pt(-6.2263, 53.3449)),
  ('n4', 'building', 'Dublin Port Centre', '{}', pt(-6.2120, 53.3480)),
  ('n5', 'critical', 'Poolbeg substation', '{"power":"substation"}', pt(-6.1890, 53.3415)),
  ('w6', 'road', 'Pigeon House Road', '{"highway":"primary"}',
       ST_Transform(ST_SetSRID(ST_MakeLine(ST_MakePoint(-6.2050, 53.3430), ST_MakePoint(-6.1950, 53.3425)), 4326), 2157)),
  ('w7', 'road', 'East Wall Road', '{"highway":"primary"}',
       ST_Transform(ST_SetSRID(ST_MakeLine(ST_MakePoint(-6.2330, 53.3510), ST_MakePoint(-6.2250, 53.3470)), 4326), 2157)),
  ('n8', 'building', 'Grand Canal Theatre', '{}', pt(-6.2395, 53.3441));  -- outside every extent

-- CSO small areas + population
CREATE TABLE small_areas("SA_GUID" text, geometry geometry(Polygon, 2157));
INSERT INTO small_areas VALUES ('SA1', bx(-6.2300, 53.3380, -6.2200, 53.3420)),
                               ('SA2', bx(-6.2100, 53.3420, -6.2000, 53.3460)),
                               ('SA3', bx(-6.2600, 53.3500, -6.2500, 53.3550));
CREATE TABLE saps("GUID" text, "T1_1AGETT" int);
INSERT INTO saps VALUES ('SA1', 312), ('SA2', 287), ('SA3', 401);

-- LiDAR surface model: three 1 km tiles, ground at 2.0 / 2.45 / 2.75 m (west to east)
CREATE TABLE dsm(rid serial, rast raster);
INSERT INTO dsm(rast)
SELECT ST_AddBand(ST_MakeEmptyRaster(100, 200, ST_X(o) + 1000 * k, ST_Y(o), 10, -10, 0, 0, 2157), '32BF', v, -9999)
FROM (SELECT pt(-6.2400, 53.3530) AS o) a,
     (VALUES (0, 2.0), (1, 2.45), (2, 2.75), (3, 2.75)) t(k, v);
CREATE INDEX ON dsm USING gist (ST_ConvexHull(rast));

-- Live-feed tables (only their row counts are shown)
CREATE TABLE opw_latest(station_ref text, value float, geometry geometry(Point, 2157));
INSERT INTO opw_latest VALUES ('0000009102', 0.61, pt(-6.2290, 53.3270)), ('0000009104', 0.46, pt(-6.2627, 53.3135));
CREATE TABLE tide_readings(station_id text, "Water_Level_OD_Malin" float, geometry geometry(Point, 2157));
INSERT INTO tide_readings VALUES ('Dublin Port', 1.12, pt(-6.2217, 53.3457));
CREATE TABLE met_warnings(raw text);
CREATE TABLE met_forecast("from" text, "to" text, precip_mm float);
INSERT INTO met_forecast VALUES ('2026-11-24T12:00:00Z', '2026-11-24T13:00:00Z', 0.4);
CREATE TABLE bus_stops(stop_id text, stop_name text, geometry geometry(Point, 2157));
INSERT INTO bus_stops VALUES ('8220DB000495', 'Ringsend Road', pt(-6.2290, 53.3410));
CREATE TABLE bus_routes(route_id text, route_short_name text);
INSERT INTO bus_routes VALUES ('1', '1'), ('47', '47');
CREATE TABLE gtfsr_trip_updates(raw text);
INSERT INTO gtfsr_trip_updates VALUES ('{}'), ('{}');
-- icwws_points deliberately left out: the dashboard must show a layer that did not load
