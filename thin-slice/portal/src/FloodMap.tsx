import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FloodImpact } from "./messages";

const STATUS_COLOUR = { safe: "#2e7d32", caution: "#f9a825", unsafe: "#c62828" };

// Asset positions mirror static/assets.geojson (served from PostGIS in a later iteration).
const ASSET_POS: Record<number, [number, number]> = {
  1: [-6.2195, 53.3385], 2: [-6.215, 53.34], 3: [-6.229, 53.344], 4: [-6.2283, 53.335], 5: [-6.212, 53.342],
};

export function FloodMap({ impact }: { impact?: FloodImpact }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);

  useEffect(() => {
    if (!container.current) return;
    map.current = new maplibregl.Map({
      container: container.current,
      center: [-6.222, 53.339],
      zoom: 14.2,
      style: {
        version: 8,
        sources: {
          osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256,
                 attribution: "© OpenStreetMap contributors" },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
    });
    return () => map.current?.remove();
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !impact) return;
    const draw = () => {
      const data: GeoJSON.Feature = { type: "Feature", properties: {}, geometry: impact.extent_geojson };
      const src = m.getSource("extent") as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      else {
        m.addSource("extent", { type: "geojson", data });
        m.addLayer({ id: "extent", type: "fill", source: "extent", paint: { "fill-color": "#1565c0", "fill-opacity": 0.35 } });
      }
      markers.current.forEach((mk) => mk.remove());
      markers.current = impact.impacts
        .filter((a) => ASSET_POS[a.asset_id])
        .map((a) =>
          new maplibregl.Marker({ color: STATUS_COLOUR[a.status] })
            .setLngLat(ASSET_POS[a.asset_id])
            .setPopup(new maplibregl.Popup().setText(`${a.name}: ${a.status}`))
            .addTo(m),
        );
    };
    if (m.isStyleLoaded()) draw();
    else m.once("load", draw);
  }, [impact]);

  return <div ref={container} style={{ height: 420, borderRadius: 8 }} aria-label="Flood map" />;
}
