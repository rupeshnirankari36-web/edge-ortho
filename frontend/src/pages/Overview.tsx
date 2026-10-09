import { useMemo } from "react";
import {
  ArrowRight,
  Cpu,
  FolderPlus,
  HardDrive,
  ImageIcon,
  Map as MapIcon,
  Mountain,
  Ruler,
  Satellite,
  Timer,
  TriangleAlert,
} from "lucide-react";
import type { RunListItem } from "../lib/api";
import {
  DASH,
  fmtBytes,
  fmtCm,
  fmtDuration,
  fmtNumber,
  fmtTimestamp,
  isMeasured,
  pluralise,
} from "../lib/format";
import { Button, Callout, cx, EmptyState, Panel, PanelHeader, Stat, StatusChip } from "../components/ui";
import type { PageProps } from "./shared";
import { PRECOMPUTED_DEMO_RUN_ID, runThumbnail } from "./shared";

export default function Overview({ runs, system, systemError, refreshRuns, onNavigate, selectRun }: PageProps) {
  const finished = useMemo(
    () => runs.filter((r) => r.status === "succeeded" || r.status === "failed"),
    [runs],
  );
  const lastWithOutput = useMemo(
    () => runs.find((r) => (r.output as { produced?: boolean })?.produced && r.status === "succeeded") ?? null,
    [runs],
  );
  const precomputedDemo = useMemo(
    () => runs.find((r) => r.name.startsWith("Precomputed demo · Brighton Beach · 18 frames") && r.status === "succeeded") ?? null,
    [runs],
  );
  const precomputedId = precomputedDemo?.run_id ?? PRECOMPUTED_DEMO_RUN_ID;

  const aggregate = useMemo(() => {
    const withMetrics = finished.filter((r) => isMeasured(r.wall_clock_s));
    if (!withMetrics.length) return null;
    const totalFrames = withMetrics.reduce((acc, r) => acc + (r.frames_ok ?? 0), 0);
    const totalSeconds = withMetrics.reduce((acc, r) => acc + (r.wall_clock_s ?? 0), 0);
    const heaviest = withMetrics.reduce<RunListItem | null>(
      (best, r) => (!best || (r.peak_rss_mb ?? 0) > (best.peak_rss_mb ?? 0) ? r : best),
      null,
    );
    const outputBytes = finished.reduce((acc, r) => acc + (r.output_bytes ?? 0), 0);
    return {
      runs: withMetrics.length,
      frames: totalFrames,
      seconds: totalSeconds,
      peakRss: heaviest?.peak_rss_mb ?? null,
      outputBytes,
      throughput: totalSeconds > 0 ? totalFrames / totalSeconds : null,
    };
  }, [finished]);

  const recent = runs.slice(0, 6);

  return (
    <div className="space-y-4 p-5">
      {/* ---------------------------------------------------------- hero */}
      <Panel className="overflow-hidden">
        <div className="grid gap-0 md:grid-cols-[1.35fr_1fr]">
          <div className="p-5">
            <div className="flex items-center gap-2">
              <span className="chip border-forest-300 bg-forest-50 text-forest-700">GEOAI 01</span>
              <span className="text-2xs text-stone-500">Edge processing of high-resolution drone imagery</span>
            </div>
            <h2 className="mt-3 text-xl font-semibold leading-tight tracking-tight text-stone-900">
              Turn a folder of geotagged drone images into a georeferenced map — locally.
            </h2>
            <p className="mt-2 max-w-xl text-xs leading-relaxed text-stone-600">
              Raw frames are read from disk, validated, matched with GPS-guided candidates and composed
              tile by tile with bounded memory. Nothing is uploaded, and every run records the RAM, CPU,
              latency and bandwidth that were actually measured.
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                icon={<FolderPlus size={14} />}
                onClick={() => onNavigate("new")}
              >
                New mapping project
              </Button>
              {lastWithOutput ? (
                <Button icon={<MapIcon size={14} />} onClick={() => onNavigate("map", lastWithOutput.run_id)}>
                  Open last mosaic
                </Button>
              ) : null}
              <Button variant="ghost" onClick={() => onNavigate("performance")}>
                Performance lab
              </Button>
            </div>
          </div>

          <div className="grid-paper flex min-h-[190px] items-center justify-center border-t border-stone-200 md:border-l md:border-t-0">
            {lastWithOutput && runThumbnail(lastWithOutput) ? (
              <button
                type="button"
                onClick={() => onNavigate("map", lastWithOutput.run_id)}
                className="group relative h-full w-full"
                aria-label={`Open the last mosaic from ${lastWithOutput.name}`}
              >
                <img
                  src={runThumbnail(lastWithOutput)!}
                  alt={`Preview of the most recent mosaic (${lastWithOutput.name})`}
                  className="h-full w-full object-contain p-3"
                  loading="lazy"
                />
                <span className="absolute bottom-2 left-3 rounded-[3px] border border-stone-300 bg-stone-50/95 px-2 py-1 text-2xs text-stone-600">
                  last orthomosaic ·{" "}
                  {fmtTimestamp(lastWithOutput.finished_at ?? lastWithOutput.created_at).relative}
                  <ArrowRight size={10} className="ml-1 inline" />
                </span>
              </button>
            ) : (
              <div className="px-6 py-8 text-center">
                <Mountain size={20} className="mx-auto text-stone-400" />
                <p className="mt-2 text-xs text-stone-500">
                  No mosaic yet. Generated rasters appear here with real geospatial metadata — never a
                  stand-in basemap.
                </p>
              </div>
            )}
          </div>
        </div>
      </Panel>

      {/* ----------------------------------------------- precomputed showcase */}
      <Panel className="overflow-hidden border-forest-300/70">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-stone-200 px-4 py-3">
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 flex h-7 w-7 items-center justify-center rounded-[4px] bg-forest-100 text-forest-700">
              <Satellite size={15} />
            </span>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-stone-900">Precomputed dataset pair</h3>
                <span className="chip border-forest-300 bg-forest-50 text-forest-700">18 frames loaded</span>
              </div>
              <p className="mt-1 max-w-2xl text-2xs leading-relaxed text-stone-600">
                Explore a completed Brighton Beach flight without waiting for processing. This is the real
                georeferenced mosaic generated from the public 18-image dataset.
              </p>
            </div>
          </div>
          <Button
            variant="primary"
            icon={<MapIcon size={13} />}
            onClick={() => onNavigate("image", precomputedId)}
          >
            Open mapped view
          </Button>
        </div>
        <div className="grid gap-0 md:grid-cols-[minmax(0,1fr)_280px]">
          <button
            type="button"
            onClick={() => onNavigate("image", precomputedId)}
            className="grid-paper group min-h-[180px] border-b border-stone-200 p-3 text-left md:border-b-0 md:border-r"
            aria-label="Open the precomputed Brighton Beach 18-frame map"
          >
            {precomputedDemo && runThumbnail(precomputedDemo) ? (
              <img
                src={runThumbnail(precomputedDemo)!}
                alt="Precomputed Brighton Beach orthomosaic"
                className="h-full max-h-[260px] w-full object-contain transition-transform group-hover:scale-[1.01]"
              />
            ) : (
              <img
                src={`/api/runs/${precomputedId}/preview.png`}
                alt="Precomputed Brighton Beach orthomosaic"
                className="h-full max-h-[260px] w-full object-contain"
              />
            )}
          </button>
          <div className="grid grid-cols-2 gap-x-5 gap-y-3 p-4 sm:grid-cols-4 md:grid-cols-2">
            <Stat label="Frames" value={precomputedDemo?.frames_ok ? `${precomputedDemo.frames_ok} / 18` : "18"} hint="accepted source images" />
            <Stat
              label="Raster"
              value={
                precomputedDemo?.output && (precomputedDemo.output as { width?: number }).width
                  ? `${fmtNumber((precomputedDemo.output as { width: number }).width)} × ${fmtNumber((precomputedDemo.output as { height: number }).height)}`
                  : null
              }
              hint="native-resolution output"
            />
            <Stat label="Map tiles" value={precomputedDemo?.output?.tile_count ? fmtNumber(precomputedDemo.output.tile_count) : null} hint="XYZ tiles for deep zoom" />
            <Stat label="Pixel size" value={precomputedDemo ? fmtCm((precomputedDemo.output as { pixel_resolution_m?: number }).pixel_resolution_m) : null} hint="native GSD" />
          </div>
        </div>
      </Panel>

      {systemError ? (
        <Callout
          tone="danger"
          icon={<TriangleAlert size={14} />}
          title="Backend unreachable"
          action={
            <Button onClick={() => void refreshRuns()} className="shrink-0">
              Retry
            </Button>
          }
        >
          The interface is running, but the local processing API is not answering. Start it with{" "}
          <code className="kbd">python -m edge_ortho.cli serve</code>.
        </Callout>
      ) : null}

      {/* ------------------------------------------------- measured summary */}
      {aggregate ? (
        <Panel>
          <PanelHeader
            title="Measured across completed runs"
            subtitle="Real values from the stored run records on this machine — no estimates"
            icon={<Ruler size={14} />}
          />
          <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Completed runs" value={fmtNumber(aggregate.runs)} hint="with a measured wall clock" />
            <Stat label="Frames processed" value={fmtNumber(aggregate.frames)} hint="accepted geotagged frames" />
            <Stat
              label="Processing time"
              value={fmtDuration(aggregate.seconds)}
              hint="sum of measured wall clock"
            />
            <Stat
              label="Throughput"
              value={isMeasured(aggregate.throughput) ? `${aggregate.throughput!.toFixed(2)} fps` : null}
              hint="frames per second across runs"
            />
            <Stat
              label="Peak RSS"
              value={isMeasured(aggregate.peakRss) ? `${fmtNumber(aggregate.peakRss, 0)} MB` : null}
              hint="highest process RSS observed"
            />
            <Stat label="Products written" value={fmtBytes(aggregate.outputBytes)} hint="all outputs on disk" />
          </div>
        </Panel>
      ) : null}

      {/* --------------------------------------------------------- recent runs */}
      <Panel>
        <PanelHeader
          title="Recent processing runs"
          subtitle={`${runs.length ? pluralise(runs.length, "stored run") : "no runs yet"}`}
          icon={<Timer size={14} />}
          actions={
            <Button variant="ghost" onClick={() => onNavigate("history")}>
              All runs
            </Button>
          }
        />
        {recent.length === 0 ? (
          <EmptyState
            icon={<ImageIcon size={18} />}
            title="No runs yet"
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Button variant="primary" icon={<FolderPlus size={14} />} onClick={() => onNavigate("new")}>
                  Add a drone image folder
                </Button>
                <Button onClick={() => onNavigate("new", "samples")}>Use a sample dataset</Button>
              </div>
            }
          >
            EdgeOrtho has not processed anything on this machine. Point it at a folder of geotagged
            JPG/TIFF frames — or fetch the 18-frame public sample dataset — and it will validate the
            metadata before any processing starts. Runs, measurements and outputs are stored locally.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-stone-200">
            {recent.map((run) => {
              const s = (run.summary ?? {}) as { source_kind?: string };
              return (
                <li key={run.run_id}>
                  <button
                    type="button"
                    onClick={() => {
                      selectRun(run.run_id);
                      onNavigate(run.status === "succeeded" ? "results" : "processing", run.run_id);
                    }}
                    className="flex w-full items-center gap-4 px-4 py-3 text-left transition-colors hover:bg-stone-100/80"
                  >
                    <span className="grid-paper flex h-12 w-16 shrink-0 items-center justify-center overflow-hidden rounded-[3px] border border-stone-300">
                      {runThumbnail(run) ? (
                        <img src={runThumbnail(run)!} alt="" className="h-full w-full object-cover" loading="lazy" />
                      ) : (
                        <ImageIcon size={14} className="text-stone-400" />
                      )}
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-stone-900">{run.name}</span>
                        <StatusChip status={run.status} />
                        {run.profile ? (
                          <span className="chip border-stone-300 bg-stone-100 text-stone-600">
                            <Cpu size={9} />
                            {run.profile}
                          </span>
                        ) : null}
                        {s.source_kind === "sample" ? (
                          <span className="chip border-stone-300 bg-stone-100 text-stone-600">sample</span>
                        ) : null}
                      </span>
                      <span className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-2xs tabular-nums text-stone-500">
                        <span>{fmtTimestamp(run.finished_at ?? run.created_at).absolute}</span>
                        <span>
                          {isMeasured(run.frames_ok) ? `${run.frames_ok}` : DASH} accepted
                          {isMeasured(run.frames_total) ? ` / ${run.frames_total}` : ""} frames
                        </span>
                        <span>wall {fmtDuration(run.wall_clock_s)}</span>
                        <span>peak RSS {isMeasured(run.peak_rss_mb) ? `${fmtNumber(run.peak_rss_mb, 0)} MB` : DASH}</span>
                        <span>output {fmtBytes(run.output_bytes)}</span>
                        {isMeasured(run.metrics?.mean_gps_placement_error_m) ? (
                          <span>GPS consistency {fmtNumber(run.metrics.mean_gps_placement_error_m, 2)} m</span>
                        ) : null}
                      </span>
                      {run.error ? (
                        <span className="mt-1 block truncate text-2xs text-signal-red">{run.error}</span>
                      ) : null}
                    </span>

                    <span className="hidden shrink-0 text-right lg:block">
                      {isMeasured((run.output as { width?: number })?.width) &&
                      isMeasured((run.output as { height?: number })?.height) ? (
                        <>
                          <span className="block text-xs tabular-nums text-stone-700">
                            {fmtNumber((run.output as { width?: number }).width)} ×{" "}
                            {fmtNumber((run.output as { height?: number }).height)}
                          </span>
                          <span className="block text-2xs text-stone-500">
                            {fmtCm((run.output as { pixel_resolution_m?: number }).pixel_resolution_m)}
                          </span>
                        </>
                      ) : (
                        <span className="block text-2xs italic text-stone-400">no raster</span>
                      )}
                    </span>
                    <ArrowRight size={14} className="shrink-0 text-stone-400" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      {/* ------------------------------------------------------------ local note */}
      <div className="grid gap-4 md:grid-cols-3">
        <Panel className="p-4">
          <div className="flex items-center gap-2 text-stone-700">
            <HardDrive size={14} />
            <span className="text-xs font-semibold">Where things are stored</span>
          </div>
          <dl className="mt-2 space-y-1 text-2xs text-stone-600">
            <div className="flex justify-between gap-3">
              <dt>Imagery</dt>
              <dd className="truncate text-right" title={system?.data_dir}>
                {system?.data_dir ?? DASH}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt>Outputs</dt>
              <dd className="truncate text-right" title={system?.output_dir}>
                {system?.output_dir ?? DASH}
              </dd>
            </div>
          </dl>
        </Panel>

        <Panel className="p-4">
          <div className="flex items-center gap-2 text-stone-700">
            <Cpu size={14} />
            <span className="text-xs font-semibold">Geospatial tooling detected</span>
          </div>
          <ul className="mt-2 space-y-1 text-2xs text-stone-600">
            {system
              ? Object.entries(system.capabilities)
                  .slice(0, 4)
                  .map(([key, value]) => (
                    <li key={key} className="flex items-center justify-between gap-3">
                      <span className="font-mono">{key}</span>
                      <span className={cx(Boolean(value) ? "text-forest-700" : "text-signal-amber")}>
                        {typeof value === "string" ? value : value ? "available" : "unavailable"}
                      </span>
                    </li>
                  ))
              : null}
          </ul>
        </Panel>

        <Panel className="p-4">
          <div className="flex items-center gap-2 text-stone-700">
            <TriangleAlert size={14} />
            <span className="text-xs font-semibold">Honesty by construction</span>
          </div>
          <p className="mt-2 text-2xs leading-relaxed text-stone-600">
            Missing measurements render as <em>not measured</em> rather than zero. The mosaic is labelled
            a georeferenced orthomosaic only when a CRS and a metadata-supported pixel size exist, and no
            survey-grade accuracy is ever claimed.
          </p>
        </Panel>
      </div>
    </div>
  );
}
