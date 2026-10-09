import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDashed,
  Loader2,
  MinusCircle,
} from "lucide-react";
import type { StageRecord } from "../lib/api";
import { STAGE_HELP, STAGE_LABELS, fmtBytes, fmtDuration, isMeasured } from "../lib/format";
import { cx, Hint, ProgressBar } from "./ui";

const ORDER = [
  "ingest",
  "validate_gps",
  "plan_neighbours",
  "match_features",
  "align",
  "compose_tiles",
  "georeference",
  "export",
];

function iconFor(status: StageRecord["status"]) {
  switch (status) {
    case "done":
      return <Check size={13} strokeWidth={2.5} />;
    case "running":
      return <Loader2 size={13} className="animate-spin" />;
    case "failed":
      return <AlertTriangle size={13} />;
    case "skipped":
      return <MinusCircle size={13} />;
    default:
      return <CircleDashed size={13} />;
  }
}

const ring: Record<StageRecord["status"], string> = {
  done: "border-forest-600 bg-forest-600 text-stone-50",
  running: "border-signal-blue bg-signal-blue/15 text-signal-blue",
  failed: "border-signal-red bg-signal-red text-stone-50",
  skipped: "border-signal-amber bg-signal-amber/15 text-signal-amber",
  pending: "border-stone-300 bg-stone-100 text-stone-400",
};

/** Turns raw stage counters into a short, human list of what the stage did. */
export function summariseCounters(name: string, counters: Record<string, unknown> | undefined): string[] {
  if (!counters) return [];
  const c = counters as Record<string, number | string | null>;
  const out: string[] = [];
  const num = (v: unknown) => (isMeasured(v as number) ? (v as number) : null);

  switch (name) {
    case "ingest": {
      const files = num(c.files_discovered);
      if (files !== null) out.push(`${files} file(s) discovered`);
      const unsupported = num(c.unsupported_skipped);
      if (unsupported) out.push(`${unsupported} unsupported skipped`);
      const bytes = num(c.input_bytes);
      if (bytes !== null) out.push(`${fmtBytes(bytes)} on disk`);
      break;
    }
    case "validate_gps": {
      out.push(`${c.accepted ?? "?"} accepted`, `${c.rejected ?? "?"} rejected`);
      if (c.crs) out.push(String(c.crs));
      if (isMeasured(c.gsd_m as number)) out.push(`GSD ${(Number(c.gsd_m) * 100).toFixed(2)} cm/px (${c.gsd_source})`);
      break;
    }
    case "plan_neighbours": {
      out.push(`${c.candidate_pairs ?? "?"} candidate pairs`);
      if (isMeasured(c.reduction_factor as number)) {
        out.push(`${Number(c.reduction_factor).toFixed(2)}× fewer than ${c.all_pairs_possible} all-pairs`);
      }
      if (isMeasured(c.radius_m as number)) out.push(`radius ${Number(c.radius_m).toFixed(1)} m`);
      break;
    }
    case "match_features": {
      out.push(`${c.pairs_ok ?? "?"}/${c.pairs_attempted ?? "?"} pairs aligned`);
      if (isMeasured(c.total_inliers as number)) out.push(`${c.total_inliers} RANSAC inliers`);
      if (isMeasured(c.mean_inlier_ratio as number)) {
        out.push(`${(Number(c.mean_inlier_ratio) * 100).toFixed(0)}% mean inlier ratio`);
      }
      if (isMeasured(c.mean_reprojection_error_px as number)) {
        out.push(`${Number(c.mean_reprojection_error_px).toFixed(2)} px mean RMSE`);
      }
      break;
    }
    case "align": {
      if (isMeasured(c.residual_rmse_m as number)) {
        out.push(`${Number(c.residual_rmse_m).toFixed(2)} m residual`);
      }
      if (isMeasured(c.gps_placement_error_mean_m as number)) {
        out.push(`${Number(c.gps_placement_error_mean_m).toFixed(2)} m GPS consistency`);
      }
      if (isMeasured(c.residual_rmse_px as number)) {
        out.push(`${Number(c.residual_rmse_px).toFixed(1)} px`);
      }
      if (c.heading_convention) out.push(`heading ${String(c.heading_convention)}`);
      break;
    }
    case "compose_tiles": {
      out.push(`${c.tiles_written ?? "?"}/${c.tiles_total ?? "?"} tiles`);
      if (isMeasured(c.time_to_first_tile_s as number)) {
        out.push(`first tile ${fmtDuration(Number(c.time_to_first_tile_s))}`);
      }
      if (isMeasured(c.decodes as number)) out.push(`${c.decodes} decodes`);
      break;
    }
    case "georeference": {
      if (c.kind) out.push(String(c.kind));
      if (isMeasured(c.pixel_size_m as number)) out.push(`${(Number(c.pixel_size_m) * 100).toFixed(2)} cm/px`);
      if (c.cog) out.push("COG written");
      break;
    }
    case "export": {
      if (isMeasured(c.geotiff_bytes as number)) out.push(`GeoTIFF ${fmtBytes(Number(c.geotiff_bytes))}`);
      if (isMeasured(c.cog_bytes as number)) out.push(`COG ${fmtBytes(Number(c.cog_bytes))}`);
      if (c.tiles) out.push(`${c.tile_count ?? 0} XYZ tiles`);
      break;
    }
    default:
      break;
  }
  return out;
}

export function StageList({
  stages,
  activeStage,
  compact,
}: {
  stages: StageRecord[];
  activeStage?: string | null;
  compact?: boolean;
}) {
  const byName = new Map(stages.map((s) => [s.name, s]));
  const ordered = ORDER.map(
    (name) =>
      byName.get(name) ?? {
        name,
        index: ORDER.indexOf(name),
        status: "pending" as const,
        started_at: null,
        finished_at: null,
        elapsed_s: null,
        detail: STAGE_LABELS[name],
        error: null,
        unsupported_reason: null,
        counters: {},
        rss_mb_at_end: null,
      },
  );
  const done = ordered.filter((s) => s.status === "done").length;
  const terminal = ordered.filter((s) => s.status !== "pending" && s.status !== "running").length;

  return (
    <div>
      <div className="flex items-center gap-3 px-4 pt-3">
        <ProgressBar value={done} max={ORDER.length} />
        <span className="shrink-0 text-2xs tabular-nums text-stone-500">
          {done}/{ORDER.length} stages
        </span>
      </div>
      <ol className="p-2">
        {ordered.map((stage, i) => {
          const facts = summariseCounters(stage.name, stage.counters);
          const isActive = activeStage === stage.name || stage.status === "running";
          return (
            <li key={stage.name} className="relative">
              {i < ordered.length - 1 ? (
                <span
                  aria-hidden
                  className={cx(
                    "absolute left-[1.05rem] top-8 h-[calc(100%-1.25rem)] w-px",
                    stage.status === "done" ? "bg-forest-300" : "bg-stone-200",
                  )}
                />
              ) : null}
              <div className={cx("relative flex gap-3 rounded-[4px] px-2 py-2", isActive && "bg-signal-blue/[0.05]")}>
                <span
                  className={cx(
                    "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                    ring[stage.status],
                  )}
                  aria-hidden
                >
                  {iconFor(stage.status)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <span
                      className={cx(
                        "text-xs font-semibold",
                        stage.status === "pending" ? "text-stone-400" : "text-stone-800",
                      )}
                    >
                      {STAGE_LABELS[stage.name] ?? stage.name}
                    </span>
                    {isMeasured(stage.elapsed_s) ? (
                      <span className="text-2xs tabular-nums text-stone-500">{fmtDuration(stage.elapsed_s)}</span>
                    ) : null}
                    <Hint text={STAGE_HELP[stage.name] ?? ""} />
                    {stage.status === "skipped" ? (
                      <span className="text-2xs font-medium text-signal-amber">unsupported</span>
                    ) : null}
                    {stage.status === "failed" ? (
                      <span className="text-2xs font-medium text-signal-red">failed</span>
                    ) : null}
                  </div>
                  {!compact && stage.detail ? (
                    <p className="mt-0.5 text-2xs leading-relaxed text-stone-500">{stage.detail}</p>
                  ) : null}
                  {stage.unsupported_reason ? (
                    <p className="mt-1 text-2xs leading-relaxed text-signal-amber">
                      {stage.unsupported_reason}
                    </p>
                  ) : null}
                  {stage.error ? (
                    <p className="mt-1 text-2xs leading-relaxed text-signal-red">{stage.error}</p>
                  ) : null}
                  {facts.length ? (
                    <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                      {facts.map((f) => (
                        <li key={f} className="flex items-center gap-1 text-2xs tabular-nums text-stone-600">
                          <ChevronRight size={9} className="text-stone-400" />
                          {f}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      {terminal === 0 ? (
        <p className="px-4 pb-3 text-2xs text-stone-500">Waiting to start.</p>
      ) : null}
    </div>
  );
}
