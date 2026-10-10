import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import type { GeoJSON as LeafletGeoJSON, ImageOverlay, Map as LeafletMap, TileLayer } from "leaflet";
import { Crosshair, Eye, EyeOff, Layers, Minus, Plus } from "lucide-react";
import { cx, Hint, Tooltip } from "./ui";

export interface MapLayers {
  footprint: GeoJSON.FeatureCollection | null;
  flightPath: GeoJSON.FeatureCollection | null;
  preview: string | null;
  previewBounds: [number, number, number, number] | null; // south, west, north, east for Leaflet
  outputBounds: [number, number, number, number] | null; // south, west, north, east for Leaflet
  tileUrlTemplate: string | null;
  tileMinZoom: number | null;
  tileMaxZoom: number | null;
}

interface Props {
  layers: MapLayers;
  className?: string;
  /** Centre when nothing is loaded yet; defaults to a neutral world view. */
  initialCenter?: [number, number];
  initialZoom?: number;
  onFeatureClick?: (feature: GeoJSON.Feature) => void;
  showBasemapToggle?: boolean;
}

const FOOTPRINT_STYLE: L.PathOptions = {
  color: "#2F5B4A",
  weight: 1,
  opacity: 0.75,
  fillColor: "#3F735E",
  fillOpacity: 0.08,
};
const PATH_STYLE: L.PathOptions = { color: "#B4744A", weight: 1.6, opacity: 0.9, dashArray: "4 3" };

export function MapView({
  layers,
  className,
  initialCenter = [46.8427, -91.994],
  initialZoom = 16,
  onFeatureClick,
  showBasemapToggle = true,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const groupsRef = useRef<{
    footprint?: LeafletGeoJSON;
    path?: LeafletGeoJSON;
    tiles?: TileLayer;
    preview?: ImageOverlay;
    basemap?: TileLayer;
  }>({});
  const [visible, setVisible] = useState({
    footprint: true,
    flightPath: true,
    output: true,
    basemap: false,
  });
  const [ready, setReady] = useState(false);

  /* ------------------------------------------------------------- init map */
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: initialCenter,
      zoom: initialZoom,
      zoomControl: false,
      attributionControl: true,
      preferCanvas: true,
      worldCopyJump: false,
    });
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
    map.createPane("outputPane");
    map.getPane("outputPane")!.style.zIndex = "350";
    mapRef.current = map;
    setReady(true);
    return () => {
      map.remove();
      mapRef.current = null;
      groupsRef.current = {};
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---------------------------------------------------- basemap (opt-in) */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (visible.basemap && !groupsRef.current.basemap) {
      groupsRef.current.basemap = L.tileLayer(
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
          maxZoom: 19,
          opacity: 0.75,
          attribution: "© OpenStreetMap contributors",
          crossOrigin: true,
        },
      ).addTo(map);
    } else if (!visible.basemap && groupsRef.current.basemap) {
      map.removeLayer(groupsRef.current.basemap);
      delete groupsRef.current.basemap;
    }
  }, [visible.basemap, ready]);

  /* ------------------------------------------------------- footprint layer */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (groupsRef.current.footprint) {
      map.removeLayer(groupsRef.current.footprint);
      delete groupsRef.current.footprint;
    }
    if (!layers.footprint || !layers.footprint.features?.length) return;

    const layer = L.geoJSON(layers.footprint, {
      style: FOOTPRINT_STYLE,
      pane: "overlayPane",
      onEachFeature: (feature, featureLayer) => {
        const p = feature.properties as Record<string, unknown>;
        featureLayer.bindTooltip(
          `<strong>${p.frame_id ?? ""}</strong><br/>${[
            p.yaw_deg != null ? `yaw ${Number(p.yaw_deg).toFixed(0)}°` : null,
            p.altitude_m != null ? `alt ${Number(p.altitude_m).toFixed(1)} m` : null,
            p.gsd_m != null ? `${(Number(p.gsd_m) * 100).toFixed(2)} cm/px` : null,
          ]
            .filter(Boolean)
            .join(" · ")}`,
          { sticky: true, className: "text-2xs" },
        );
        if (onFeatureClick) {
          featureLayer.on("click", () => onFeatureClick(feature));
        }
      },
    });
    groupsRef.current.footprint = layer;
    if (visible.footprint) layer.addTo(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.footprint, ready]);

  useEffect(() => {
    const layer = groupsRef.current.footprint;
    const map = mapRef.current;
    if (!layer || !map) return;
    if (visible.footprint && !map.hasLayer(layer)) layer.addTo(map);
    if (!visible.footprint && map.hasLayer(layer)) map.removeLayer(layer);
  }, [visible.footprint]);

  /* ------------------------------------------------------ flight path layer */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (groupsRef.current.path) {
      map.removeLayer(groupsRef.current.path);
      delete groupsRef.current.path;
    }
    if (!layers.flightPath || !layers.flightPath.features?.length) return;
    const layer = L.geoJSON(layers.flightPath, {
      style: PATH_STYLE,
      pane: "overlayPane",
    });
    groupsRef.current.path = layer;
    if (visible.flightPath) layer.addTo(map);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers.flightPath, ready]);

  useEffect(() => {
    const layer = groupsRef.current.path;
    const map = mapRef.current;
    if (!layer || !map) return;
    if (visible.flightPath && !map.hasLayer(layer)) layer.addTo(map);
    if (!visible.flightPath && map.hasLayer(layer)) map.removeLayer(layer);
  }, [visible.flightPath]);

  /* --------------------------------------------------------- output layers */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    // remove previous
    (["tiles", "preview"] as const).forEach((key) => {
      const existing = groupsRef.current[key];
      if (existing) {
        map.removeLayer(existing as L.Layer);
        delete groupsRef.current[key];
      }
    });
    if (!visible.output) return;

    if (layers.tileUrlTemplate) {
      const min = layers.tileMinZoom ?? 0;
      const max = layers.tileMaxZoom ?? 22;
      const tileLayer = L.tileLayer(layers.tileUrlTemplate, {
        minZoom: Math.max(0, min - 1),
        maxZoom: Math.max(24, max + 3),
        minNativeZoom: min,
        maxNativeZoom: max,
        tileSize: 256,
        opacity: 1,
        keepBuffer: 2,
        updateWhenIdle: false,
        updateWhenZooming: true,
        pane: "outputPane",
        attribution: "EdgeOrtho mosaic (generated locally)",
      });
      groupsRef.current.tiles = tileLayer.addTo(map);
    } else if (layers.preview && layers.previewBounds) {
      const [s, w, n, e] = layers.previewBounds;
      const overlay = L.imageOverlay(layers.preview, [
        [s, w],
        [n, e],
      ], {
        opacity: 1,
        pane: "outputPane",
        attribution: "EdgeOrtho mosaic preview (generated locally)",
        interactive: false,
      });
      groupsRef.current.preview = overlay.addTo(map);
    }
  }, [layers.tileUrlTemplate, layers.preview, layers.previewBounds, layers.tileMinZoom, layers.tileMaxZoom, visible.output, ready]);

  /* ------------------------------------------------------------- fit extent */
  const fitExtent = useMemo(() => {
    return () => {
      const map = mapRef.current;
      if (!map) return;
      if (layers.outputBounds) {
        const [s, w, n, e] = layers.outputBounds;
        map.fitBounds([[s, w], [n, e]], { animate: false, padding: [18, 18] });
        return;
      }
      const group = L.featureGroup(
        [
          groupsRef.current.footprint,
          groupsRef.current.path,
          groupsRef.current.preview,
        ].filter(Boolean) as L.Layer[],
      );
      if (!group.getLayers().length) return;
      try {
        map.fitBounds(group.getBounds().pad(0.08), { animate: false });
      } catch {
        /* degenerate bounds */
      }
    };
  }, [layers.outputBounds]);

  useEffect(() => {
    if (!ready) return;
    const id = window.setTimeout(fitExtent, 120);
    return () => window.clearTimeout(id);
  }, [ready, fitExtent, layers.footprint, layers.preview, layers.tileUrlTemplate, layers.previewBounds, layers.outputBounds]);

  const hasOutput = Boolean(layers.tileUrlTemplate || (layers.preview && layers.previewBounds));

  return (
    <div className={cx("relative h-full w-full overflow-hidden", className)}>
      <div ref={containerRef} className="h-full w-full" role="application" aria-label="Mosaic map" />

      <div className="pointer-events-none absolute inset-0">
        <div className="pointer-events-auto absolute left-3 top-3 w-52 rounded-card border border-stone-300 bg-stone-50/95 shadow-raised backdrop-blur-[1px]">
          <div className="flex items-center gap-1.5 border-b border-stone-200 px-2.5 py-1.5">
            <Layers size={12} className="text-stone-500" />
            <span className="text-2xs font-semibold uppercase tracking-[0.07em] text-stone-600">Layers</span>
          </div>
          <div className="p-1.5">
            <LayerRow
              label="Mosaic output"
              detail={
                layers.tileUrlTemplate
                  ? `XYZ tiles z${layers.tileMinZoom}–z${layers.tileMaxZoom}`
                  : layers.preview
                    ? "single preview raster"
                    : "not produced"
              }
              active={visible.output}
              disabled={!hasOutput}
              onToggle={() => setVisible((v) => ({ ...v, output: !v.output }))}
            />
            <LayerRow
              label="Image footprints"
              detail={`${layers.footprint?.features?.length ?? 0} polygons`}
              active={visible.footprint}
              disabled={!layers.footprint?.features?.length}
              onToggle={() => setVisible((v) => ({ ...v, footprint: !v.footprint }))}
            />
            <LayerRow
              label="Flight path"
              detail={`${layers.flightPath?.features?.[0]?.geometry ? "GPS track" : "unavailable"}`}
              active={visible.flightPath}
              disabled={!layers.flightPath?.features?.length}
              onToggle={() => setVisible((v) => ({ ...v, flightPath: !v.flightPath }))}
            />
            {showBasemapToggle ? (
              <LayerRow
                label="OpenStreetMap"
                detail="online · leaks this location"
                active={visible.basemap}
                onToggle={() => setVisible((v) => ({ ...v, basemap: !v.basemap }))}
                warn
              />
            ) : null}
          </div>
        </div>

        <div className="pointer-events-auto absolute right-3 top-3 flex flex-col gap-1.5">
          <MapButton label="Fit to extent" onClick={fitExtent}>
            <Crosshair size={13} />
          </MapButton>
          <MapButton label="Zoom in" onClick={() => mapRef.current?.zoomIn()}>
            <Plus size={13} />
          </MapButton>
          <MapButton label="Zoom out" onClick={() => mapRef.current?.zoomOut()}>
            <Minus size={13} />
          </MapButton>
        </div>
      </div>
    </div>
  );
}

function LayerRow({
  label,
  detail,
  active,
  disabled,
  onToggle,
  warn,
}: {
  label: string;
  detail: string;
  active: boolean;
  disabled?: boolean;
  onToggle: () => void;
  warn?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      aria-pressed={active}
      className={cx(
        "flex w-full items-start gap-2 rounded-[3px] px-1.5 py-1.5 text-left transition-colors",
        disabled ? "cursor-not-allowed opacity-45" : "hover:bg-stone-200/70",
      )}
    >
      <span className="mt-0.5 shrink-0 text-stone-500" aria-hidden>
        {active ? <Eye size={12} /> : <EyeOff size={12} />}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-2xs font-medium text-stone-800">{label}</span>
        <span className={cx("block truncate text-2xs", warn && active ? "text-signal-amber" : "text-stone-500")}>
          {detail}
        </span>
      </span>
    </button>
  );
}

function MapButton({
  children,
  label,
  onClick,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <Tooltip text={label}>
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        className="flex h-7 w-7 items-center justify-center rounded-[3px] border border-stone-300
          bg-stone-50 text-stone-700 shadow-panel hover:bg-stone-200"
      >
        {children}
      </button>
    </Tooltip>
  );
}

export { Hint };
