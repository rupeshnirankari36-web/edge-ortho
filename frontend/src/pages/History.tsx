import { useMemo, useState } from "react";
import {
  AlertTriangle,
  FolderOpen,
  History as HistoryIcon,
  Map as MapIcon,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { api, type RunListItem } from "../lib/api";
import { DASH, fmtBytes, fmtDuration, fmtNumber, fmtTimestamp, isMeasured } from "../lib/format";
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
  StatusChip,
} from "../components/ui";
import type { PageProps } from "./shared";
import { runThumbnail } from "./shared";

const STATUS_FILTERS = ["all", "succeeded", "failed", "running"] as const;

export default function History({ runs, refreshRuns, onNavigate, selectRun, activeRunId }: PageProps) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]>("all");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return runs.filter((r) => {
      if (status !== "all" && r.status !== status) return false;
      if (!needle) return true;
      return (
        r.name.toLowerCase().includes(needle) ||
        r.run_id.toLowerCase().includes(needle) ||
        (r.source ?? "").toLowerCase().includes(needle)
      );
    });
  }, [runs, query, status]);

  const deleteRun = async (runId: string, deleteFiles: boolean) => {
    setBusy(runId);
    setError(null);
    try {
      await api.deleteRun(runId, deleteFiles);
      if (activeRunId === runId) selectRun(null);
      await refreshRuns();
      setConfirming(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4 p-5">
      <Panel>
        <PanelHeader
          title="Run history"
          subtitle="Every run is stored locally in SQLite, with its report and outputs kept on disk"
          icon={<HistoryIcon size={14} />}
          actions={
            <Button variant="primary" onClick={() => onNavigate("new")}>
              New project
            </Button>
          }
        />

        {runs.length ? (
          <div className="flex flex-wrap items-center gap-2 border-b border-stone-200 px-4 py-2.5">
            <div className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-stone-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter by name, id or source path"
                aria-label="Filter runs"
                className="field w-72 pl-7"
              />
            </div>
            <div className="flex items-center gap-1">
              {STATUS_FILTERS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setStatus(s)}
                  aria-pressed={status === s}
                  className={cx(
                    "rounded-[3px] border px-2 py-1 text-2xs font-medium",
                    status === s
                      ? "border-forest-600 bg-forest-600 text-stone-50"
                      : "border-stone-300 bg-stone-50 text-stone-700 hover:bg-stone-200/70",
                  )}
                >
                  {s === "all" ? "All" : s}
                </button>
              ))}
            </div>
            <span className="ml-auto text-2xs text-stone-500">
              {filtered.length} of {runs.length} runs
            </span>
          </div>
        ) : null}

        {error ? (
          <div className="border-b border-stone-200 p-3">
            <Callout tone="danger" icon={<AlertTriangle size={13} />} title="Delete failed">
              {error}
            </Callout>
          </div>
        ) : null}

        {!runs.length ? (
          <EmptyState
            icon={<FolderOpen size={18} />}
            title="No runs stored yet"
            action={
              <Button variant="primary" onClick={() => onNavigate("new")}>
                Validate a dataset
              </Button>
            }
          >
            Runs appear here after processing: status, timings, frame verdicts, the size of the
            products and their location on disk. Records can be deleted without touching the outputs,
            or together with them.
          </EmptyState>
        ) : (
          <DataTable
            compact
            rows={filtered}
            getRowKey={(r) => r.run_id}
            empty={
              <p className="px-4 py-6 text-xs text-stone-500">
                No run matches this filter.
              </p>
            }
            columns={[
              {
                key: "preview",
                header: "",
                render: (r) => (
                  <span className="grid-paper flex h-9 w-12 items-center justify-center overflow-hidden rounded-[3px] border border-stone-300">
                    {runThumbnail(r) ? (
                      <img src={runThumbnail(r)!} alt="" className="h-full w-full object-cover" loading="lazy" />
                    ) : (
                      <span className="text-2xs text-stone-400">—</span>
                    )}
                  </span>
                ),
              },
              {
                key: "name",
                header: "Run",
                render: (r) => (
                  <span className="block max-w-[17rem]">
                    <span className="block truncate text-xs font-medium text-stone-800">{r.name}</span>
                    <span className="block truncate text-2xs text-stone-500" title={r.source ?? r.run_id}>
                      {r.source ?? r.run_id}
                    </span>
                  </span>
                ),
              },
              { key: "status", header: "Status", render: (r) => <StatusChip status={r.status} /> },
              {
                key: "when",
                header: "Finished",
                render: (r) => {
                  const t = fmtTimestamp(r.finished_at ?? r.created_at);
                  return <span title={t.absolute}>{t.relative}</span>;
                },
              },
              {
                key: "frames",
                header: "Frames ok / total",
                align: "right",
                render: (r) => `${fmtNumber(r.frames_ok)} / ${fmtNumber(r.frames_total)}`,
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
                key: "output",
                header: "Output",
                align: "right",
                render: (r) =>
                  (r.output as { produced?: boolean })?.produced ? fmtBytes(r.output_bytes) : <Chip>no raster</Chip>,
              },
              {
                key: "profile",
                header: "Profile",
                render: (r) => (
                  <span className="text-2xs text-stone-600">
                    {r.profile ?? DASH}
                    {r.preset ? ` · ${r.preset}` : ""}
                  </span>
                ),
              },
              {
                key: "actions",
                header: "Actions",
                render: (r) => (
                  <span className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      icon={<FolderOpen size={12} />}
                      onClick={() => onNavigate("results", r.run_id)}
                      title="Open results"
                      aria-label={`Open results for ${r.name}`}
                    />
                    <Button
                      variant="ghost"
                      icon={<MapIcon size={12} />}
                      onClick={() => onNavigate("map", r.run_id)}
                      title="Open in map viewer"
                      aria-label={`Open ${r.name} in the map viewer`}
                    />
                    <Button
                      variant="ghost"
                      icon={<Trash2 size={12} />}
                      onClick={() => setConfirming(r.run_id === confirming ? null : r.run_id)}
                      title="Delete this run"
                      aria-label={`Delete ${r.name}`}
                    />
                  </span>
                ),
              },
            ]}
          />
        )}
      </Panel>

      {confirming ? (
        <DeleteConfirm
          run={runs.find((r) => r.run_id === confirming) ?? null}
          busy={busy === confirming}
          onCancel={() => setConfirming(null)}
          onDelete={(files) => void deleteRun(confirming, files)}
        />
      ) : null}
    </div>
  );
}

function DeleteConfirm({
  run,
  busy,
  onCancel,
  onDelete,
}: {
  run: RunListItem | null;
  busy: boolean;
  onCancel: () => void;
  onDelete: (deleteFiles: boolean) => void;
}) {
  const artifactCount = run?.artifacts?.length ?? 0;
  const outputBytes = run?.output_bytes ?? null;
  return (
    <Panel>
      <PanelHeader
        title={`Delete “${run?.name ?? "run"}”`}
        subtitle="Choose whether the generated files are removed as well"
        icon={<AlertTriangle size={14} />}
        actions={
          <Button variant="ghost" icon={<X size={12} />} onClick={onCancel} aria-label="Cancel deletion">
            Cancel
          </Button>
        }
      />
      <div className="grid gap-4 p-4 sm:grid-cols-2">
        <dl>
          <KeyValue label="Run id" value={run?.run_id ?? null} />
          <KeyValue label="Artifacts recorded" value={String(artifactCount)} />
          <KeyValue label="Output size" value={fmtBytes(outputBytes)} />
          <KeyValue label="Status" value={run?.status ?? null} mono={false} />
        </dl>
        <div className="space-y-2 text-xs leading-relaxed text-stone-600">
          <p>
            Deleting the record only removes the row from the local SQLite store. Deleting with files
            also removes <code className="kbd">outputs/{run?.run_id ?? ""}</code> and{" "}
            <code className="kbd">data/meta/{run?.run_id ?? ""}</code>, including the GeoTIFF, tiles
            and reports. Raw source imagery is never touched.
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <Button variant="secondary" disabled={busy} onClick={() => onDelete(false)}>
              {busy ? "Deleting…" : "Delete record only"}
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => onDelete(true)}>
              Delete record and files
            </Button>
          </div>
        </div>
      </div>
    </Panel>
  );
}
