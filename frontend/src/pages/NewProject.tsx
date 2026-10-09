import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  CloudDownload,
  Cpu,
  FileImage,
  FolderOpen,
  HardDriveUpload,
  Info,
  Layers,
  MapPin,
  Play,
  RotateCcw,
  Satellite,
  XCircle,
} from "lucide-react";
import { api, type InspectionResult, type SystemInfo } from "../lib/api";
import {
  DASH,
  REJECT_REASON_LABELS,
  fmtBytes,
  fmtCm,
  fmtLatLon,
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
  DataTable,
  EmptyState,
  Field,
  Panel,
  PanelHeader,
  Select,
  Spinner,
  Stat,
  Tooltip,
} from "../components/ui";
import { MapView } from "../components/MapView";
import type { PageProps } from "./shared";

type SourceTab = "folder" | "upload" | "sample";

export default function NewProject({ system, refreshRuns, onNavigate, selectRun }: PageProps) {
  const [tab, setTab] = useState<SourceTab>("folder");
  const [folderPath, setFolderPath] = useState("");
  const [inspection, setInspection] = useState<InspectionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ sent: number; total: number } | null>(null);
  const [profile, setProfile] = useState("laptop");
  const [preset, setPreset] = useState("balanced");
  const [alignment, setAlignment] = useState("affine");
  const [runName, setRunName] = useState("");
  const dropRef = useRef<HTMLLabelElement | null>(null);

  const source = inspection?.upload_path ?? inspection?.discovery?.root ?? folderPath;

  /* ------------------------------------------------------------ validation */
  const inspectFolder = useCallback(async (path: string) => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.inspectPath(path);
      setInspection(result);
      setRunName((current) => current || result.suggested_name || "");
    } catch (err) {
      setInspection(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const inspectUpload = useCallback(
    async (files: File[]) => {
      setBusy(true);
      setError(null);
      try {
        const result = await api.uploadFiles(files, (sent, total) => setUploadProgress({ sent, total }));
        setInspection(result);
        setRunName((current) => current || result.suggested_name || "");
      } catch (err) {
        setInspection(null);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
        setUploadProgress(null);
      }
    },
    [],
  );

  const loadSample = useCallback(
    async (key: string, path: string | null) => {
      setBusy(true);
      setError(null);
      try {
        const manifest = await api.fetchSample(key);
        await inspectFolder(manifest.path || path || "");
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [inspectFolder],
  );

  /* --------------------------------------------------------------- drag/drop */
  const onFiles = useCallback(
    (fileList: FileList | null) => {
      if (!fileList?.length) return;
      const files = Array.from(fileList).filter((f) =>
        [".jpg", ".jpeg", ".tif", ".tiff"].some((ext) => f.name.toLowerCase().endsWith(ext)),
      );
      if (!files.length) {
        setError(
          "None of the dropped files are supported. EdgeOrtho accepts geotagged .jpg, .jpeg, .tif and .tiff frames.",
        );
        return;
      }
      void inspectUpload(files);
    },
    [inspectUpload],
  );

  useEffect(() => {
    const el = dropRef.current;
    if (!el) return;
    const prevent = (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
    };
    const onEnter = (e: DragEvent) => {
      prevent(e);
      setDragging(true);
    };
    const onLeave = (e: DragEvent) => {
      prevent(e);
      setDragging(false);
    };
    const onDrop = (e: DragEvent) => {
      prevent(e);
      setDragging(false);
      onFiles(e.dataTransfer?.files ?? null);
    };
    el.addEventListener("dragenter", onEnter);
    el.addEventListener("dragover", onEnter);
    el.addEventListener("dragleave", onLeave);
    el.addEventListener("drop", onDrop);
    return () => {
      el.removeEventListener("dragenter", onEnter);
      el.removeEventListener("dragover", onEnter);
      el.removeEventListener("dragleave", onLeave);
      el.removeEventListener("drop", onDrop);
    };
  }, [onFiles]);

  /* ------------------------------------------------------------------ start */
  const startRun = useCallback(async () => {
    if (!source) return;
    setStarting(true);
    setError(null);
    try {
      const { run_id } = await api.createRun({
        source,
        name: runName || inspection?.suggested_name || "Untitled run",
        settings: { profile, preset, alignment_model: alignment },
      });
      await refreshRuns();
      selectRun(run_id);
      onNavigate("processing", run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  }, [source, runName, inspection, profile, preset, alignment, refreshRuns, selectRun, onNavigate]);

  const summary = inspection?.summary;
  const accepted = inspection?.frames.filter((f) => f.accepted) ?? [];
  const rejected = inspection?.frames.filter((f) => !f.accepted) ?? [];
  const gpsMissing = summary ? !summary.gps_available : false;
  const unsuitable = inspection ? !inspection.suitable : false;

  return (
    <div className="grid gap-4 p-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-4">
        {/* -------------------------------------------------------- source */}
        <Panel>
          <PanelHeader
            title="1 · Choose the imagery"
            subtitle="Frames are read in place on this machine; nothing is uploaded to a service"
            icon={<FileImage size={14} />}
            actions={
              inspection ? (
                <Button
                  variant="ghost"
                  icon={<RotateCcw size={13} />}
                  onClick={() => {
                    setInspection(null);
                    setError(null);
                  }}
                >
                  Clear
                </Button>
              ) : null
            }
          />

          <div className="flex gap-1 border-b border-stone-200 px-3 pt-3" role="tablist">
            {(
              [
                { id: "folder", label: "Local folder", icon: FolderOpen, hint: "Zero transfer" },
                { id: "upload", label: "Upload images", icon: HardDriveUpload, hint: "Drag and drop" },
                { id: "sample", label: "Sample dataset", icon: CloudDownload, hint: "First run" },
              ] as const
            ).map((t) => {
              const Icon = t.icon;
              return (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={tab === t.id}
                  onClick={() => setTab(t.id)}
                  className={cx(
                    "-mb-px flex items-center gap-2 rounded-t-[4px] border border-b-0 px-3 py-2 text-xs transition-colors",
                    tab === t.id
                      ? "border-stone-300 bg-stone-50 font-semibold text-stone-900"
                      : "border-transparent text-stone-500 hover:text-stone-800",
                  )}
                >
                  <Icon size={13} />
                  {t.label}
                  <span className="hidden text-2xs text-stone-400 sm:inline">{t.hint}</span>
                </button>
              );
            })}
          </div>

          <div className="p-4">
            {tab === "folder" ? (
              <div className="space-y-3">
                <Field
                  label="Absolute path to the image folder"
                  hint="The backend reads this folder directly. This is the true local-first path: no bytes are transferred."
                  required
                >
                  <div className="flex gap-2">
                    <input
                      className="field font-mono text-xs"
                      placeholder="D:\surveys\site-01\images"
                      value={folderPath}
                      onChange={(e) => setFolderPath(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && folderPath.trim()) void inspectFolder(folderPath.trim());
                      }}
                    />
                    <Button
                      variant="primary"
                      disabled={!folderPath.trim() || busy}
                      onClick={() => void inspectFolder(folderPath.trim())}
                      icon={busy ? <Spinner /> : undefined}
                    >
                      {busy ? "Checking" : "Check metadata"}
                    </Button>
                  </div>
                </Field>
                <FolderHints system={system} onPick={(p) => setFolderPath(p)} />
              </div>
            ) : null}

            {tab === "upload" ? (
              <label
                ref={dropRef}
                className={cx(
                  "flex cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed px-6 py-10 text-center transition-colors",
                  dragging ? "border-forest-500 bg-forest-50" : "border-stone-300 bg-stone-100/60 hover:border-stone-400",
                )}
              >
                <input
                  type="file"
                  className="sr-only"
                  multiple
                  accept=".jpg,.jpeg,.tif,.tiff,image/jpeg,image/tiff"
                  onChange={(e) => onFiles(e.target.files)}
                />
                {busy ? (
                  <>
                    <Spinner className="h-5 w-5" />
                    <span className="mt-3 text-sm font-medium text-stone-700">
                      {uploadProgress
                        ? `Uploading ${uploadProgress.sent}/${uploadProgress.total} files and reading metadata…`
                        : "Uploading…"}
                    </span>
                  </>
                ) : (
                  <>
                    <HardDriveUpload size={20} className="text-stone-400" />
                    <span className="mt-3 text-sm font-medium text-stone-700">
                      Drop a folder of geotagged JPG/TIFF frames here
                    </span>
                    <span className="mt-1 text-2xs text-stone-500">
                      or click to select files. Multi-select is supported; each file is stored under{" "}
                      <code className="kbd">data/uploads</code>.
                    </span>
                  </>
                )}
              </label>
            ) : null}

            {tab === "sample" ? <SamplePicker onLoad={loadSample} busy={busy} /> : null}
          </div>
        </Panel>

        {error ? (
          <Callout tone="danger" icon={<XCircle size={14} />} title="That input could not be used">
            {error}
          </Callout>
        ) : null}

        {/* ------------------------------------------------------ validation */}
        {inspection && summary ? (
          <>
            <Panel>
              <PanelHeader
                title="2 · Metadata validation report"
                subtitle={`${inspection.discovery.root ?? "uploaded set"} · checked in ${
                  isMeasured(inspection.elapsed_s) ? `${(inspection.elapsed_s as number).toFixed(2)} s` : "—"
                }`}
                icon={unsuitable ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
              />
              <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 lg:grid-cols-4">
                <Stat label="Files discovered" value={fmtNumber(summary.frames_discovered)} />
                <Stat
                  label="Accepted"
                  value={fmtNumber(summary.frames_accepted)}
                  tone={summary.frames_accepted ? "good" : "warn"}
                />
                <Stat
                  label="Rejected"
                  value={fmtNumber(summary.frames_rejected)}
                  tone={summary.frames_rejected ? "warn" : "default"}
                />
                <Stat label="Total bytes" value={fmtBytes(summary.total_bytes)} />
                <Stat
                  label="GPS positions"
                  value={summary.gps_available ? "available" : "missing"}
                  tone={summary.gps_available ? "good" : "warn"}
                  hint={summary.gps_available ? `${summary.frames_accepted} frames geotagged` : "frames were rejected"}
                />
                <Stat
                  label="Flight altitude"
                  value={
                    summary.altitude_range_m
                      ? `${summary.altitude_range_m[0].toFixed(1)}–${summary.altitude_range_m[1].toFixed(1)} m`
                      : null
                  }
                  hint={summary.altitude_source ?? undefined}
                />
                <Stat
                  label="Estimated GSD"
                  value={summary.gsd_available ? fmtCm(summary.gsd_m) : null}
                  hint={summary.gsd_source ? `from ${summary.gsd_source}` : "needs altitude + focal length"}
                  tone={summary.gsd_available ? "default" : "warn"}
                />
                <Stat
                  label="Image dimensions"
                  value={summary.image_dimensions.join(", ") || null}
                  hint={summary.camera_models.join(", ") || undefined}
                />
              </div>

              {inspection.dataset_warnings.length ? (
                <div className="space-y-2 border-t border-stone-200 p-4">
                  {inspection.dataset_warnings.map((w) => (
                    <Callout key={w.code} tone="warn" icon={<AlertTriangle size={13} />} title={w.text}>
                      {w.detail}
                    </Callout>
                  ))}
                </div>
              ) : null}

              {gpsMissing ? (
                <div className="border-t border-stone-200 p-4">
                  <Callout tone="danger" icon={<XCircle size={14} />} title="No usable GPS metadata">
                    None of the discovered frames carry a latitude/longitude pair. EdgeOrtho does not
                    invent coordinates and will not accept missing metadata as valid, so this dataset
                    cannot be processed. Re-export the images with location tags, or supply frames from a
                    geotagged flight.
                  </Callout>
                </div>
              ) : null}

              {inspection.unsuitability_reasons.length && summary.gps_available ? (
                <div className="border-t border-stone-200 p-4">
                  <Callout tone="warn" icon={<CircleSlash size={14} />} title="This dataset is not suitable as-is">
                    <ul className="list-disc space-y-1 pl-4">
                      {inspection.unsuitability_reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  </Callout>
                </div>
              ) : null}
            </Panel>

            {/* ------------------------------------------------ flight preview */}
            {inspection.geojson?.footprints?.features?.length ? (
              <Panel>
                <PanelHeader
                  title="3 · Flight footprint preview"
                  subtitle="Real ground footprints computed from the EXIF GPS, altitude and camera yaw"
                  icon={<MapPin size={14} />}
                  actions={
                    <span className="text-2xs text-stone-500">
                      {inspection.crs ?? "CRS unavailable"} ·{" "}
                      {summary.flight_extent
                        ? `${summary.flight_extent.width_m.toFixed(0)} × ${summary.flight_extent.height_m.toFixed(0)} m`
                        : DASH}
                    </span>
                  }
                />
                <div className="h-[320px] overflow-hidden rounded-b-card border-t border-stone-200">
                  <MapView
                    layers={{
                      footprint: inspection.geojson.footprints,
                      flightPath: inspection.geojson.flight_path,
                      preview: null,
                      previewBounds: null,
                      outputBounds: null,
                      tileUrlTemplate: null,
                      tileMinZoom: null,
                      tileMaxZoom: null,
                    }}
                  />
                </div>
              </Panel>
            ) : (
              <Callout tone="info" icon={<Info size={14} />} title="No footprint preview">
                A footprint preview needs both GPS positions and an estimated ground sampling distance
                (altitude plus focal length). One of those is missing, so no polygons are drawn — and none
                are invented.
              </Callout>
            )}

            {/* -------------------------------------------------- frame tables */}
            <FrameTables accepted={accepted} rejected={rejected} />
          </>
        ) : null}
      </div>

      {/* ------------------------------------------------------------ sidebar */}
      <div className="space-y-4">
        <Panel>
          <PanelHeader title="4 · Processing settings" icon={<Layers size={14} />} />
          <div className="space-y-3 p-4">
            <Field label="Run name">
              <input
                className="field"
                placeholder="e.g. Site 01 — north field"
                value={runName}
                onChange={(e) => setRunName(e.target.value)}
              />
            </Field>
            <Field
              label="Resource profile"
              hint={
                system?.profiles.find((p) => p.name === profile)?.description ??
                "Configured CPU/RAM limits, not a physical device measurement."
              }
            >
              <Select
                value={profile}
                onChange={setProfile}
                options={(system?.profiles ?? []).map((p) => ({
                  value: p.name,
                  label: `${p.label}${p.acceptance ? " — acceptance" : ""}`,
                }))}
              />
            </Field>
            <Field
              label="Settings preset"
              hint={system?.presets.find((p) => p.name === preset)?.description ?? ""}
            >
              <Select
                value={preset}
                onChange={setPreset}
                options={(system?.presets ?? []).map((p) => ({ value: p.name, label: p.label }))}
              />
            </Field>
            <Field
              label="Alignment model"
              hint={
                alignment === "affine"
                  ? "Similarity/affine pairs drive the global solve and the composition. Stable for flat, nadir imagery."
                  : "Also estimates homography per pair and chains it for comparison. Composition still uses the validated similarity solve."
              }
            >
              <Select
                value={alignment}
                onChange={setAlignment}
                options={[
                  { value: "affine", label: "Affine / similarity (default)" },
                  { value: "both", label: "Affine + homography comparison" },
                  { value: "homography", label: "Homography comparison only" },
                ]}
              />
            </Field>

            <div className="divider" />

            <Callout tone="info" icon={<Info size={13} />} title="What will run">
              <ul className="mt-1 space-y-0.5 text-2xs">
                <li>Ingest → Validate GPS → Plan Neighbours → Match → Align → Compose → Georeference → Export</li>
                <li>Matching on ~0.6 MP copies · 2048 px output tiles · weak GPS prior</li>
                <li>{summary?.frames_accepted ?? 0} accepted frame(s) queued for processing</li>
              </ul>
            </Callout>

            <Button
              variant="primary"
              className="w-full"
              disabled={!inspection || !summary?.gps_available || unsuitable || starting || busy}
              icon={starting ? <Spinner /> : <Play size={14} />}
              onClick={() => void startRun()}
            >
              {starting ? "Starting…" : "Start processing"}
            </Button>
            {unsuitable && summary?.gps_available ? (
              <p className="text-2xs leading-relaxed text-signal-amber">
                Processing is disabled because the dataset did not pass the suitability checks above.
                Adjust the source or reduce the scope — EdgeOrtho will not pretend to process it.
              </p>
            ) : null}
          </div>
        </Panel>

        {system ? (
          <Panel className="p-4">
            <div className="flex items-center gap-2 text-stone-700">
              <Cpu size={13} />
              <span className="text-xs font-semibold">This machine</span>
            </div>
            <dl className="mt-2 space-y-1 text-2xs text-stone-600">
              <Row label="Platform" value={system.platform} />
              <Row label="Python" value={system.python} />
              <Row label="Logical cores" value={String(system.cpu_logical)} />
              <Row label="Physical cores" value={String(system.cpu_physical)} />
              <Row label="RAM" value={`${(system.ram_total_mb / 1024).toFixed(0)} GB`} />
              <Row label="COG driver" value={system.capabilities.cog_driver ? "available" : "unavailable"} />
              <Row label="XYZ tiles" value={system.capabilities.xyz_tiles ? "native" : "unavailable"} />
            </dl>
          </Panel>
        ) : null}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt>{label}</dt>
      <dd className="truncate text-right text-stone-800">{value}</dd>
    </div>
  );
}

function FolderHints({ system, onPick }: { system: SystemInfo | null; onPick: (path: string) => void }) {
  const [items, setItems] = useState<{ name: string; path: string; images: number }[]>([]);
  const [open, setOpen] = useState(false);

  const load = async (path?: string) => {
    try {
      const listing = await api.browse(path);
      const dirs = await Promise.all(
        listing.directories.slice(0, 8).map(async (d) => {
          try {
            const sub = await api.browse(d.path);
            return { name: d.name, path: d.path, images: sub.images_here };
          } catch {
            return { name: d.name, path: d.path, images: 0 };
          }
        }),
      );
      setItems(dirs.filter((d) => d.images > 0));
      if (!dirs.filter((d) => d.images > 0).length) setItems(dirs);
    } catch {
      setItems([]);
    }
  };

  return (
    <div>
      <button
        type="button"
        className="text-2xs text-stone-500 underline decoration-stone-300 underline-offset-2 hover:text-stone-800"
        onClick={() => {
          setOpen((v) => !v);
          if (!open) void load(system?.data_dir);
        }}
      >
        {open ? "Hide suggestions" : "Show folders containing imagery"}
      </button>
      {open ? (
        <ul className="mt-2 space-y-1">
          {items.length ? (
            items.map((d) => (
              <li key={d.path}>
                <button
                  type="button"
                  onClick={() => onPick(d.path)}
                  className="flex w-full items-center gap-2 rounded-[3px] border border-stone-200 bg-stone-50 px-2 py-1.5 text-left hover:bg-stone-100"
                >
                  <FolderOpen size={12} className="text-stone-500" />
                  <span className="min-w-0 flex-1 truncate font-mono text-2xs text-stone-700">{d.path}</span>
                  <span className="text-2xs text-stone-500">{pluralise(d.images, "image")}</span>
                </button>
              </li>
            ))
          ) : (
            <li className="text-2xs text-stone-500">No folders with imagery found nearby.</li>
          )}
        </ul>
      ) : null}
    </div>
  );
}

function SamplePicker({ onLoad, busy }: { onLoad: (key: string, path: string | null) => void; busy: boolean }) {
  const [datasets, setDatasets] = useState<
    { key: string; label: string; description: string; license: string; repo: string; expected_images: number; approx_bytes: number; installed: boolean; path: string | null }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const { datasets: list } = await api.samples();
        setDatasets(list);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <Spinner />;
  if (err) return <Callout tone="danger">{err}</Callout>;

  return (
    <div className="space-y-3">
      <Callout tone="info" icon={<Satellite size={13} />} title="Public OpenDroneMap datasets">
        Small, real, geotagged flights used for the first evaluation. Imagery is downloaded into{" "}
        <code className="kbd">data/raw</code> (git-ignored) and never redistributed with EdgeOrtho. Licences
        are shown before you download.
      </Callout>
      <ul className="space-y-2">
        {datasets.map((d) => (
          <li key={d.key} className="flex items-start gap-3 rounded-card border border-stone-200 bg-stone-50 px-3 py-2.5">
            <Satellite size={15} className="mt-0.5 shrink-0 text-forest-600" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-stone-800">{d.label}</span>
                {d.installed ? <Chip tone="green">downloaded</Chip> : null}
                <Chip>{fmtBytes(d.approx_bytes)}</Chip>
              </div>
              <p className="mt-0.5 text-2xs leading-relaxed text-stone-600">{d.description}</p>
              <p className="mt-1 text-2xs text-stone-500">
                Licence: {d.license} ·{" "}
                <a className="link" href={d.repo} target="_blank" rel="noreferrer noopener">
                  source repository
                </a>
              </p>
            </div>
            <Button
              variant={d.installed ? "secondary" : "primary"}
              disabled={busy}
              onClick={() => onLoad(d.key, d.path)}
            >
              {d.installed ? "Use it" : "Download & use"}
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FrameTables({
  accepted,
  rejected,
}: {
  accepted: InspectionResult["frames"];
  rejected: InspectionResult["frames"];
}) {
  const [tab, setTab] = useState<"accepted" | "rejected">(accepted.length ? "accepted" : "rejected");
  const rows = tab === "accepted" ? accepted : rejected;

  const cols = useMemo(() => {
    if (tab === "accepted") {
      return [
        { key: "file", header: "Frame", render: (f: InspectionResult["frames"][number]) => (
          <span className="block max-w-[16rem] truncate font-mono text-2xs" title={f.path}>
            {f.filename}
          </span>
        ) },
        { key: "size", header: "Pixels", render: (f: InspectionResult["frames"][number]) =>
          f.width && f.height ? `${f.width}×${f.height}` : DASH, align: "right" as const },
        { key: "bytes", header: "Bytes", render: (f: InspectionResult["frames"][number]) => fmtBytes(f.bytes), align: "right" as const },
        { key: "gps", header: "GPS", render: (f: InspectionResult["frames"][number]) => (
          <span className="font-mono text-2xs">{fmtLatLon(f.latitude, f.longitude, 5)}</span>
        ) },
        { key: "alt", header: "Altitude", render: (f: InspectionResult["frames"][number]) =>
          isMeasured(f.altitude_m) ? `${f.altitude_m!.toFixed(1)} m` : DASH, align: "right" as const },
        { key: "gsd", header: "GSD", render: (f: InspectionResult["frames"][number]) => fmtCm(f.gsd_m), align: "right" as const },
        { key: "yaw", header: "Yaw", render: (f: InspectionResult["frames"][number]) =>
          isMeasured(f.yaw_deg) ? `${f.yaw_deg!.toFixed(0)}°` : DASH, align: "right" as const },
        { key: "warn", header: "Notes", render: (f: InspectionResult["frames"][number]) => (
          <span className="flex flex-wrap gap-1">
            {f.warning_text.length ? (
              f.warning_text.map((w) => (
                <Tooltip key={w} text={w}>
                  <span className="chip border-signal-amber/30 bg-signal-amber/10 text-signal-amber">
                    {w.slice(0, 26)}…
                  </span>
                </Tooltip>
              ))
            ) : (
              <span className="text-2xs text-stone-400">clean</span>
            )}
          </span>
        ) },
      ];
    }
    return [
      { key: "file", header: "Frame", render: (f: InspectionResult["frames"][number]) => (
        <span className="block max-w-[18rem] truncate font-mono text-2xs" title={f.path}>{f.filename}</span>
      ) },
      { key: "reason", header: "Reason", render: (f: InspectionResult["frames"][number]) => (
        <span className="flex flex-col gap-0.5">
          <span className="font-medium text-signal-red">
            {REJECT_REASON_LABELS[f.reject_reason ?? ""] ?? f.reject_reason ?? "unknown"}
          </span>
          <span className="text-2xs text-stone-500">{f.reject_reason_text}</span>
        </span>
      ) },
      { key: "bytes", header: "Bytes", render: (f: InspectionResult["frames"][number]) => fmtBytes(f.bytes), align: "right" as const },
      { key: "lat", header: "Latitude", render: (f: InspectionResult["frames"][number]) => (isMeasured(f.latitude) ? f.latitude!.toFixed(6) : DASH), align: "right" as const },
      { key: "lon", header: "Longitude", render: (f: InspectionResult["frames"][number]) => (isMeasured(f.longitude) ? f.longitude!.toFixed(6) : DASH), align: "right" as const },
    ];
  }, [tab]);

  return (
    <Panel>
      <PanelHeader
        title="Frame-level report"
        subtitle="Every discovered file with the reason it was accepted or rejected"
        icon={<Info size={14} />}
        actions={
          <div className="flex gap-1">
            {(["accepted", "rejected"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cx(
                  "rounded-[3px] border px-2 py-1 text-2xs",
                  tab === t
                    ? "border-stone-400 bg-stone-100 font-semibold text-stone-900"
                    : "border-stone-300 bg-stone-50 text-stone-600 hover:bg-stone-100",
                )}
              >
                {t === "accepted" ? `Accepted (${accepted.length})` : `Rejected (${rejected.length})`}
              </button>
            ))}
          </div>
        }
      />
      <DataTable
        rows={rows}
        columns={cols}
        getRowKey={(f) => f.frame_id}
        compact
        empty={
          <EmptyState title={tab === "accepted" ? "No accepted frames" : "Nothing was rejected"}>
            {tab === "accepted"
              ? "Every discovered file failed validation — see the rejected tab for the reasons."
              : "All discovered frames had usable GPS metadata and readable pixels."}
          </EmptyState>
        }
      />
      {summaryFraction(accepted.length, rejected.length)}
    </Panel>
  );
}

function summaryFraction(accepted: number, rejected: number) {
  const total = accepted + rejected;
  if (!total) return null;
  return (
    <div className="flex items-center gap-3 border-t border-stone-200 px-4 py-2.5 text-2xs text-stone-600">
      <span>
        {fmtPercent(accepted / total, 1)} of {pluralise(total, "frame")} accepted
      </span>
      <span className="text-stone-300">|</span>
      <span>Coverage of the flight: {accepted} of {total}</span>
    </div>
  );
}
