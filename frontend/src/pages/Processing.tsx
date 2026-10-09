import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Clock,
  Cpu,
  Gauge,
  HardDrive,
  Info,
  MemoryStick,
  Network,
  Radar,
  Timer,
  Waypoints,
  XCircle,
} from "lucide-react";
import { api, streamRun, type MetricsRecord, type RunReport, type StageRecord } from "../lib/api";
import {
  DASH,
  STAGE_HELP,
  STAGE_LABELS,
  fmtBytes,
  fmtCm,
  fmtDuration,
  fmtNumber,
  fmtPercent,
  isMeasured,
  pluralise,
} from "../lib/format";
import {
  Button,
  Callout,
  Chip,
  cx,
  EmptyState,
  Panel,
  PanelHeader,
  ProgressBar,
  Spinner,
  Stat,
  StatusChip,
} from "../components/ui";
import { StageList } from "../components/StageList";
import type { PageProps } from "./shared";

interface LiveMetrics {
  elapsed_s: number | null;
  rss_mb: number | null;
  peak_rss_mb: number | null;
  baseline_rss_mb: number | null;
}

export default function Processing({
  runs,
  runId,
  onNavigate,
  refreshRuns,
  activeRunId,
}: PageProps & { runId: string | null }) {
  const effectiveId = runId ?? activeRunId ?? runs[0]?.run_id ?? null;
  const [report, setReport] = useState<RunReport | null>(null);
  const [stages, setStages] = useState<StageRecord[]>([]);
  const [live, setLive] = useState<LiveMetrics>({ elapsed_s: null, rss_mb: null, peak_rss_mb: null, baseline_rss_mb: null });
  const [status, setStatus] = useState<string>("queued");
  const [progress, setProgress] = useState<{ stage: string; done: number; total: number; label: string } | null>(null);
  const [firstTile, setFirstTile] = useState<number | null>(null);
  const [events, setEvents] = useState<{ t: string; text: string; tone: string }[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const logRef = useRef<HTMLDivElement | null>(null);

  const loadReport = useCallback(async (id: string) => {
    try {
      const r = await api.report(id);
      setReport(r);
      setStages(r.stages ?? []);
      setStatus(r.status);
      const c = r.stages?.find((s) => s.name === "compose_tiles")?.counters as
        | { time_to_first_tile_s?: number }
        | undefined;
      if (isMeasured(c?.time_to_first_tile_s)) setFirstTile(c!.time_to_first_tile_s!);
      return r;
    } catch {
      return null;
    }
  }, []);

  /* ------------------------------------------------------------ initial load */
  useEffect(() => {
    if (!effectiveId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void (async () => {
      const detail = await api.getRun(effectiveId).catch(() => null);
      if (cancelled) return;
      if (detail?.live) {
        setStatus(detail.live.status);
        const seeded = (detail.live.events ?? []) as Record<string, unknown>[];
        applyEvents(seeded, true);
      }
      const r = await loadReport(effectiveId);
      if (cancelled) return;
      if (!r && detail?.run) {
        setStages(detail.run.stages ?? []);
        setStatus(detail.run.status);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveId]);

  /* -------------------------------------------------------------- live SSE */
  useEffect(() => {
    if (!effectiveId) return;
    if (status === "succeeded" || status === "failed") return;

    const stop = streamRun(
      effectiveId,
      (event) => applyEvents([event], false),
      (message) => setStreamError(message),
    );
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveId, status === "succeeded" || status === "failed"]);

  function applyEvents(batch: Record<string, unknown>[], replace: boolean) {
    if (!batch.length) return;
    if (replace) setEvents([]);
    for (const event of batch) {
      const type = String(event.type ?? "");
      if (type === "started") {
        setStatus("running");
        push("Run accepted — starting the pipeline.", "info");
      } else if (type === "stage") {
        const stage = event.stage as StageRecord;
        setStages((prev) => {
          const next = prev.filter((s) => s.name !== stage.name);
          next.push(stage);
          return next.sort((a, b) => a.index - b.index);
        });
        if (stage.status === "done") push(`${STAGE_LABELS[stage.name] ?? stage.name} finished — ${stage.detail ?? ""}`, "good");
        else if (stage.status === "failed") push(`${STAGE_LABELS[stage.name] ?? stage.name} failed — ${stage.error ?? ""}`, "bad");
        else if (stage.status === "skipped") push(`${STAGE_LABELS[stage.name] ?? stage.name} skipped — ${stage.unsupported_reason ?? ""}`, "warn");
        else push(`${STAGE_LABELS[stage.name] ?? stage.name} started.`, "info");
      } else if (type === "progress") {
        setProgress({
          stage: String(event.stage),
          done: Number(event.done ?? 0),
          total: Number(event.total ?? 0),
          label: String(event.label ?? ""),
        });
        const m = event.metrics as LiveMetrics | undefined;
        if (m) setLive(m);
      } else if (type === "first_tile") {
        setFirstTile(Number(event.seconds));
        push(`First output tile written after ${fmtDuration(Number(event.seconds))}.`, "good");
      } else if (type === "finished") {
        setStatus(String(event.status ?? "succeeded"));
        push(`Run ${event.status === "succeeded" ? "completed" : "ended"}.`, event.status === "succeeded" ? "good" : "bad");
        void loadReport(effectiveId);
        void refreshRuns();
      }
    }

    function push(text: string, tone: string) {
      setEvents((prev) => [...prev.slice(-160), { t: new Date().toLocaleTimeString(), text, tone }]);
    }
  }

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [events.length]);

  /* ----------------------------------------------------------------- render */
  if (!effectiveId) {
    return (
      <div className="p-5">
        <Panel>
          <EmptyState
            icon={<Radar size={18} />}
            title="No run selected"
            action={<Button variant="primary" onClick={() => onNavigate("new")}>Start a new project</Button>}
          >
            The processing workspace streams real stage transitions, measured memory and timing for one run.
            Choose a run from history or start a new mapping project.
          </EmptyState>
        </Panel>
      </div>
    );
  }

  const metrics: MetricsRecord | undefined = report?.metrics;
  const doneCount = stages.filter((s) => s.status === "done").length;
  const isLive = status === "running" || status === "queued";
  const stageCount = 8;

  return (
    <div className="grid gap-4 p-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0 space-y-4">
        {/* ------------------------------------------------------- headline */}
        <Panel>
          <PanelHeader
            title={report?.name ?? "Run"}
            subtitle={effectiveId}
            icon={<Activity size={14} />}
            actions={
              <div className="flex items-center gap-2">
                <StatusChip status={status} />
                {isLive ? <Spinner /> : null}
                {!isLive && report ? (
                  <Button icon={<ArrowRight size={13} />} onClick={() => onNavigate("results", effectiveId)}>
                    Open results
                  </Button>
                ) : null}
              </div>
            }
          />
          <div className="p-4">
            <div className="flex items-center gap-3">
              <ProgressBar value={doneCount} max={stageCount} tone={status === "failed" ? "red" : "forest"} />
              <span className="shrink-0 text-2xs tabular-nums text-stone-500">
                {doneCount}/{stageCount}
              </span>
            </div>
            {progress && isLive ? (
              <p className="mt-2 text-2xs tabular-nums text-stone-600">
                {STAGE_LABELS[progress.stage] ?? progress.stage}: {progress.label} · {progress.done}/{progress.total}
              </p>
            ) : null}

            <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
              <Stat
                label="Elapsed"
                value={fmtDuration(isLive ? live.elapsed_s : metrics?.wall_clock_s)}
                hint={isLive ? "live wall clock" : "total wall clock"}
                icon={<Clock size={11} />}
              />
              <Stat
                label="Process RSS"
                value={
                  isMeasured(live.rss_mb ?? metrics?.peak_rss_mb)
                    ? `${fmtNumber(isLive ? live.rss_mb : metrics?.peak_rss_mb, 0)} MB`
                    : null
                }
                hint={isLive ? `peak ${fmtNumber(live.peak_rss_mb, 0)} MB` : "peak observed"}
                icon={<MemoryStick size={11} />}
              />
              <Stat
                label="Time to first tile"
                value={isMeasured(firstTile) ? fmtDuration(firstTile) : null}
                unavailableReason="Measured only once a tile has actually been written."
                hint="first evidence of a usable map"
                icon={<Timer size={11} />}
                tone="good"
              />
              <Stat
                label="Throughput"
                value={isMeasured(metrics?.throughput_fps) ? `${metrics!.throughput_fps!.toFixed(2)} fps` : null}
                hint="accepted frames / wall clock"
                icon={<Gauge size={11} />}
              />
            </div>
          </div>
        </Panel>

        {/* ------------------------------------------------------ diagnostics */}
        {metrics ? (
          <Panel>
            <PanelHeader
              title="Diagnostics"
              subtitle="Every value below was measured during this run"
              icon={<Activity size={14} />}
            />
            <div className="grid gap-x-6 gap-y-4 p-4 md:grid-cols-2 lg:grid-cols-3">
              <DiagGroup title="Frames">
                <Diag label="Discovered" value={fmtNumber(metrics.frames_total)} />
                <Diag label="Accepted" value={fmtNumber(metrics.frames_accepted)} />
                <Diag label="Rejected" value={fmtNumber(metrics.frames_rejected)} />
                <Diag label="Failed during processing" value={fmtNumber(metrics.frames_failed)} />
                <Diag label="Frames per tile (max)" value={fmtNumber(metrics.frames_composed)} />
              </DiagGroup>

              <DiagGroup title="Matching">
                <Diag label="Candidate pairs" value={fmtNumber(metrics.pairs_candidates)} />
                <Diag label="Pairs aligned" value={fmtNumber(metrics.pairs_matched)} />
                <Diag label="Pairs rejected" value={fmtNumber(metrics.pairs_failed)} />
                <Diag label="Ratio-filtered matches" value={fmtNumber(metrics.total_matches)} />
                <Diag label="RANSAC inliers" value={fmtNumber(metrics.total_inliers)} />
                <Diag label="Mean inlier ratio" value={fmtPercent(metrics.mean_inlier_ratio, 0)} />
                <Diag
                  label="Mean reprojection error"
                  value={isMeasured(metrics.mean_reprojection_error_px) ? `${metrics.mean_reprojection_error_px!.toFixed(2)} px` : null}
                />
              </DiagGroup>

              <DiagGroup title="Alignment">
                <Diag label="Constraints used" value={fmtNumber(asNumber(report?.alignment?.constraints))} />
                <Diag label="Correspondences" value={fmtNumber(asNumber(report?.alignment?.correspondences))} />
                <Diag
                  label="Residual RMSE"
                  value={
                    isMeasured(asNumber(report?.alignment?.residual_rmse_m))
                      ? `${asNumber(report?.alignment?.residual_rmse_m)!.toFixed(2)} m`
                      : null
                  }
                />
                <Diag
                  label="GPS consistency"
                  value={isMeasured(metrics.mean_gps_placement_error_m) ? `${metrics.mean_gps_placement_error_m!.toFixed(2)} m` : null}
                />
                <Diag label="Heading convention" value={String(report?.alignment?.heading_convention ?? DASH)} mono={false} />
                <Diag
                  label="Output grid"
                  value={report?.canvas ? `${report.canvas.width} × ${report.canvas.height} px @ ${fmtCm(report.canvas.gsd_m)}` : null}
                />
              </DiagGroup>

              <DiagGroup title="Resources">
                <Diag label="Baseline RSS" value={isMeasured(metrics.baseline_rss_mb) ? `${fmtNumber(metrics.baseline_rss_mb, 0)} MB` : null} />
                <Diag label="Peak RSS" value={isMeasured(metrics.peak_rss_mb) ? `${fmtNumber(metrics.peak_rss_mb, 0)} MB` : null} />
                <Diag label="Peak RSS above baseline" value={isMeasured(metrics.peak_rss_delta_mb) ? `${fmtNumber(metrics.peak_rss_delta_mb, 0)} MB` : null} />
                <Diag label="CPU (machine)" value={fmtPercent(metrics.peak_cpu_percent, 1)} />
                <Diag label="Cores available" value={fmtNumber(metrics.cpu_cores_effective)} />
                <Diag label="Disk read" value={fmtBytes(metrics.disk_read_bytes)} />
                <Diag label="Disk write" value={fmtBytes(metrics.disk_write_bytes)} />
              </DiagGroup>

              <DiagGroup title="Output">
                <Diag label="GeoTIFF" value={fmtBytes(report?.output.geotiff_bytes)} />
                <Diag label="COG" value={fmtBytes(report?.output.cog_bytes)} />
                <Diag label="XYZ tiles" value={fmtNumber(report?.output.tile_count)} />
                <Diag label="Total output" value={fmtBytes(metrics.output_bytes)} />
                <Diag label="Input imagery" value={fmtBytes(metrics.input_bytes)} />
                <Diag
                  label="Reduction factor"
                  value={isMeasured(metrics.reduction_factor) ? `${metrics.reduction_factor!.toFixed(2)}×` : null}
                />
              </DiagGroup>

              <DiagGroup title="Environment">
                <Diag label="Profile" value={metrics.profile} mono={false} />
                <Diag label="CPU limit" value={metrics.profile_limit_cores ? `${metrics.profile_limit_cores} cores` : "none"} />
                <Diag label="RAM limit" value={metrics.profile_limit_ram_mb ? `${metrics.profile_limit_ram_mb} MB soft` : "none"} />
                <Diag label="Alignment model" value={metrics.alignment_model ?? DASH} mono={false} />
                <Diag label="Detector" value={metrics.feature_detector ?? DASH} mono={false} />
                <Diag label="Matching copies" value={isMeasured(metrics.matching_megapixels) ? `${metrics.matching_megapixels} MP` : null} />
                <Diag label="Tile size" value={metrics.tile_size ? `${metrics.tile_size} px` : null} />
              </DiagGroup>
            </div>

            {metrics.measurements_unavailable?.length ? (
              <div className="border-t border-stone-200 px-4 py-3">
                <Callout tone="warn" icon={<Info size={13} />} title="Measurements this run could not make">
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
                    {metrics.measurements_unavailable.map((m) => (
                      <li key={m}>{m}</li>
                    ))}
                  </ul>
                </Callout>
              </div>
            ) : null}
          </Panel>
        ) : null}

        {/* -------------------------------------------------------- log */}
        <Panel>
          <PanelHeader
            title="Stage log"
            subtitle="Real stage transitions, skips and errors as they happened"
            icon={<Waypoints size={14} />}
            actions={<span className="text-2xs text-stone-500">{pluralise(events.length, "event")}</span>}
          />
          <div ref={logRef} className="scroll-thin max-h-64 overflow-y-auto px-4 py-3">
            {events.length ? (
              <ol className="space-y-1">
                {events.map((e, i) => (
                  <li key={i} className="flex gap-3 text-2xs leading-relaxed">
                    <span className="shrink-0 tabular-nums text-stone-400">{e.t}</span>
                    <span
                      className={cx(
                        e.tone === "bad"
                          ? "text-signal-red"
                          : e.tone === "warn"
                            ? "text-signal-amber"
                            : e.tone === "good"
                              ? "text-forest-700"
                              : "text-stone-600",
                      )}
                    >
                      {e.text}
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-2xs text-stone-500">No events yet.</p>
            )}
          </div>
        </Panel>
      </div>

      {/* -------------------------------------------------------------- right */}
      <div className="space-y-4">
        <Panel>
          <PanelHeader title="Pipeline" subtitle="Ingest → Export" icon={<Radar size={14} />} />
          <StageList stages={stages} activeStage={progress?.stage ?? null} />
        </Panel>

        {report?.error ? (
          <Callout tone="danger" icon={<XCircle size={14} />} title="The run did not complete">
            <p className="mt-0.5">{report.error}</p>
            <ul className="mt-2 list-disc space-y-0.5 pl-4">
              <li>Check that the frames overlap (~70% along-track and ~40% side-lap).</li>
              <li>Repetitive texture (sand, water, uniform canopy) can defeat feature matching.</li>
              <li>Missing altitude or focal length metadata prevents a metric output grid.</li>
            </ul>
            <Button className="mt-2" onClick={() => onNavigate("new")}>
              Try another dataset
            </Button>
          </Callout>
        ) : null}

        {streamError && isLive ? (
          <Callout tone="warn" icon={<Network size={13} />} title="Live stream interrupted">
            {streamError}. The run continues on the backend; use Refresh or reopen this page to resync.
          </Callout>
        ) : null}

        {report ? (
          <>
            <Panel>
              <PanelHeader title="Run configuration" icon={<Cpu size={14} />} />
              <dl className="px-4 py-2">
                {Object.entries(report.settings ?? {})
                  .filter(([k]) =>
                    ["profile", "preset", "alignment_model", "matching_megapixels", "tile_size", "max_output_megapixels", "feature_detector", "min_valid_frames"].includes(k),
                  )
                  .map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3 border-b border-stone-200 py-1.5 last:border-b-0">
                      <dt className="text-xs text-stone-500">{k.replace(/_/g, " ")}</dt>
                      <dd className="truncate text-right text-xs tabular-nums text-stone-800">{String(v)}</dd>
                    </div>
                  ))}
              </dl>
            </Panel>

            <Panel>
              <PanelHeader title="Stage help" icon={<Info size={14} />} />
              <div className="px-4 py-3">
                <StageList stages={[]} compact />
                <dl className="mt-2 space-y-2">
                  {Object.entries(STAGE_HELP).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-2xs font-semibold text-stone-700">{STAGE_LABELS[k]}</dt>
                      <dd className="text-2xs leading-relaxed text-stone-500">{v}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            </Panel>
          </>
        ) : null}

        {loading ? (
          <Panel>
            <PanelHeader title="Loading run" icon={<HardDrive size={14} />} />
            <div className="p-4">
              <Spinner />
            </div>
          </Panel>
        ) : null}

        {report && status === "failed" ? (
          <Callout tone="danger" icon={<AlertTriangle size={13} />} title="Nothing was fabricated">
            When a stage cannot run, EdgeOrtho marks it <em>unsupported</em> and stops rather than
            producing a plausible-looking substitute.
          </Callout>
        ) : null}

        {report?.messages?.length ? (
          <Panel>
            <PanelHeader title="Pipeline notes" icon={<Info size={14} />} />
            <ul className="space-y-1.5 px-4 py-3">
              {report.messages.map((m, i) => (
                <li key={i} className="text-2xs leading-relaxed text-stone-600">
                  {m}
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        <Chip tone="neutral">
          <HardDrive size={9} /> outputs/{effectiveId}
        </Chip>
      </div>
    </div>
  );
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function DiagGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="panel-title mb-1.5">{title}</h4>
      <dl>{children}</dl>
    </div>
  );
}

function Diag({ label, value, mono = true }: { label: string; value: string | null; mono?: boolean }) {
  const missing = value === null || value === undefined || value === "";
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-stone-200/80 py-1 last:border-b-0">
      <dt className="text-2xs text-stone-500">{label}</dt>
      <dd className={cx("truncate text-2xs", mono && "tabular-nums", missing ? "italic text-stone-400" : "text-stone-800")}>
        {missing ? "not measured" : value}
      </dd>
    </div>
  );
}
