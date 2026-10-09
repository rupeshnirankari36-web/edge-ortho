import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check,
  Cpu,
  Database,
  FolderTree,
  Info,
  Layers,
  RotateCcw,
  Save,
  Settings as SettingsIcon,
  Sliders,
  TriangleAlert,
} from "lucide-react";
import { api } from "../lib/api";
import { DASH, isMeasured } from "../lib/format";

import {
  Button,
  Callout,
  Chip,
  Field,
  KeyValue,
  Panel,
  PanelHeader,
  Select,
  SkeletonRows,
  Toggle,
} from "../components/ui";
import type { PageProps } from "./shared";

type Settings = Record<string, unknown>;

const NUMBER_FIELDS = [
  { key: "matching_megapixels", label: "Matching resolution (MP)", hint: "Downscaled copies for feature detection. The brief's default is near 0.6 MP." },
  { key: "tile_size", label: "Tile size (px)", hint: "Composition and XYZ tile grid. Smaller tiles lower peak RAM and add I/O." },
  { key: "max_output_megapixels", label: "Maximum output (MP)", hint: "Hard ceiling on the composed canvas; the run stops with an explanation instead of exhausting memory." },
  { key: "min_valid_frames", label: "Minimum valid frames", hint: "Below this, the run is rejected before composing anything." },
] as const;

const ADVANCED_NUMBER_FIELDS = [
  { key: "orb_features", label: "Features per frame", hint: "ORB keypoint budget per downscaled frame." },
  { key: "ratio_threshold", label: "Lowe ratio", hint: "Descriptor ratio test; lower is stricter." },
  { key: "min_matches", label: "Minimum ratio-filtered matches", hint: "Pairs below this are rejected before RANSAC." },
  { key: "min_inliers", label: "Minimum RANSAC inliers", hint: "A transform with fewer inliers is not accepted." },
  { key: "max_reprojection_error_px", label: "Maximum reprojection error (px)", hint: "Pair transforms above this RMSE are rejected." },
  { key: "neighbour_max_links", label: "Maximum neighbour links", hint: "Candidate pairs per frame; this is the comparison budget." },
  { key: "seam_blend_px", label: "Seam blend (px)", hint: "Feather width when two frames overlap a tile edge." },
  { key: "decode_cache_size", label: "Decode cache (frames)", hint: "How many full-resolution frames stay in memory while composing." },
] as const;

export default function SettingsPage({
  system,
  systemError,
  refreshSystem,
  onNavigate,
}: PageProps & { onNavigate: (page: string, param?: string) => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [stored, setStored] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);

  const load = useCallback(async () => {
    try {
      const payload = await api.settings();
      setSettings(payload.settings);
      setStored(((payload.saved ?? {}) as { pipeline?: Settings }).pipeline ?? {});
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const defaults = system?.default_settings ?? null;
  const dirty = useMemo(() => {
    if (!settings || !defaults) return false;
    return Object.keys(settings).some(
      (k) => JSON.stringify(settings[k]) !== JSON.stringify(stored?.[k] ?? defaults[k]),
    );
  }, [settings, stored, defaults]);

  const update = (key: string, value: unknown) => {
    setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSavedAt(null);
  };

  const applyPreset = (name: string) => {
    const preset = system?.presets.find((p) => p.name === name);
    if (!preset) return;
    setSettings((prev) => ({ ...(prev ?? {}), ...preset.settings, preset: name }));
    setSavedAt(null);
  };

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setError(null);
    try {
      const result = await api.saveSettings(settings);
      setStored((result as { pipeline?: Settings }).pipeline ?? {});
      setSavedAt(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const resetToDefaults = () => {
    if (!defaults) return;
    setSettings({ ...defaults });
    setSavedAt(null);
  };

  const caps = (system?.capabilities ?? {}) as Record<string, string | boolean | null>;

  return (
    <div className="grid gap-4 p-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0 space-y-4">
        <Panel>
          <PanelHeader
            title="Processing settings"
            subtitle="Applied to new runs; completed runs keep the settings recorded with them"
            icon={<SettingsIcon size={14} />}
            actions={
              <div className="flex items-center gap-2">
                {savedAt ? (
                  <span className="flex items-center gap-1 text-2xs text-forest-700">
                    <Check size={11} /> saved {savedAt}
                  </span>
                ) : dirty ? (
                  <span className="text-2xs text-signal-amber">unsaved changes</span>
                ) : null}
                <Button variant="ghost" icon={<RotateCcw size={12} />} onClick={resetToDefaults} disabled={!defaults}>
                  Defaults
                </Button>
                <Button variant="primary" icon={<Save size={13} />} onClick={() => void save()} disabled={saving || !settings}>
                  {saving ? "Saving…" : "Save settings"}
                </Button>
              </div>
            }
          />

          {error ? (
            <div className="border-b border-stone-200 p-3">
              <Callout tone="danger" icon={<TriangleAlert size={13} />} title="Settings could not be saved">
                {error}
              </Callout>
            </div>
          ) : null}

          {!settings ? (
            <SkeletonRows rows={4} />
          ) : (
            <>
              <div className="grid gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="Resource profile" hint="Runs marked acceptance match the brief's target device; limits are emulated on this host.">
                  <Select
                    value={String(settings.profile ?? "laptop")}
                    onChange={(v) => update("profile", v)}
                    options={(system?.profiles ?? []).map((p) => ({
                      value: p.name,
                      label: `${p.label} — ${p.ram_limit_mb ? `${p.ram_limit_mb} MB RAM` : "no RAM cap"}`,
                    }))}
                  />
                </Field>

                <Field label="Preset" hint="Loads a coherent group of settings below; individual values stay editable.">
                  <Select
                    value={String(settings.preset ?? "balanced")}
                    onChange={applyPreset}
                    options={(system?.presets ?? []).map((p) => ({ value: p.name, label: p.label }))}
                  />
                </Field>

                <Field label="Alignment model" hint="Similarity is always solved globally for composition; homography is validated and recorded for comparison.">
                  <Select
                    value={String(settings.alignment_model ?? "affine")}
                    onChange={(v) => update("alignment_model", v)}
                    options={[
                      { value: "affine", label: "Affine / similarity (default)" },
                      { value: "homography", label: "Homography (estimate + compare)" },
                      { value: "both", label: "Both (compare and record)" },
                    ]}
                  />
                </Field>

                <Field label="Feature detector" hint="ORB is the default; AKAZE is slower but more robust on low-texture frames.">
                  <Select
                    value={String(settings.feature_detector ?? "orb")}
                    onChange={(v) => update("feature_detector", v)}
                    options={[
                      { value: "orb", label: "ORB" },
                      { value: "akaze", label: "AKAZE" },
                    ]}
                  />
                </Field>

                {NUMBER_FIELDS.map((f) => (
                  <Field key={f.key} label={f.label} hint={f.hint}>
                    <input
                      className="field tabular-nums"
                      type="number"
                      step="any"
                      value={String(settings[f.key] ?? "")}
                      onChange={(e) => update(f.key, e.target.value === "" ? null : Number(e.target.value))}
                    />
                  </Field>
                ))}
              </div>

              <div className="border-t border-stone-200 px-4 py-2">
                <Toggle
                  label="Show advanced matching, planning and composition parameters"
                  hint="Thresholds that decide whether a pair is accepted, and how the composer trades memory for I/O."
                  checked={advanced}
                  onChange={setAdvanced}
                />
              </div>

              {advanced ? (
                <div className="grid gap-4 border-t border-stone-200 p-4 sm:grid-cols-2 lg:grid-cols-3">
                  {ADVANCED_NUMBER_FIELDS.map((f) => (
                    <Field key={f.key} label={f.label} hint={f.hint}>
                      <input
                        className="field tabular-nums"
                        type="number"
                        step="any"
                        value={String(settings[f.key] ?? "")}
                        onChange={(e) => update(f.key, e.target.value === "" ? null : Number(e.target.value))}
                      />
                    </Field>
                  ))}
                  <div className="sm:col-span-2 lg:col-span-3">
                    <Toggle
                      label="Exposure compensation when blending overlaps"
                      hint="Matches the mean brightness of overlapping frames so tile seams are less visible."
                      checked={Boolean(settings.exposure_compensation ?? true)}
                      onChange={(v) => update("exposure_compensation", v)}
                    />
                  </div>
                </div>
              ) : null}
            </>
          )}
        </Panel>

        <Panel>
          <PanelHeader
            title="What each setting costs"
            subtitle="The trade-offs the pipeline actually makes"
            icon={<Sliders size={14} />}
          />
          <ul className="space-y-2 px-4 py-3 text-xs leading-relaxed text-stone-600">
            <li>
              <span className="font-semibold text-stone-800">Matching resolution.</span> Feature
              detection runs on downscaled copies. Raising it improves match quality on fine texture
              and increases both time and peak memory roughly with the pixel count.
            </li>
            <li>
              <span className="font-semibold text-stone-800">Tile size.</span> The composer holds one
              output tile per band pass, not the whole canvas. Larger tiles mean fewer passes over the
              frames but a bigger single allocation.
            </li>
            <li>
              <span className="font-semibold text-stone-800">Decode cache.</span> Each full-resolution
              frame decoded for composition costs about width × height × 3 bytes. The cache is the
              single largest lever on peak RSS and is bounded by design.
            </li>
            <li>
              <span className="font-semibold text-stone-800">Alignment model.</span> The homography
              path re-estimates every pair with a second model, so it roughly doubles the matching
              work; it is recorded as evidence and never silently becomes the composite geometry.
            </li>
          </ul>
        </Panel>
      </div>

      <div className="space-y-4">
        <Panel>
          <PanelHeader title="This machine" icon={<Cpu size={14} />} />
          {system ? (
            <dl className="px-4 py-2">
              <KeyValue label="Backend version" value={system.version} />
              <KeyValue label="Python" value={system.python} />
              <KeyValue label="Platform" value={system.platform} mono={false} />
              <KeyValue label="CPU cores (logical / physical)" value={`${system.cpu_logical} / ${system.cpu_physical ?? DASH}`} />
              <KeyValue label="Total RAM" value={`${(system.ram_total_mb / 1024).toFixed(1)} GB`} />
              <KeyValue label="Data directory" value={system.data_dir} mono={false} />
              <KeyValue label="Output directory" value={system.output_dir} mono={false} />
              <KeyValue label="Supported inputs" value={system.supported_extensions.join(", ")} mono={false} />
            </dl>
          ) : (
            <Callout tone="warn" icon={<TriangleAlert size={13} />} title="Backend offline">
              {systemError ?? "The local API is not answering."}{" "}
              <button type="button" className="link" onClick={() => void refreshSystem()}>
                Retry
              </button>
            </Callout>
          )}
        </Panel>

        <Panel>
          <PanelHeader title="Geospatial capabilities" subtitle="Detected at startup" icon={<Layers size={14} />} />
          <div className="flex flex-wrap gap-1.5 p-4">
            {Object.entries(caps).map(([key, value]) => {
              const ok = value !== null && value !== false && value !== "";
              return (
                <Chip key={key} tone={ok ? "green" : "amber"} title={value === null ? "not available" : String(value)}>
                  {key.replace(/_/g, " ")}: {value === null ? "unavailable" : String(value)}
                </Chip>
              );
            })}
            {!Object.keys(caps).length ? (
              <p className="text-xs text-stone-500">Capabilities are reported by the backend.</p>
            ) : null}
          </div>
          <p className="border-t border-stone-200 px-4 py-3 text-2xs leading-relaxed text-stone-500">
            COG conversion and XYZ tile generation are only attempted when the corresponding tool is
            present. When it is missing the stage is reported as unavailable rather than downgraded
            silently.
          </p>
        </Panel>

        <Panel>
          <PanelHeader title="Storage" icon={<Database size={14} />} />
          <ul className="space-y-2 px-4 py-3 text-2xs leading-relaxed text-stone-600">
            <li>
              <code className="kbd">data/edgeortho.sqlite3</code> holds run records, per-stage
              counters and settings.
            </li>
            <li>
              <code className="kbd">data/meta/&lt;run_id&gt;/</code> holds the metadata validation
              report, frame table, pair statistics and the run report.
            </li>
            <li>
              <code className="kbd">outputs/&lt;run_id&gt;/</code> holds the GeoTIFF, COG, XYZ tiles
              and the mosaic preview.
            </li>
            <li>Raw source imagery is read in place and never copied into the workspace.</li>
          </ul>
        </Panel>

        <Panel>
          <PanelHeader title="Next step" icon={<FolderTree size={14} />} />
          <div className="p-4">
            <p className="text-xs leading-relaxed text-stone-600">
              Settings take effect on the next run. Validate a dataset to see the profile applied to
              real frames.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => onNavigate("new")}>
                New mapping project
              </Button>
              <Button onClick={() => onNavigate("performance")}>Performance lab</Button>
            </div>
          </div>
        </Panel>

        <Callout tone="info" icon={<Info size={13} />} title="Emulated limits">
          The pi-class and pi-lite profiles constrain CPU affinity and apply a soft RSS ceiling on
          this machine. They are a repeatable budget test, not a substitute for measuring on that
          hardware.
        </Callout>

        {defaults && settings ? (
          <Panel>
            <PanelHeader title="Effective values" icon={<Info size={14} />} />
            <dl className="scroll-thin max-h-72 overflow-y-auto px-4 py-2">
              {Object.entries(settings).map(([k, v]) => (
                <KeyValue
                  key={k}
                  label={k.replace(/_/g, " ")}
                  value={isMeasured(v) ? String(v) : v === null || v === undefined ? null : String(v)}
                  mono={typeof v !== "string"}
                  title={JSON.stringify(v)}
                />
              ))}
            </dl>
          </Panel>
        ) : null}
      </div>
    </div>
  );
}
