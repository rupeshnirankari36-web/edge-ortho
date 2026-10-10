import { useEffect, useRef, useState } from "react";
import L from "leaflet";

interface Meta {
  width: number;
  height: number;
  tile: number;
  maxz: number;
}

/**
 * Pan/zoom "map" of the photographic mosaic.
 * Uses Leaflet's flat CRS.Simple (no lat/lon, no basemap) on a pre-cut tile
 * pyramid, so the picture looks exactly like the stitched photo at every zoom.
 */
export function PhotoMap({ baseUrl = "/mosaic", className = "" }: { baseUrl?: string; className?: string }) {
  const el = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!el.current) return;
    let map: L.Map | null = null;
    let cancelled = false;

    fetch(`${baseUrl}/meta.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`meta.json ${r.status}`))))
      .then((m: Meta) => {
        if (cancelled || !el.current) return;
        map = L.map(el.current, {
          crs: L.CRS.Simple,
          minZoom: 0,
          maxZoom: m.maxz + 2,
          zoomSnap: 0.25,
          attributionControl: false,
        });
        // image pixel (x,y) at the finest level -> Leaflet lat/lng
        const sw = map.unproject([0, m.height], m.maxz);
        const ne = map.unproject([m.width, 0], m.maxz);
        const bounds = L.latLngBounds(sw, ne);

        L.tileLayer(`${baseUrl}/tiles/{z}/{x}/{y}.jpg`, {
          tileSize: m.tile,
          minNativeZoom: 0,
          maxNativeZoom: m.maxz,
          maxZoom: m.maxz + 2,
          noWrap: true,
          bounds,
        }).addTo(map);

        map.fitBounds(bounds);
        map.setMaxBounds(bounds.pad(0.25));
      })
      .catch((e: Error) => setError(e.message));

    return () => {
      cancelled = true;
      map?.remove();
    };
  }, [baseUrl]);

  return (
    <div className={`relative ${className}`}>
      <div ref={el} className="h-full w-full" style={{ background: "#fff" }} />
      {error ? <p className="absolute left-3 top-3 text-xs text-red-600">Could not load mosaic: {error}</p> : null}
    </div>
  );
}
