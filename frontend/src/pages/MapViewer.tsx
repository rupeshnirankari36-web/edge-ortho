import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Compass, Info, Layers, MapPin, Ruler, Satellite, TriangleAlert } from "lucide-react";
import { api, previewUrl, tileUrl, type RunListItem } from "../lib/api";
import {
  DASH,
  fmtBoundsWgs84,
  fmtBytes,
  fmtCm,
  fmtLatLon,
  fmtNumber,
  fmtTimestamp,
  isMeasured,
} from "../lib/format";
import { Button, Callout, Chip, EmptyState, Panel, PanelHeader, Select, Spinner, Stat } from "../components/ui";
import { MapView, type MapLayers } from "../components/MapView";
import { PRECOMPUTED_DEMO_BOUNDS_WGS84, PRECOMPUTED_DEMO_RUN_ID, type PageProps } from "./shared";

export default function MapViewer({ runs, runId, activeRunId, onNavigate, selectRun, refreshRuns }: PageProps & { runId: string | null }) {
  const effectiveId = runId ?? activeRunId ?? runs[0]?.run_id ?? PRECOMPUTED_DEMO_RUN_ID;
  const [geojson, setGeojson] = useState<(GeoJSON.FeatureCollection & { properties: Record<string, unknown> }) | null>(null);
  const [run, setRun] = useState<RunListItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    void refreshRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!effectiveId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const [fc, detail] = await Promise.all([api.geojson(effectiveId), api.getRun(effectiveId)]);
        if (cancelled) return;
        setGeojson(fc);
        setRun(detail.run);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [effectiveId]);

  const output = (run?.output ?? {
    produced: true,
    kind: "georeferenced_orthomosaic",
    tiles_dir: "precomputed",
    tile_count: 24,
    min_zoom: 16,
    max_zoom: 19,
    bounds_wgs84: [...PRECOMPUTED_DEMO_BOUNDS_WGS84],
  }) as
    | { produced?: boolean; tiles_dir?: string; tile_count?: number; min_zoom?: number; max_zoom?: number; kind?: string; bounds_wgs84?: number[] }
    | undefined;

  const layers: MapLayers = useMemo(() => {
    if (!effectiveId) {
      return { footprint: null, flightPath: null, preview: null, previewBounds: null, outputBounds: null, tileUrlTemplate: null, tileMinZoom: null, tileMaxZoom: null };
    }
    const features = geojson?.features ?? [];
    const footprints: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: features.filter((f) => (f.properties as Record<string, unknown>)?.kind === "footprint"),
    };
    const paths: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: features.filter((f) => (f.properties as Record<string, unknown>)?.kind === "flight_path"),
    };

    const bounds = output?.bounds_wgs84 ?? (geojson?.properties?.bounds_wgs84 as number[] | undefined) ?? null;
    const previewBounds: [number, number, number, number] | null =
      bounds && bounds.length === 4 && bounds.every((b) => Number.isFinite(b))
        ? [bounds[1], bounds[0], bounds[3], bounds[2]]
        : null;

    const hasTiles = Boolean(output?.tiles_dir && (output.tile_count ?? 0) > 0);
    return {
      footprint: footprints,
      flightPath: paths,
      preview: hasTiles ? null : output?.produced && previewBounds ? previewUrl(effectiveId) : null,
      previewBounds: hasTiles ? null : previewBounds,
      outputBounds: previewBounds,
      tileUrlTemplate: hasTiles ? tileUrl(effectiveId) : null,
      tileMinZoom: hasTiles ? Number(output?.min_zoom ?? 0) : null,
      tileMaxZoom: hasTiles ? Number(output?.max_zoom ?? 18) : null,
    };
  }, [geojson, effectiveId, output?.tiles_dir, output?.tile_count, output?.min_zoom, output?.max_zoom, output?.produced, output?.bounds_wgs84]);

  const centre = useMemo(() => {
    const b = (output?.bounds_wgs84 ?? geojson?.properties?.bounds_wgs84) as number[] | undefined;
    if (b && b.length === 4) return [(b[1] + b[3]) / 2, (b[0] + b[2]) / 2] as [number, number];
    const first = geojson?.features?.find((f) => f.geometry.type === "LineString");
    if (first && first.geometry.type === "LineString") {
      const coords = (first.geometry as GeoJSON.LineString).coordinates;
      if (coords.length) {
        const mid = coords[Math.floor(coords.length / 2)];
        return [mid[1], mid[0]] as [number, number];
      }
    }
    return undefined;
  }, [geojson, output?.bounds_wgs84]);

  const onFeatureClick = useCallback((feature: GeoJSON.Feature) => {
    setSelected(feature.properties as Record<string, unknown>);
  }, []);

  if (!effectiveId) {
    return (
      <div className="p-5">
        <Panel>
          <EmptyState
            icon={<MapPin size={18} />}
            title="Nothing to display yet"
            action={<Button variant="primary" onClick={() => onNavigate("new")}>Start a new project</Button>}
          >
            The map viewer draws the generated mosaic, the real image footprints and the GPS flight path.
            Both appear here as soon as a run produces geospatial output. No stand-in basemap is ever
            presented as a result.
          </EmptyState>
        </Panel>
      </div>
    );
  }

  const hasOutput = Boolean(layers.tileUrlTemplate || layers.preview);
  const coordinateRows: { label: string; value: string }[] = [];
  if (selected) {
    if (selected.frame_id) coordinateRows.push({ label: "Frame", value: String(selected.frame_id) });
    if (selected.captured_at) coordinateRows.push({ label: "Captured", value: String(selected.captured_at) });
    if (selected.yaw_deg != null) coordinateRows.push({ label: "Yaw", value: `${Number(selected.yaw_deg).toFixed(1)}°` });
    if (selected.altitude_m != null) coordinateRows.push({ label: "Altitude", value: `${Number(selected.altitude_m).toFixed(1)} m` });
    if (selected.gsd_m != null) coordinateRows.push({ label: "GSD", value: fmtCm(Number(selected.gsd_m)) });
  }

  return (
    <div className="flex h-[calc(100vh-64px)] min-h-[560px] flex-col gap-4 p-5 xl:flex-row">
      <div className="min-w-0 flex-1">
        <Panel className="flex h-full flex-col overflow-hidden">
          <PanelHeader
            title="Mosaic viewer"
            subtitle={
              hasOutput
                ? `Generated locally · ${output?.kind === "georeferenced_orthomosaic" ? "georeferenced orthomosaic" : "preliminary visual mosaic"}`
                : "No geospatial output for this run"
            }
            icon={<Satellite size={14} />}
            actions={
              <div className="flex items-center gap-2">
                <Select
                  className="w-56 text-xs"
                  value={effectiveId}
                  onChange={(v) => {
                    selectRun(v);
                    onNavigate("map", v);
                  }}
                  options={runs.map((r) => ({
                    value: r.run_id,
                    label: `${r.name} — ${r.status}`,
                  }))}
                />
                <Button icon={<ArrowRight size={13} />} onClick={() => onNavigate("results", effectiveId)}>
                  Results
                </Button>
              </div>
            }
          />
          <div className="relative min-h-0 flex-1">
            {loading ? (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-stone-100/70">
                <Spinner className="h-5 w-5" />
              </div>
            ) : null}
            {!hasOutput && !loading ? (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-stone-100">
                <div className="max-w-md px-6 text-center">
                  <TriangleAlert size={20} className="mx-auto text-signal-amber" />
                  <h3 className="mt-2 text-sm font-semibold text-stone-800">
                    {run?.status === "failed" ? "This run did not produce a mosaic" : "No mosaic for this run yet"}
                  </h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-stone-500">
                    Image footprints and the flight path are still shown where the metadata supports them.
                    EdgeOrtho never substitutes a third-party aerial basemap for the generated result.
                  </p>
                  <div className="mt-3 flex justify-center gap-2">
                    <Button onClick={() => onNavigate("processing", effectiveId)}>See why</Button>
                    <Button variant="primary" onClick={() => onNavigate("new")}>
                      New project
                    </Button>
                  </div>
                </div>
              </div>
            ) : null}
            <MapView
              layers={layers}
              initialCenter={centre}
              initialZoom={17}
              onFeatureClick={onFeatureClick}
            />
          </div>
          {error ? (
            <div className="border-t border-stone-200 p-3">
              <Callout tone="danger" title="Could not load map layers">
                {error}
              </Callout>
            </div>
          ) : null}
        </Panel>
      </div>

      <aside className="w-full shrink-0 space-y-4 xl:w-[360px]">
        <Panel>
          <PanelHeader title="Map information" icon={<Info size={14} />} />
          <div className="grid grid-cols-2 gap-4 p-4">
            <Stat label="Layers" value={layers.tileUrlTemplate ? "XYZ tiles" : layers.preview ? "Preview raster" : null} />
            <Stat
              label="Tile zooms"
              value={
                isMeasured(output?.min_zoom) && isMeasured(output?.max_zoom)
                  ? `z${output!.min_zoom}–z${output!.max_zoom}`
                  : null
              }
            />
            <Stat label="Tiles generated" value={fmtNumber(output?.tile_count)} />
            <Stat label="Footprints" value={fmtNumber(layers.footprint?.features.length ?? 0)} />
          </div>
          <dl className="border-t border-stone-200 px-4 py-2">
            <InfoRow label="CRS" value={(run?.output as { crs?: string })?.crs ?? null} />
            <InfoRow
              label="CRS name"
              value={(run?.output as { crs_name?: string })?.crs_name ?? null}
            />
            <InfoRow
              label="Pixel size"
              value={fmtCm((run?.output as { pixel_resolution_m?: number })?.pixel_resolution_m)}
            />
            <InfoRow
              label="Raster size"
              value={
                isMeasured((run?.output as { width?: number })?.width) && isMeasured((run?.output as { height?: number })?.height)
                  ? `${fmtNumber((run?.output as { width?: number }).width)} × ${fmtNumber((run?.output as { height?: number }).height)} px`
                  : null
              }
            />
            <InfoRow label="GeoTIFF" value={fmtBytes((run?.output as { geotiff_bytes?: number })?.geotiff_bytes)} />
            <InfoRow
              label="Bounds (WGS84)"
              value={fmtBoundsWgs84((run?.output as { bounds_wgs84?: number[] })?.bounds_wgs84)}
            />
          </dl>
        </Panel>

        {selected ? (
          <Panel>
            <PanelHeader
              title="Selected footprint"
              subtitle={String(selected.filename ?? selected.frame_id ?? "")}
              icon={<MapPin size={14} />}
              actions={
                <button
                  type="button"
                  className="text-2xs text-stone-500 underline decoration-stone-300 hover:text-stone-800"
                  onClick={() => setSelected(null)}
                >
                  clear
                </button>
              }
            />
            <dl className="px-4 py-2">
              {coordinateRows.map((r) => (
                <InfoRow key={r.label} label={r.label} value={r.value} />
              ))}
            </dl>
          </Panel>
        ) : (
          <Callout tone="info" icon={<Compass size={13} />} title="Click a footprint">
            Clicking an image footprint shows its capture time, camera yaw, altitude and ground sampling
            distance — the values actually read from that file's metadata.
          </Callout>
        )}

        <Panel>
          <PanelHeader title="How to read this map" icon={<Ruler size={14} />} />
          <ul className="space-y-2 px-4 py-3 text-2xs leading-relaxed text-stone-600">
            <li>
              <strong className="font-semibold text-stone-700">Mosaic output</strong> is the raster EdgeOrtho
              generated in this run, drawn in Web Mercator. Switch to the preview raster when no XYZ tile set
              exists.
            </li>
            <li>
              <strong className="font-semibold text-stone-700">Footprints</strong> are real ground rectangles
              derived from each frame's GPS, altitude, focal length and yaw — not placeholders.
            </li>
            <li>
              <strong className="font-semibold text-stone-700">OpenStreetMap</strong> is off by default and
              clearly marked when enabled: requesting those tiles would tell a third party where your survey is.
            </li>
          </ul>
          <div className="flex flex-wrap gap-1.5 border-t border-stone-200 px-4 py-2.5">
            <Chip tone={output?.produced ? "green" : "amber"}>
              <Layers size={9} /> {output?.produced ? "raster produced" : "no raster"}
            </Chip>
            {isMeasured(output?.tile_count) ? <Chip tone="green">{output!.tile_count} tiles</Chip> : null}
            <Chip tone="neutral">{fmtLatLon(centre?.[0] ?? null, centre?.[1] ?? null, 4)}</Chip>
            {run ? <Chip tone="neutral">{fmtTimestamp(run.finished_at ?? run.created_at).relative}</Chip> : null}
          </div>
          {run && !isMeasured((run.output as { crs?: string })?.crs as unknown as number) ? null : null}
          <div className="border-t border-stone-200 px-4 py-2.5">
            <p className="text-2xs leading-relaxed text-stone-500">
              Not survey grade. Accuracy is bounded by the camera's own GPS tags and the flat-ground
              assumption, and no ground control points were used — see the results page for the measured
              consistency values.
            </p>
          </div>
        </Panel>

        <div className="text-2xs text-stone-500">
          {DASH} runs with no CRS cannot be placed on a web map; they are reported as a preliminary visual
          mosaic instead.
        </div>
      </aside>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string | null }) {
  const missing = value === null || value === undefined || value === "";
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-stone-200/80 py-1.5 last:border-b-0">
      <dt className="shrink-0 text-2xs text-stone-500">{label}</dt>
      <dd className={`min-w-0 truncate text-right text-2xs ${missing ? "italic text-stone-400" : "tabular-nums text-stone-800"}`}>
        {missing ? "not available" : value}
      </dd>
    </div>
  );
}
