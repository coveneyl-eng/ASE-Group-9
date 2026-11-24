import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FloodCheck } from "./types";

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

/** Active CFRAM extent + every asset inside it, coloured by grade. */
export function FloodMap({ check }: { check?: FloodCheck }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({
      container: box.current,
      center: [-6.215, 53.345],
      zoom: 12.6,
      style: {
        version: 8,
        sources: {
          osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256,
                 attribution: "© OpenStreetMap contributors" },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
    });
    m.on("load", () => {
      m.addSource("extent", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "extent", type: "fill", source: "extent", paint: { "fill-color": "#1565c0", "fill-opacity": 0.3 } });
      m.addLayer({ id: "extent-line", type: "line", source: "extent", paint: { "line-color": "#1565c0", "line-width": 1.5 } });
      m.addSource("assets", { type: "geojson", data: EMPTY });
      m.addLayer({
        id: "assets", type: "circle", source: "assets",
        paint: {
          "circle-radius": 6, "circle-stroke-width": 1.5, "circle-stroke-color": "#ffffff",
          "circle-color": ["match", ["get", "grade"], "unsafe", "#c62828", "caution", "#f9a825", "#2e7d32"],
        },
      });
      m.on("click", "assets", (e) => {
        const p = e.features?.[0]?.properties as { name: string; grade: string; depth: number | null; kind: string };
        new maplibregl.Popup().setLngLat(e.lngLat)
          .setText(`${p.name} (${p.kind}): ${p.grade}${p.depth != null ? `, ${p.depth} m deep` : ""}`).addTo(m);
      });
    });
    map.current = m;
    // The page layout settles after data arrives; keep the map's canvas in step with its container.
    const resize = new ResizeObserver(() => m.resize());
    resize.observe(box.current);
    return () => {
      resize.disconnect();
      m.remove();
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const draw = () => {
      const extent: GeoJSON.FeatureCollection = check?.extent
        ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: check.extent }] }
        : EMPTY;
      const assets: GeoJSON.FeatureCollection = {
        type: "FeatureCollection",
        features: (check?.assets?.items ?? []).map((a) => ({
          type: "Feature",
          properties: { name: a.name, grade: a.grade, depth: a.depth, kind: a.kind },
          geometry: { type: "Point", coordinates: [a.lon, a.lat] },
        })),
      };
      (m.getSource("extent") as maplibregl.GeoJSONSource).setData(extent);
      (m.getSource("assets") as maplibregl.GeoJSONSource).setData(assets);
      // Zoom to the active extent (and every asset in it) so the whole flood zone is in view.
      const pts: [number, number][] = assets.features.map((f) => (f.geometry as GeoJSON.Point).coordinates as [number, number]);
      const walk = (c: unknown): void => {
        if (Array.isArray(c) && typeof c[0] === "number") pts.push(c as [number, number]);
        else if (Array.isArray(c)) c.forEach(walk);
      };
      if (check?.extent && "coordinates" in check.extent) walk(check.extent.coordinates);
      if (pts.length) {
        const b = pts.reduce((acc, p) => acc.extend(p), new maplibregl.LngLatBounds(pts[0], pts[0]));
        m.resize();
        m.fitBounds(b, { padding: 40, maxZoom: 15, animate: false });
      }
    };
    if (m.getSource("extent")) draw();
    else m.once("load", draw);
  }, [check]);

  return <div ref={box} className="map" aria-label="Flood extent map" />;
}
