import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Columns2,
  Download,
  FileJson,
  FileSpreadsheet,
  Grid3x3,
  Image as ImageIcon,
  Info,
  Layers,
  Map as MapIcon,
  Ruler,
  Scan,
  ShieldQuestion,
  Table2,
  XCircle,
} from "lucide-react";
import {
  api,
  cogUrl,
  framesCsvUrl,
  frameSourceUrl,
  geotiffUrl,
  metadataReportUrl,
  metricsCsvUrl,
  performanceExportUrl,
  previewUrl,
  reportUrl,
  tilesZipUrl,
  type FrameRecord,
  type PairRow,
  type RunReport,
} from "../lib/api";
import {
  DASH,
  fmtBoundsWgs84,
  fmtBytes,
  fmtCm,
  fmtDuration,
  fmtLatLon,
  fmtNumber,
  fmtPercent,
  fmtTimestamp,
  isMeasured,
  pluralise,
} from "../lib/format";
import {
  Button,
  Callout,
  Chip,
  cx,
  DataTable,
  EmptyState,
  KeyValue,
  Panel,
  PanelHeader,
  Select,
  SkeletonRows,
  Spinner,
  Stat,
  StatusChip,
} from "../components/ui";
import { StageList } from "../components/StageList";
import type { PageProps } from "./shared";

export default function Results({
  runs,
  runId,
  activeRunId,
  onNavigate,
  refreshRuns,
}: PageProps & { runId: string | null }) {
  const effectiveId = runId ?? activeRunId ?? runs[runs.length - 1]?.run_id ?? null;
  const [report, setReport] = useState<RunReport | null>(null);
  const [frames, setFrames] = useState<FrameRecord[]>([]);
  const [pairs, setPairs] = useState<PairRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [missingReport, setMissingReport] = useState(false);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setMissingReport(false);
    const [rep, meta, prs] = await Promise.all([
      api.report(id).catch(() => null),
      api.metadataReport(id).catch(() => null),
      api.pairs(id).catch(() => null),
    ]);
    setReport(rep);
    setMissingReport(!rep);
    setFrames(meta?.frames ?? []);
    setPairs(prs?.pairs ?? []);
    setLoading(false);
    void refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    if (!effectiveId) {
      setLoading(false);
      return;
    }
    void load(effectiveId);
  }, [effectiveId, load]);

  const accepted = useMemo(() => frames.filter((f) => f.accepted), [frames]);
  const rejected = useMemo(() => frames.filter((f) => !f.accepted), [frames]);
  const rankedPairs = useMemo(
    () =>
      [...pairs]
        .filter((p) => typeof p.inliers === "number")
        .sort((a, b) => (b.inliers ?? 0) - (a.inliers ?? 0)),
    [pairs],
  );

  if (!effectiveId) {
    return (
      <div className="p-5">
        <Panel>
          <EmptyState
            icon={<Layers size={18} />}
            title="No output to show"
            action={
              <Button variant="primary" onClick={() => onNavigate("new")}>
                Start a mapping project
              </Button>
            }
          >
            Results are read back from a finished run on disk: raster metadata, exports, pair
            statistics and the honest list of what the pipeline could not do.
          </EmptyState>
        </Panel>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-5">
        <Panel>
          <PanelHeader title="Loading run outputs" icon={<Spinner />} />
          <SkeletonRows rows={4} />
        </Panel>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="p-5">
        <Panel>
          <EmptyState
            icon={<XCircle size={18} />}
            title={missingReport ? "This run has no report yet" : "Run not found"}
            action={
              <Button onClick={() => onNavigate("processing", effectiveId)}>Open processing</Button>
            }
          >
            A report is written when the pipeline finishes. If the run is still executing, watch the
            processing workspace.
          </EmptyState>
        </Panel>
      </div>
    );
  }

  const out = report.output;
  const metrics = report.metrics;
  const canvas = report.canvas;
  const georeferenced = Boolean(canvas?.georeferenced && out.produced);
  const validation = (out.validation ?? {}) as Record<string, unknown>;
  const validationRows = Object.entries(validation).filter(
    ([, v]) => typeof v === "boolean" || typeof v === "string" || typeof v === "number",
  );
  const producedExports = report.artifacts?.filter((a) =>
    ["raster", "cog", "tiles", "orthomosaic_preview", "preview_png"].includes(a.kind),
  );

  return (
    <div className="grid gap-4 p-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-4">
        <Panel>
          <PanelHeader
            title={report.name}
            subtitle={`${report.run_id} · ${fmtTimestamp(report.finished_at ?? report.created_at).absolute}`}
            icon={<Scan size={14} />}
            actions={
              <div className="flex items-center gap-2">
                <StatusChip status={report.status} />
                <Button icon={<MapIcon size={13} />} onClick={() => onNavigate("map", effectiveId)}>
                  Open in map
                </Button>
              </div>
            }
          />
          <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
            <Stat
              label="Output size"
              value={out.width && out.height ? `${out.width} × ${out.height} px` : null}
              hint="composed raster, pixels"
            />
            <Stat
              label="Pixel resolution"
              value={isMeasured(out.pixel_resolution_m) ? `${(out.pixel_resolution_m! * 100).toFixed(2)} cm/px` : null}
              hint={canvas?.native_gsd_m ? `native estimate ${fmtCm(canvas.native_gsd_m)}` : "from metadata GSD"}
            />
            <Stat label="CRS" value={out.crs ?? null} hint={out.crs_name ?? "not resolved"} />
            <Stat
              label="Total output"
              value={fmtBytes(metrics.output_bytes)}
              hint={
                isMeasured(metrics.reduction_factor)
                  ? `${metrics.reduction_factor!.toFixed(2)}× smaller than input`
                  : "measured on disk"
              }
              tone={isMeasured(metrics.reduction_factor) ? "good" : "default"}
            />
          </div>
        </Panel>

        {!georeferenced ? (
          <Callout tone="warn" icon={<ShieldQuestion size={14} />} title="This output is not a validated georeferenced product">
            {out.produced
              ? "A raster was written, but the CRS, transform and bounds could not all be established from the available metadata and transforms. Treat it as a preliminary visual mosaic: it is not placed in a coordinate system you should measure against."
              : "The pipeline did not produce a raster for this dataset. Everything below reports the reasons rather than substituting a placeholder image."}
            {canvas?.cap_message ? <p className="mt-1">{canvas.cap_message}</p> : null}
          </Callout>
        ) : null}

        {report.status === "failed" && report.error ? (
          <Callout tone="danger" icon={<AlertTriangle size={14} />} title="The run stopped early">
            <p>{report.error}</p>
            {report.limitations?.length ? (
              <ul className="mt-1.5 list-disc space-y-0.5 pl-4">
                {report.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            ) : null}
          </Callout>
        ) : null}

        <OutputViewer runId={effectiveId} report={report} frames={accepted} />

        <Panel>
          <PanelHeader
            title="Output geospatial metadata"
            subtitle="Read back from the written raster, not from the request that wrote it"
            icon={<Ruler size={14} />}
          />
          <div className="grid gap-x-6 p-4 sm:grid-cols-2 lg:grid-cols-3">
            <dl>
              <KeyValue label="Kind" value={out.kind || DASH} mono={false} />
              <KeyValue label="Width × height" value={out.width && out.height ? `${out.width} × ${out.height}` : null} />
              <KeyValue label="Bands" value={fmtNumber(out.bands)} />
              <KeyValue label="Data type" value={(out as { dtype?: string }).dtype ?? null} />
              <KeyValue label="NoData" value={out.nodata === null ? null : String(out.nodata)} />
              <KeyValue label="Internal alpha/mask" value={out.alpha_mask === undefined ? null : out.alpha_mask ? "yes" : "no"} />
            </dl>
            <dl>
              <KeyValue label="CRS" value={out.crs ?? null} />
              <KeyValue label="CRS name" value={out.crs_name ?? null} mono={false} />
              <KeyValue
                label="Pixel size"
                value={isMeasured(out.gsd_m) ? `${out.gsd_m!.toFixed(4)} m/px` : null}
              />
              <KeyValue
                label="Affine transform"
                value={out.transform ? out.transform.map((v) => Number(v).toFixed(3)).join(", ") : null}
                title={out.transform?.join(", ")}
              />
              <KeyValue
                label="Bounds (CRS)"
                value={out.bounds ? out.bounds.map((v) => Math.round(v)).join(", ") : null}
                title={out.bounds?.join(", ")}
              />
              <KeyValue label="Bounds (WGS84)" value={fmtBoundsWgs84(out.bounds_wgs84 ?? null)} mono={false} />
            </dl>
            <dl>
              <KeyValue label="GeoTIFF driver" value={geotiffDriver(out)} mono={false} />
              <KeyValue label="GeoTIFF size" value={fmtBytes(out.geotiff_bytes)} />
              <KeyValue label="COG size" value={fmtBytes(out.cog_bytes)} />
              <KeyValue label="COG driver" value={out.cog_driver ?? null} mono={false} />
              <KeyValue label="XYZ tiles" value={out.tile_count === null ? null : `${out.tile_count} (z${out.min_zoom}–z${out.max_zoom})`} />
              <KeyValue label="Georeferencing basis" value={out.georeferencing_basis ?? null} mono={false} />
            </dl>
          </div>

          {validationRows.length ? (
            <div className="border-t border-stone-200 px-4 py-3">
              <h4 className="panel-title mb-2">Raster validation on reopen</h4>
              <div className="flex flex-wrap gap-1.5">
                {validationRows.map(([k, v]) => (
                  <Chip
                    key={k}
                    tone={
                      v === false || v === "failed"
                        ? "red"
                        : v === true || v === "ok" || v === "passed"
                          ? "green"
                          : "neutral"
                    }
                  >
                    {k.replace(/_/g, " ")}: {String(v)}
                  </Chip>
                ))}
              </div>
            </div>
          ) : null}

          {out.messages?.length || out.tiles_messages?.length || out.cog_messages?.length ? (
            <div className="border-t border-stone-200 px-4 py-3">
              <h4 className="panel-title mb-1.5">Writer messages</h4>
              <ul className="space-y-1">
                {[...(out.messages ?? []), ...(out.cog_messages ?? []), ...(out.tiles_messages ?? [])].map(
                  (m, i) => (
                    <li key={`${i}-${m}`} className="text-2xs leading-relaxed text-stone-600">
                      {m}
                    </li>
                  ),
                )}
              </ul>
            </div>
          ) : null}
        </Panel>

        <Panel>
          <PanelHeader
            title="What succeeded and what did not"
            subtitle="Stage-by-stage, from the stored run record"
            icon={<Table2 size={14} />}
            actions={
              <Button variant="ghost" onClick={() => onNavigate("processing", effectiveId)}>
                Full diagnostics
              </Button>
            }
          />
          <div className="grid gap-4 p-4 sm:grid-cols-2">
            <dl>
              <KeyValue label="Frames discovered" value={fmtNumber(metrics.frames_total)} />
              <KeyValue label="Accepted geotagged frames" value={fmtNumber(metrics.frames_accepted)} />
              <KeyValue label="Rejected frames" value={fmtNumber(metrics.frames_rejected)} />
              <KeyValue label="Frames failed while reading" value={fmtNumber(metrics.frames_failed)} />
              <KeyValue label="Frames used in composition" value={fmtNumber(metrics.frames_composed)} />
            </dl>
            <dl>
              <KeyValue label="Candidate pairs planned" value={fmtNumber(metrics.pairs_candidates)} />
              <KeyValue label="Pairs aligned" value={fmtNumber(metrics.pairs_matched)} />
              <KeyValue label="Pairs rejected by validation" value={fmtNumber(metrics.pairs_failed)} />
              <KeyValue label="Total RANSAC inliers" value={fmtNumber(metrics.total_inliers)} />
              <KeyValue
                label="Mean reprojection error"
                value={isMeasured(metrics.mean_reprojection_error_px) ? `${metrics.mean_reprojection_error_px!.toFixed(2)} px` : null}
              />
            </dl>
          </div>
          <div className="border-t border-stone-200">
            <StageList stages={report.stages ?? []} />
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title="Strongest image pairs"
            subtitle={
              rankedPairs.length
                ? `${pluralise(rankedPairs.length, "pair")} with a validated transform, sorted by RANSAC inliers`
                : "No pair produced a validated transform for this dataset"
            }
            icon={<Grid3x3 size={14} />}
          />
          <DataTable
            compact
            rows={rankedPairs.slice(0, 40)}
            getRowKey={(p, i) => `${p.source_id}-${p.target_id}-${i}`}
            empty={
              <p className="px-4 py-6 text-xs leading-relaxed text-stone-500">
                Feature matching either did not run or could not validate any pair. Repetitive texture
                (water, sand, uniform canopy) and insufficient overlap are the usual causes; the pair
                table on the processing page lists the specific rejection reasons.
              </p>
            }
            columns={[
              {
                key: "pair",
                header: "Pair",
                render: (p) => (
                  <span className="tabular-nums">
                    {p.source_id} → {p.target_id}
                  </span>
                ),
              },
              {
                key: "distance",
                header: "Baseline",
                align: "right",
                render: (p) => (isMeasured(p.distance_m) ? `${p.distance_m.toFixed(1)} m` : DASH),
              },
              {
                key: "matches",
                header: "Ratio-filtered",
                align: "right",
                render: (p) => fmtNumber(p.ratio_filtered_matches),
              },
              {
                key: "inliers",
                header: "Inliers",
                align: "right",
                render: (p) => fmtNumber(p.inliers),
              },
              {
                key: "ratio",
                header: "Inlier ratio",
                align: "right",
                render: (p) => fmtPercent(p.inlier_ratio, 0),
              },
              {
                key: "rmse",
                header: "Reprojection RMSE",
                align: "right",
                render: (p) =>
                  isMeasured(p.reprojection_error_px) ? `${p.reprojection_error_px!.toFixed(2)} px` : DASH,
              },
              {
                key: "scale",
                header: "Scale",
                align: "right",
                render: (p) => (isMeasured(p.scale) ? `${p.scale!.toFixed(3)}×` : DASH),
              },
              {
                key: "rotation",
                header: "Rotation",
                align: "right",
                render: (p) => (isMeasured(p.rotation_deg) ? `${p.rotation_deg!.toFixed(2)}°` : DASH),
              },
            ]}
          />
        </Panel>

        <Panel>
          <PanelHeader
            title="Frames used and frames rejected"
            subtitle={`${accepted.length} accepted · ${rejected.length} rejected`}
            icon={<ImageIcon size={14} />}
          />
          <DataTable
            compact
            rows={frames.slice(0, 200)}
            getRowKey={(f) => f.frame_id}
            columns={[
              { key: "file", header: "File", render: (f) => <span className="truncate">{f.filename}</span> },
              {
                key: "gps",
                header: "GPS",
                render: (f) => fmtLatLon(f.latitude, f.longitude, 5),
              },
              {
                key: "alt",
                header: "Altitude",
                align: "right",
                render: (f) => (isMeasured(f.altitude_m) ? `${f.altitude_m!.toFixed(1)} m` : DASH),
              },
              {
                key: "yaw",
                header: "Yaw",
                align: "right",
                render: (f) => (isMeasured(f.yaw_deg) ? `${f.yaw_deg!.toFixed(0)}°` : DASH),
              },
              {
                key: "gsd",
                header: "GSD",
                align: "right",
                render: (f) => (isMeasured(f.gsd_m) ? `${(f.gsd_m! * 100).toFixed(2)} cm/px` : DASH),
              },
              {
                key: "px",
                header: "Pixels",
                align: "right",
                render: (f) => (f.width && f.height ? `${f.width}×${f.height}` : DASH),
              },
              {
                key: "status",
                header: "Status",
                render: (f) =>
                  f.accepted ? (
                    <Chip tone="green">accepted</Chip>
                  ) : (
                    <Chip tone="red" title={f.reject_reason_text ?? undefined}>
                      {f.reject_reason_text ?? f.reject_reason ?? "rejected"}
                    </Chip>
                  ),
              },
            ]}
          />
        </Panel>

        <Panel>
          <PanelHeader
            title="Accuracy posture"
            subtitle="What these numbers do and do not support"
            icon={<ShieldQuestion size={14} />}
          />
          <ul className="space-y-2 px-4 py-3 text-xs leading-relaxed text-stone-600">
            <li>
              <span className="font-semibold text-stone-800">No ground control.</span> This dataset
              carries no surveyed ground control points and no independent check points were used, so
              absolute positional accuracy has not been measured. The figure reported below is the
              internal agreement between the visual solution and the GPS-tagged image centres, which
              is evidence of consistency, not of survey accuracy.
            </li>
            <li>
              <span className="font-semibold text-stone-800">Terrain assumption.</span> The composer
              assumes near-nadir, roughly planar RGB imagery. Elevated structure, water and steep
              relief will show parallax seams and local displacement that this first-round
              implementation does not model.
            </li>
            <li>
              <span className="font-semibold text-stone-800">Single strip evidence.</span> Values
              below come from the runs stored on this machine
              {metrics.frames_accepted ? ` (${metrics.frames_accepted} frames in this run)` : ""},
              which is a small sample and not a general accuracy claim.
            </li>
          </ul>
          <div className="grid grid-cols-2 gap-4 border-t border-stone-200 p-4 sm:grid-cols-4">
            <Stat
              label="GPS consistency"
              value={isMeasured(metrics.mean_gps_placement_error_m) ? `${metrics.mean_gps_placement_error_m!.toFixed(2)} m` : null}
              hint="mean offset from tag position"
              unavailableReason="Only measured when frame centres could be placed on the UTM canvas."
            />
            <Stat
              label="Internal residual"
              value={isMeasured(report.alignment?.residual_rmse_m as number) ? `${(report.alignment.residual_rmse_m as number).toFixed(2)} m` : null}
              hint="visual + GPS solve agreement"
            />
            <Stat
              label="Mean inlier ratio"
              value={fmtPercent(metrics.mean_inlier_ratio, 0)}
              hint="RANSAC inliers / matches"
            />
            <Stat
              label="Mean reprojection RMSE"
              value={isMeasured(metrics.mean_reprojection_error_px) ? `${metrics.mean_reprojection_error_px!.toFixed(2)} px` : null}
              hint="per-pair transform fit"
            />
          </div>
        </Panel>
      </div>

      {/* --------------------------------------------------------------- side */}

      <div className="space-y-4">
        <Panel>
          <PanelHeader title="Exports" subtitle="All artifacts stay on this machine" icon={<Download size={14} />} />
          <div className="p-2">
            <ExportRow
              label="GeoTIFF"
              detail={fmtBytes(out.geotiff_bytes)}
              href={out.geotiff_path ? geotiffUrl(effectiveId) : null}
              available={Boolean(out.geotiff_path)}
            />
            <ExportRow
              label="Cloud Optimized GeoTIFF"
              detail={out.cog_path ? fmtBytes(out.cog_bytes) : "converter unavailable or not requested"}
              href={out.cog_path ? cogUrl(effectiveId) : null}
              available={Boolean(out.cog_path)}
            />
            <ExportRow
              label="Web map tiles (zip)"
              detail={out.tile_count === null ? "not generated" : `${out.tile_count} PNG tiles`}
              href={out.tile_count ? tilesZipUrl(effectiveId) : null}
              available={Boolean(out.tile_count)}
            />
            <ExportRow
              label="Mosaic preview (PNG)"
              detail={out.preview_png ? "downscaled from the raster" : "not produced"}
              href={out.preview_png ? previewUrl(effectiveId) : null}
              available={Boolean(out.preview_png)}
            />
          </div>
          <div className="border-t border-stone-200 p-2">
            <ExportRow
              label="Run report (JSON)"
              detail="Every stage, counter and measurement"
              href={reportUrl(effectiveId)}
              available
              icon={<FileJson size={12} />}
            />
            <ExportRow
              label="Metrics (CSV)"
              detail="One row of measured values"
              href={metricsCsvUrl(effectiveId)}
              available
              icon={<FileSpreadsheet size={12} />}
            />
            <ExportRow
              label="Frame table (CSV)"
              detail="Per-frame GPS, altitude, GSD, verdict"
              href={framesCsvUrl(effectiveId)}
              available
              icon={<FileSpreadsheet size={12} />}
            />
            <ExportRow
              label="Metadata report (JSON)"
              detail="Validation report for every discovered file"
              href={metadataReportUrl(effectiveId)}
              available
              icon={<FileJson size={12} />}
            />
            <ExportRow
              label="Experiment records (JSON)"
              detail="All completed runs on this machine"
              href={performanceExportUrl("json")}
              available
              icon={<FileJson size={12} />}
            />
            <ExportRow
              label="Experiment records (CSV)"
              detail="Same records, tabular"
              href={performanceExportUrl("csv")}
              available
              icon={<FileSpreadsheet size={12} />}
            />
          </div>
        </Panel>

        <Panel>
          <PanelHeader title="Run facts" icon={<Info size={14} />} />
          <dl className="px-4 py-2">
            <KeyValue label="Profile" value={metrics.profile} mono={false} />
            <KeyValue label="Preset" value={(report.settings?.preset as string) ?? null} mono={false} />
            <KeyValue label="Alignment model" value={metrics.alignment_model ?? null} mono={false} />
            <KeyValue label="Feature detector" value={metrics.feature_detector ?? null} mono={false} />
            <KeyValue
              label="Matching resolution"
              value={isMeasured(metrics.matching_megapixels) ? `${metrics.matching_megapixels} MP` : null}
            />
            <KeyValue label="Tile size" value={metrics.tile_size ? `${metrics.tile_size} px` : null} />
            <KeyValue label="Wall clock" value={fmtDuration(metrics.wall_clock_s)} />
            <KeyValue
              label="Time to first tile"
              value={isMeasured(metrics.time_to_first_tile_s) ? fmtDuration(metrics.time_to_first_tile_s) : null}
            />
            <KeyValue label="Peak RSS" value={isMeasured(metrics.peak_rss_mb) ? `${fmtNumber(metrics.peak_rss_mb, 0)} MB` : null} />
            <KeyValue label="Input imagery" value={fmtBytes(metrics.input_bytes)} />
          </dl>
        </Panel>

        {producedExports?.length ? (
          <Panel>
            <PanelHeader title="Artifacts on disk" icon={<Layers size={14} />} />
            <ul className="divide-y divide-stone-200">
              {producedExports.map((a) => (
                <li key={`${a.kind}-${a.filename}`} className="px-4 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-xs text-stone-800">{a.label}</span>
                    <span className="shrink-0 text-2xs tabular-nums text-stone-500">{fmtBytes(a.bytes)}</span>
                  </div>
                  <div className="truncate text-2xs text-stone-500" title={a.filename}>
                    {a.filename}
                    {typeof (a as { tile_count?: number }).tile_count === "number"
                      ? ` · ${(a as { tile_count?: number }).tile_count} files`
                      : ""}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        {report.dataset_warnings?.length ? (
          <Callout tone="warn" icon={<AlertTriangle size={13} />} title="Dataset warnings">
            <ul className="mt-1 list-disc space-y-1 pl-4">
              {report.dataset_warnings.map((w) => (
                <li key={w.code}>
                  <span className="font-medium">{w.text}</span>
                  {w.detail ? <span className="text-stone-500"> — {w.detail}</span> : null}
                </li>
              ))}
            </ul>
          </Callout>
        ) : null}

        {report.limitations?.length ? (
          <Panel>
            <PanelHeader title="Known limitations for this run" icon={<AlertTriangle size={14} />} />
            <ul className="space-y-2 px-4 py-3">
              {report.limitations.map((l) => (
                <li key={l} className="text-2xs leading-relaxed text-stone-600">
                  {l}
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}

        {report.messages?.length ? (
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
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ viewer */

type ViewMode = "mosaic" | "source" | "both";

function OutputViewer({
  runId,
  report,
  frames,
}: {
  runId: string;
  report: RunReport;
  frames: FrameRecord[];
}) {
  const [mode, setMode] = useState<ViewMode>("mosaic");
  const [frameId, setFrameId] = useState<string | null>(frames[0]?.frame_id ?? null);
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!frameId && frames.length) setFrameId(frames[0].frame_id);
  }, [frames, frameId]);

  const frame = frames.find((f) => f.frame_id === frameId) ?? frames[0] ?? null;
  const hasMosaic = Boolean(report.output.produced && report.output.preview_png);
  const hasTiles = Boolean(report.output.tile_count);

  return (
    <Panel>
      <PanelHeader
        title="Mosaic and source comparison"
        subtitle={
          report.canvas
            ? `${report.canvas.width} × ${report.canvas.height} px canvas · ${fmtCm(report.canvas.gsd_m)} ground sampling`
            : "output grid unavailable"
        }
        icon={<Scan size={14} />}
        actions={
          <div className="flex items-center gap-1.5">
            <ModeButton active={mode === "mosaic"} onClick={() => setMode("mosaic")} icon={<Layers size={12} />}>
              Mosaic
            </ModeButton>
            <ModeButton
              active={mode === "source"}
              onClick={() => setMode("source")}
              icon={<ImageIcon size={12} />}
              disabled={!frames.length}
            >
              Source frame
            </ModeButton>
            <ModeButton
              active={mode === "both"}
              onClick={() => setMode("both")}
              icon={<Columns2 size={12} />}
              disabled={!frames.length || !hasMosaic}
            >
              Side by side
            </ModeButton>
          </div>
        }
      />

      {mode !== "mosaic" && frames.length > 1 ? (
        <div className="flex items-center gap-2 border-b border-stone-200 px-4 py-2">
          <span className="label mb-0">Source frame</span>
          <Select
            className="max-w-xs"
            value={frame?.frame_id ?? ""}
            onChange={setFrameId}
            options={frames.map((f, i) => ({
              value: f.frame_id,
              label: `${i + 1}. ${f.filename}${f.accepted ? "" : " (rejected)"}`,
            }))}
          />
          {frame ? (
            <span className="text-2xs tabular-nums text-stone-500">
              {fmtLatLon(frame.latitude, frame.longitude, 5)}
              {frame.altitude_m !== null ? ` · ${frame.altitude_m.toFixed(1)} m AGL` : ""}
              {frame.gsd_m !== null ? ` · ${(frame.gsd_m * 100).toFixed(2)} cm/px` : ""}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="grid-paper p-3">
        <div className={cx("grid gap-3", mode === "both" ? "sm:grid-cols-2" : "grid-cols-1")}>
          {mode !== "source" ? (
            <figure className="overflow-hidden rounded-[3px] border border-stone-300 bg-stone-50">
              {hasMosaic && !failed.mosaic ? (
                <img
                  src={previewUrl(runId)}
                  alt="Generated orthomosaic preview"
                  className="max-h-[520px] w-full object-contain"
                  onError={() => setFailed((f) => ({ ...f, mosaic: true }))}
                />
              ) : (
                <div className="flex h-56 flex-col items-center justify-center px-6 text-center">
                  <Layers size={18} className="text-stone-400" />
                  <p className="mt-2 text-xs leading-relaxed text-stone-500">
                    {failed.mosaic
                      ? "The preview file could not be loaded from disk."
                      : hasTiles
                        ? "Tiles exist but no preview raster was written. Open the map viewer to inspect them."
                        : "No mosaic raster was produced for this run."}
                  </p>
                </div>
              )}
              <figcaption className="border-t border-stone-200 bg-stone-50 px-2.5 py-1.5 text-2xs text-stone-500">
                Processed mosaic
                {report.output.width
                  ? ` · ${report.output.width} × ${report.output.height} px · ${report.output.crs ?? "no CRS"}`
                  : ""}
              </figcaption>
            </figure>
          ) : null}

          {mode !== "mosaic" ? (
            <figure className="overflow-hidden rounded-[3px] border border-stone-300 bg-stone-50">
              {frame && !failed[frame.frame_id] ? (
                <img
                  src={frameSourceUrl(runId, frame.frame_id, 1280)}
                  alt={`Original frame ${frame.filename}`}
                  className="max-h-[520px] w-full object-contain"
                  onError={() => setFailed((f) => ({ ...f, [frame.frame_id]: true }))}
                />
              ) : (
                <div className="flex h-56 flex-col items-center justify-center px-6 text-center">
                  <ImageIcon size={18} className="text-stone-400" />
                  <p className="mt-2 text-xs leading-relaxed text-stone-500">
                    {frames.length
                      ? "The original frame could not be read from its path — it may have been moved since the run."
                      : "This run recorded no accepted frames to compare against."}
                  </p>
                </div>
              )}
              <figcaption className="border-t border-stone-200 bg-stone-50 px-2.5 py-1.5 text-2xs text-stone-500">
                Original frame
                {frame?.width && frame?.height ? ` · ${frame.width} × ${frame.height} px` : ""}
                {frame?.make || frame?.model ? ` · ${[frame.make, frame.model].filter(Boolean).join(" ")}` : ""}
              </figcaption>
            </figure>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 border-t border-stone-200 px-4 py-2.5">
        <Chip tone={report.canvas?.georeferenced ? "green" : "amber"}>
          {report.canvas?.georeferenced ? "placed in a CRS transform" : "preliminary visual mosaic only"}
        </Chip>
        <Chip tone={hasTiles ? "green" : "neutral"}>
          {hasTiles ? `${report.output.tile_count} XYZ tiles at z${report.output.min_zoom}–z${report.output.max_zoom}` : "no tiles"}
        </Chip>
        <Chip tone={report.output.cog_path ? "green" : "neutral"}>
          {report.output.cog_path ? `COG ${fmtBytes(report.output.cog_bytes)}` : "no COG"}
        </Chip>
        <span className="ml-auto text-2xs text-stone-500">
          Source frame shown at up to 1280 px; the mosaic preview is downscaled from the full raster.
        </span>
      </div>
    </Panel>
  );
}

function ModeButton({
  active,
  onClick,
  children,
  icon,
  disabled,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  icon?: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className={cx(
        "inline-flex items-center gap-1.5 rounded-[3px] border px-2 py-1 text-2xs font-medium transition-colors",
        disabled
          ? "cursor-not-allowed border-stone-200 text-stone-400"
          : active
            ? "border-forest-600 bg-forest-600 text-stone-50"
            : "border-stone-300 bg-stone-50 text-stone-700 hover:bg-stone-200/70",
      )}
    >
      {icon}
      {children}
    </button>
  );
}

function ExportRow({
  label,
  detail,
  href,
  available,
  icon,
}: {
  label: string;
  detail: string;
  href: string | null;
  available: boolean;
  icon?: React.ReactNode;
}) {
  const content = (
    <>
      <span className="mt-px shrink-0 text-stone-400">{icon ?? <Download size={12} />}</span>
      <span className="min-w-0 flex-1">
        <span className={cx("block truncate text-xs", available ? "text-stone-800" : "text-stone-400")}>
          {label}
        </span>
        <span className="block truncate text-2xs text-stone-500">{detail}</span>
      </span>
    </>
  );
  if (!available || !href) {
    return <div className="flex w-full items-start gap-2 rounded-[3px] px-2 py-1.5 opacity-60">{content}</div>;
  }
  return (
    <a
      href={href}
      download
      className="flex w-full items-start gap-2 rounded-[3px] px-2 py-1.5 hover:bg-stone-200/70"
    >
      {content}
    </a>
  );
}

function geotiffDriver(out: RunReport["output"]): string | null {
  const driver = (out.validation ?? {})["driver"];
  if (typeof driver === "string") return driver;
  return out.geotiff_path ? "GTiff" : null;
}
