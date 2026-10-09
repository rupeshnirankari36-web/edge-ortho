import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  BarChart3,
  Cpu,
  Download,
  Gauge,
  HardDrive,
  Info,
  MemoryStick,
  Network,
  Table2,
  TriangleAlert,
} from "lucide-react";
import { api, performanceExportUrl, type PerformanceRecord } from "../lib/api";
import {
  DASH,
  fmtBytes,
  fmtDuration,
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
  Stat,
} from "../components/ui";
import type { PageProps } from "./shared";

interface BandwidthScenario {
  mbps: number;
  input_seconds: number | null;
  input_human: string | null;
  output_seconds: number | null;
  output_human: string | null;
  saved_seconds: number | null;
  saved_human: string | null;
  web_seconds: number | null;
  web_human: string | null;
  web_saved_seconds: number | null;
  web_saved_human: string | null;
}

export default function PerformanceLab({ system, onNavigate }: PageProps & { onNavigate: (page: string, param?: string) => void }) {
  const [records, setRecords] = useState<PerformanceRecord[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [rates, setRates] = useState<number[]>([1, 5, 20]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bandwidthRunId, setBandwidthRunId] = useState<string | null>(null);
  const [comparisonRunId, setComparisonRunId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await api.performance();
      setRecords(payload.records);
      setNotes(payload.notes ?? []);
      setRates(payload.bandwidth_rates_mbps ?? [1, 5, 20]);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const completed = useMemo(
    () => records.filter((r) => r.status === "succeeded" || r.status === "failed"),
    [records],
  );

  /* ---------------------------------------------------- bandwidth selection */
  const bandwidthCandidates = useMemo(
    () => records.filter((r) => isMeasured(r.input_bytes) && (r.input_bytes ?? 0) > 0),
    [records],
  );
  const bandwidthRecord = useMemo(() => {
    const chosen = bandwidthRunId
      ? bandwidthCandidates.find((r) => r.run_id === bandwidthRunId)
      : bandwidthCandidates[0];
    return chosen ?? null;
  }, [bandwidthCandidates, bandwidthRunId]);

  /* --------------------------------------------------- comparison selection */
  const comparisonCandidates = useMemo(
    () => records.filter((r) => (r.comparison as { available?: boolean } | null)?.available),
    [records],
  );
  const comparisonRecord = useMemo(() => {
    const chosen = comparisonRunId
      ? comparisonCandidates.find((r) => r.run_id === comparisonRunId)
      : comparisonCandidates[0];
    return chosen ?? null;
  }, [comparisonCandidates, comparisonRunId]);

  /* ----------------------------------------------------------- aggregates */
  const totals = useMemo(() => {
    const measured = completed.filter((r) => isMeasured(r.wall_clock_s));
    if (!measured.length) return null;
    const frames = measured.reduce((acc, r) => acc + (r.frames_accepted ?? 0), 0);
    const seconds = measured.reduce((acc, r) => acc + (r.wall_clock_s ?? 0), 0);
    const disk = measured.reduce((acc, r) => acc + (r.disk_write_bytes ?? 0), 0);
    const output = completed.reduce((acc, r) => acc + (r.output_bytes ?? 0), 0);
    const failures = completed.reduce((acc, r) => acc + (r.frames_failed ?? 0), 0);
    const heaviest = measured.reduce<PerformanceRecord | null>(
      (best, r) => (!best || (r.peak_rss_mb ?? 0) > (best.peak_rss_mb ?? 0) ? r : best),
      null,
    );
    return {
      runs: measured.length,
      frames,
      seconds,
      disk,
      output,
      failures,
      peakRss: heaviest?.peak_rss_mb ?? null,
      throughput: seconds > 0 ? frames / seconds : null,
    };
  }, [completed]);

  const ramPoints = useMemo(
    () =>
      completed
        .filter((r) => isMeasured(r.frames_accepted) && isMeasured(r.peak_rss_mb) && (r.frames_accepted ?? 0) > 0)
        .map((r) => ({
          x: r.frames_accepted as number,
          y: r.peak_rss_mb as number,
          label: r.name,
          profile: r.profile,
          runId: r.run_id,
        }))
        .sort((a, b) => a.x - b.x),
    [completed],
  );

  const scenarios: Record<string, BandwidthScenario> = (bandwidthRecord?.bandwidth?.scenarios ??
    {}) as Record<string, BandwidthScenario>;
  const scenarioRows = rates.map((mbps) => scenarios[String(mbps)] ?? null);

  return (
    <div className="space-y-4 p-5">
      <Panel>
        <PanelHeader
          title="Performance lab"
          subtitle="Measured on this machine, from stored run records — never estimated"
          icon={<BarChart3 size={14} />}
          actions={
            <div className="flex items-center gap-1.5">
              <Button icon={<Download size={13} />} onClick={() => window.open(performanceExportUrl("json"), "_blank")}>
                Experiments (JSON)
              </Button>
              <Button variant="ghost" onClick={() => window.open(performanceExportUrl("csv"), "_blank")}>
                CSV
              </Button>
            </div>
          }
        />
        {loading ? (
          <SkeletonRows rows={3} />
        ) : totals ? (
          <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 lg:grid-cols-6">
            <Stat
              label="Completed runs"
              value={fmtNumber(totals.runs)}
              hint="with a measured wall clock"
              icon={<Activity size={11} />}
            />
            <Stat
              label="Frames processed"
              value={fmtNumber(totals.frames)}
              hint="accepted geotagged frames"
              icon={<Cpu size={11} />}
            />
            <Stat
              label="Runtime"
              value={fmtDuration(totals.seconds)}
              hint="sum of measured wall clock"
              icon={<Gauge size={11} />}
            />
            <Stat
              label="Throughput"
              value={isMeasured(totals.throughput) ? `${totals.throughput!.toFixed(2)} fps` : null}
              hint="accepted frames / second"
            />
            <Stat
              label="Peak RSS"
              value={isMeasured(totals.peakRss) ? `${fmtNumber(totals.peakRss, 0)} MB` : null}
              hint="highest process RSS observed"
              icon={<MemoryStick size={11} />}
            />
            <Stat
              label="Written to disk"
              value={fmtBytes(totals.disk || null)}
              hint={`${fmtBytes(totals.output || null)} of products · ${pluralise(totals.failures, "frame")} failed`}
              icon={<HardDrive size={11} />}
            />
          </div>
        ) : (
          <EmptyState
            icon={<BarChart3 size={18} />}
            title="No measurements yet"
            action={<Button variant="primary" onClick={() => onNavigate("new")}>Run a dataset</Button>}
          >
            This screen charts real work only. Process a dataset and the runtime, memory, throughput
            and bandwidth numbers will be recorded here automatically. Nothing is pre-filled.
          </EmptyState>
        )}
      </Panel>

      {error ? (
        <Callout tone="danger" icon={<TriangleAlert size={14} />} title="The performance API did not answer">
          {error}
        </Callout>
      ) : null}

      {/* ------------------------------------------------------------ profiles */}
      <Panel>
        <PanelHeader
          title="Resource profiles"
          subtitle="Configured for the GEOAI 01 edge profiles — emulated on this host, not measured on that hardware"
          icon={<Cpu size={14} />}
        />
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          {(system?.profiles ?? []).map((profile) => (
            <div key={profile.name} className="rounded-card border border-stone-300 bg-stone-50 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-stone-800">{profile.label}</span>
                {profile.acceptance ? <Chip tone="green">acceptance profile</Chip> : <Chip>reference</Chip>}
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Chip tone={profile.cpu_cores ? "neutral" : "green"}>
                  {profile.cpu_cores ? `${profile.cpu_cores} CPU cores` : "no CPU cap"}
                </Chip>
                <Chip tone={profile.ram_limit_mb ? "neutral" : "green"}>
                  {profile.ram_limit_mb ? `${profile.ram_limit_mb} MB RAM` : "no RAM cap"}
                </Chip>
              </div>
              <p className="mt-2 text-2xs leading-relaxed text-stone-600">{profile.description}</p>
              <p className="mt-1.5 text-2xs leading-relaxed text-signal-amber">
                {profile.cpu_cores
                  ? "Limits applied to this host's process; not a Raspberry Pi or Jetson measurement."
                  : "Runs unconstrained on this host."}
              </p>
            </div>
          ))}
          {!system ? <p className="text-xs text-stone-500">Backend offline — profiles unavailable.</p> : null}
        </div>
        <div className="border-t border-stone-200 px-4 py-3">
          <Callout tone="warn" icon={<Info size={13} />} title="What emulation does and does not prove">
            A constrained profile applies a CPU affinity mask and a soft RSS ceiling to the pipeline
            process on this machine. It demonstrates that the pipeline respects a budget and keeps
            working under it. It is not evidence of throughput on a Raspberry Pi or Jetson, whose
            cores, memory bandwidth and thermals differ. Physical-device runs would be required to
            make that claim.
          </Callout>
        </div>
        {records.some((r) => r.profile_enforcement && Object.keys(r.profile_enforcement).length) ? (
          <div className="border-t border-stone-200 px-4 py-3">
            <h4 className="panel-title mb-2">Enforcement actually applied on this host</h4>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(
                (records.find((r) => r.profile_enforcement && Object.keys(r.profile_enforcement).length)
                  ?.profile_enforcement ?? {}) as Record<string, unknown>,
              ).map(([k, v]) => (
                <Chip key={k} tone={v === false ? "amber" : "neutral"}>
                  {k.replace(/_/g, " ")}: {typeof v === "boolean" ? (v ? "yes" : "no") : String(v)}
                </Chip>
              ))}
            </div>
          </div>
        ) : null}
      </Panel>

      {/* --------------------------------------------------------- RAM chart */}
      <Panel>
        <PanelHeader
          title="Peak RAM against image count"
          subtitle={
            ramPoints.length
              ? `${pluralise(ramPoints.length, "completed run")} plotted from stored measurements`
              : "Plotted only from completed runs that measured both values"
          }
          icon={<MemoryStick size={14} />}
        />
        {ramPoints.length ? (
          <div className="p-4">
            <RamChart points={ramPoints} />
            <p className="mt-2 text-2xs leading-relaxed text-stone-500">
              Each point is one run on this machine: x is the number of accepted frames, y is the peak
              process RSS observed by the sampler. The line joins runs in frame order and is a guide
              to the trend, not a fitted model.
            </p>
          </div>
        ) : (
          <div className="px-4 py-6">
            <p className="text-xs leading-relaxed text-stone-500">
              At least one completed run with both a frame count and a peak RSS reading is needed.
              {completed.length
                ? " The stored runs so far are missing one of those two measurements."
                : " No runs have completed yet."}
            </p>
          </div>
        )}
      </Panel>

      {/* --------------------------------------------------------- bandwidth */}
      <Panel>
        <PanelHeader
          title="Bandwidth comparison"
          subtitle="Transfer time for the raw imagery versus the produced products, at the same link speed"
          icon={<Network size={14} />}
          actions={
            bandwidthCandidates.length ? (
              <Select
                className="max-w-[15rem]"
                value={bandwidthRecord?.run_id ?? ""}
                onChange={setBandwidthRunId}
                options={bandwidthCandidates.map((r) => ({
                  value: r.run_id,
                  label: `${r.name} · ${fmtBytes(r.input_bytes)} in`,
                }))}
              />
            ) : null
          }
        />
        {bandwidthRecord ? (
          <>
            <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
              <Stat label="Raw imagery" value={fmtBytes(bandwidthRecord.input_bytes)} hint="measured input bytes" />
              <Stat
                label="All products"
                value={fmtBytes(bandwidthRecord.output_bytes)}
                hint="GeoTIFF + COG + tiles"
              />
              <Stat
                label="Web delivery"
                value={fmtBytes((bandwidthRecord.bandwidth as { web_bytes?: number | null })?.web_bytes ?? null)}
                hint="COG + XYZ tiles only"
              />
              <Stat
                label="Web reduction"
                value={
                  isMeasured((bandwidthRecord.bandwidth as { web_reduction_factor?: number | null })?.web_reduction_factor)
                    ? `${(bandwidthRecord.bandwidth as { web_reduction_factor?: number }).web_reduction_factor!.toFixed(1)}×`
                    : null
                }
                hint="raw bytes / web bytes"
                tone="good"
              />
            </div>
            <DataTable
              compact
              rows={scenarioRows.filter(Boolean) as BandwidthScenario[]}
              getRowKey={(row) => String(row.mbps)}
              columns={[
                { key: "rate", header: "Link", render: (row) => `${row.mbps} Mbps` },
                {
                  key: "input",
                  header: "Raw imagery upload",
                  align: "right",
                  render: (row) => row.input_human ?? DASH,
                },
                {
                  key: "web",
                  header: "Web products (COG + tiles)",
                  align: "right",
                  render: (row) => row.web_human ?? DASH,
                },
                {
                  key: "web_saved",
                  header: "Difference",
                  align: "right",
                  render: (row) => row.web_saved_human ?? DASH,
                },
                {
                  key: "output",
                  header: "Everything written",
                  align: "right",
                  render: (row) => row.output_human ?? DASH,
                },
              ]}
            />
            <p className="border-t border-stone-200 px-4 py-3 text-2xs leading-relaxed text-stone-500">
              Computed with <code className="kbd">transfer_seconds = bytes × 8 / bits_per_second</code>{" "}
              using the measured byte counts above. These are transfer estimates for the same payloads
              over a given link, not a network measurement of any provider. Everything written includes
              the lossless GeoTIFF, which is larger than the raw imagery — a negative difference is
              reported as such rather than as a saving.
            </p>
          </>
        ) : (
          <div className="px-4 py-6">
            <p className="text-xs leading-relaxed text-stone-500">
              A completed run with a measured input size is required before transfer times can be
              calculated.
            </p>
          </div>
        )}
      </Panel>

      {/* ------------------------------------------------ affine vs homography */}
      <Panel>
        <PanelHeader
          title="Affine versus homography"
          subtitle="Recorded only when a run was executed with the homography comparison enabled"
          icon={<Activity size={14} />}
          actions={
            comparisonCandidates.length ? (
              <Select
                className="max-w-[15rem]"
                value={comparisonRecord?.run_id ?? ""}
                onChange={setComparisonRunId}
                options={comparisonCandidates.map((r) => ({ value: r.run_id, label: r.name }))}
              />
            ) : null
          }
        />
        {comparisonRecord ? (
          <ComparisonTable record={comparisonRecord} />
        ) : (
          <div className="px-4 py-6">
            <p className="text-xs leading-relaxed text-stone-500">
              No stored run used the homography comparison. Set the alignment model to{" "}
              <span className="font-medium text-stone-700">homography</span> or{" "}
              <span className="font-medium text-stone-700">both</span> in settings and process a
              dataset again; the comparison is then recorded as evidence. Composition always uses the
              globally solved similarity model.
            </p>
          </div>
        )}
      </Panel>

      {/* ------------------------------------------------------------ records */}
      <Panel>
        <PanelHeader
          title="Experiment records"
          subtitle={records.length ? `${pluralise(records.length, "stored run")}` : "no runs stored"}
          icon={<Table2 size={14} />}
          actions={
            <Button variant="ghost" onClick={() => void load()} icon={<ArrowDownToLine size={12} />}>
              Refresh
            </Button>
          }
        />
        <DataTable
          compact
          rows={records}
          getRowKey={(r) => r.run_id}
          empty={<p className="px-4 py-6 text-xs text-stone-500">Nothing has been measured yet.</p>}
          columns={[
            {
              key: "name",
              header: "Run",
              render: (r) => (
                <button
                  type="button"
                  className="link max-w-[16rem] truncate text-left"
                  onClick={() => onNavigate("results", r.run_id)}
                >
                  {r.name}
                </button>
              ),
            },
            { key: "when", header: "When", render: (r) => fmtTimestamp(r.created_at).relative },
            {
              key: "profile",
              header: "Profile",
              render: (r) => r.profile ?? DASH,
            },
            {
              key: "frames",
              header: "Frames",
              align: "right",
              render: (r) => fmtNumber(r.frames_accepted),
            },
            {
              key: "runtime",
              header: "Runtime",
              align: "right",
              render: (r) => fmtDuration(r.wall_clock_s),
            },
            {
              key: "rss",
              header: "Peak RSS",
              align: "right",
              render: (r) => (isMeasured(r.peak_rss_mb) ? `${fmtNumber(r.peak_rss_mb, 0)} MB` : DASH),
            },
            {
              key: "fps",
              header: "Throughput",
              align: "right",
              render: (r) => (isMeasured(r.throughput_fps) ? `${r.throughput_fps!.toFixed(2)} fps` : DASH),
            },
            {
              key: "ttft",
              header: "First tile",
              align: "right",
              render: (r) => (isMeasured(r.time_to_first_tile_s) ? fmtDuration(r.time_to_first_tile_s) : DASH),
            },
            {
              key: "output",
              header: "Output",
              align: "right",
              render: (r) => fmtBytes(r.output_bytes),
            },
            {
              key: "disk",
              header: "Disk write",
              align: "right",
              render: (r) => fmtBytes(r.disk_write_bytes),
            },
            {
              key: "inliers",
              header: "Mean inlier ratio",
              align: "right",
              render: (r) => fmtPercent(r.mean_inlier_ratio, 0),
            },
            {
              key: "model",
              header: "Model",
              render: (r) => r.alignment_model ?? DASH,
            },
            {
              key: "status",
              header: "Status",
              render: (r) => (
                <span className={cx(r.status === "succeeded" ? "text-forest-700" : "text-signal-red")}>
                  {r.status}
                </span>
              ),
            },
          ]}
        />
      </Panel>

      {records.some((r) => r.measurements_unavailable?.length) ? (
        <Panel>
          <PanelHeader title="Measurements some runs could not take" icon={<Info size={14} />} />
          <ul className="space-y-1.5 px-4 py-3">
            {Array.from(new Set(records.flatMap((r) => r.measurements_unavailable ?? []))).map((m) => (
              <li key={m} className="text-2xs leading-relaxed text-stone-600">
                {m}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {notes.length ? (
        <Panel>
          <PanelHeader title="How to read these numbers" icon={<Info size={14} />} />
          <ul className="space-y-1.5 px-4 py-3">
            {notes.map((n) => (
              <li key={n} className="text-2xs leading-relaxed text-stone-600">
                {n}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ chart */

interface RamPoint {
  x: number;
  y: number;
  label: string;
  profile: string | null;
  runId: string;
}

function RamChart({ points }: { points: RamPoint[] }) {
  const width = 720;
  const height = 260;
  const pad = { left: 52, right: 16, top: 14, bottom: 34 };
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMax = Math.max(...xs) * 1.12;
  const yMax = Math.max(...ys) * 1.15;
  const px = (x: number) => pad.left + (x / xMax) * (width - pad.left - pad.right);
  const py = (y: number) => height - pad.bottom - (y / yMax) * (height - pad.top - pad.bottom);

  const yTicks = 4;
  const xTicks = Math.min(6, points.length);

  return (
    <div className="scroll-thin overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-[260px] min-w-[560px] w-full"
        role="img"
        aria-label="Peak process RAM against accepted frame count for each completed run"
      >
        {Array.from({ length: yTicks + 1 }).map((_, i) => {
          const value = (yMax / yTicks) * i;
          return (
            <g key={`y${i}`}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={py(value)}
                y2={py(value)}
                stroke="#EAE6DC"
                strokeWidth={1}
              />
              <text x={pad.left - 8} y={py(value) + 3} textAnchor="end" fontSize={9} fill="#948C7C">
                {Math.round(value)} MB
              </text>
            </g>
          );
        })}
        {Array.from({ length: xTicks }).map((_, i) => {
          const value = Math.round((xMax / (xTicks || 1)) * i);
          return (
            <text key={`x${i}`} x={px(value)} y={height - pad.bottom + 14} textAnchor="middle" fontSize={9} fill="#948C7C">
              {value}
            </text>
          );
        })}
        <text x={(width + pad.left) / 2} y={height - 2} textAnchor="middle" fontSize={9} fill="#6F6759">
          accepted frames per run
        </text>

        <polyline
          points={points.map((p) => `${px(p.x)},${py(p.y)}`).join(" ")}
          fill="none"
          stroke="#2F5B4A"
          strokeWidth={1.4}
          strokeOpacity={0.5}
        />
        {points.map((p) => (
          <g key={p.runId}>
            <circle cx={px(p.x)} cy={py(p.y)} r={4} fill="#2F5B4A" fillOpacity={0.85} stroke="#FBFAF7" strokeWidth={1.4}>
              <title>{`${p.label}\n${p.x} frames · ${Math.round(p.y)} MB peak RSS${p.profile ? ` · ${p.profile}` : ""}`}</title>
            </circle>
          </g>
        ))}
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------- comparison */

function ComparisonTable({ record }: { record: PerformanceRecord }) {
  const c = record.comparison as {
    similarity?: { frames?: number; mean_gps_error_m?: number | null; median_gps_error_m?: number | null; max_gps_error_m?: number | null };
    homography_chain?: { frames_reachable?: number; frames_total?: number; mean_gps_error_m?: number | null; median_gps_error_m?: number | null; max_gps_error_m?: number | null };
    mean_placement_disagreement_m?: number | null;
    max_placement_disagreement_m?: number | null;
    homography_pairs_ok?: number;
    homography_pairs_attempted?: number;
    note?: string;
    selection_rationale?: string;
  } | null;

  if (!c) {
    return <p className="px-4 py-6 text-xs text-stone-500">This run recorded no comparison data.</p>;
  }

  return (
    <div className="grid gap-4 p-4 sm:grid-cols-2">
      <dl>
        <KeyValue label="Run" value={record.name} mono={false} />
        <KeyValue label="Alignment model setting" value={record.alignment_model ?? null} mono={false} />
        <KeyValue label="Similarity frames solved" value={fmtNumber(c.similarity?.frames)} />
        <KeyValue
          label="Similarity mean GPS error"
          value={isMeasured(c.similarity?.mean_gps_error_m) ? `${c.similarity!.mean_gps_error_m!.toFixed(2)} m` : null}
        />
        <KeyValue
          label="Similarity max GPS error"
          value={isMeasured(c.similarity?.max_gps_error_m) ? `${c.similarity!.max_gps_error_m!.toFixed(2)} m` : null}
        />
      </dl>
      <dl>
        <KeyValue
          label="Frames reachable by homography chaining"
          value={
            c.homography_chain?.frames_reachable === undefined
              ? null
              : `${c.homography_chain.frames_reachable} / ${c.homography_chain.frames_total ?? "?"}`
          }
        />
        <KeyValue
          label="Homography mean GPS error"
          value={isMeasured(c.homography_chain?.mean_gps_error_m) ? `${c.homography_chain!.mean_gps_error_m!.toFixed(2)} m` : null}
        />
        <KeyValue
          label="Homography pairs validated"
          value={
            c.homography_pairs_attempted === undefined
              ? null
              : `${c.homography_pairs_ok ?? 0} / ${c.homography_pairs_attempted}`
          }
        />
        <KeyValue
          label="Mean placement disagreement"
          value={isMeasured(c.mean_placement_disagreement_m) ? `${c.mean_placement_disagreement_m!.toFixed(2)} m` : null}
        />
        <KeyValue
          label="Max placement disagreement"
          value={isMeasured(c.max_placement_disagreement_m) ? `${c.max_placement_disagreement_m!.toFixed(2)} m` : null}
        />
      </dl>
      {c.selection_rationale ? (
        <p className="text-2xs leading-relaxed text-stone-600 sm:col-span-2">{c.selection_rationale}</p>
      ) : null}
      {c.note ? <p className="text-2xs leading-relaxed text-stone-500 sm:col-span-2">{c.note}</p> : null}
    </div>
  );
}
