/**
 * Thin typed client for the local EdgeOrtho API.
 *
 * Every call goes to the same-origin `/api`, which Vite proxies to the local
 * FastAPI process in development and which the built app serves itself in
 * production. Nothing leaves the machine.
 *
 * The rule these types encode: a measurement the pipeline could not make is
 * `null`, never `0`. The UI renders `null` as "unavailable" rather than as a
 * misleading zero.
 */

export interface FrameRecord {
  frame_id: string;
  path: string;
  filename: string;
  bytes: number;
  accepted: boolean;
  latitude: number | null;
  longitude: number | null;
  altitude_m: number | null;
  altitude_source: string | null;
  yaw_deg: number | null;
  yaw_source: string | null;
  width: number | null;
  height: number | null;
  make: string | null;
  model: string | null;
  focal_length_mm: number | null;
  focal_length_35mm: number | null;
  gsd_m: number | null;
  gsd_source: string | null;
  footprint_w_m: number | null;
  footprint_h_m: number | null;
  projected_x: number | null;
  projected_y: number | null;
  captured_at: string | null;
  reject_reason: string | null;
  reject_reason_text: string | null;
  warnings: string[];
  warning_text: string[];
}

export interface IngestSummary {
  frames_discovered: number;
  frames_accepted: number;
  frames_rejected: number;
  rejected_by_reason: Record<string, number>;
  unsupported_files_skipped: number;
  total_bytes: number;
  total_megapixels: number;
  gps_available: boolean;
  altitude_available: boolean;
  altitude_range_m: [number, number] | null;
  altitude_source: string | null;
  yaw_available: boolean;
  yaw_source: string | null;
  gsd_available: boolean;
  gsd_m: number | null;
  gsd_source: string | null;
  footprint_m: number | null;
  image_dimensions: string[];
  camera_models: string[];
  flight_extent: {
    easting_m: [number, number];
    northing_m: [number, number];
    width_m: number;
    height_m: number;
  } | null;
  capture_window: { first: string; last: string } | null;
}

export interface InspectionResult {
  crs: string | null;
  summary: IngestSummary;
  dataset_warnings: { code: string; text: string; detail: string }[];
  suitable: boolean;
  unsuitability_reasons: string[];
  input_bytes: number;
  frames: FrameRecord[];
  discovery: { root: string | null; image_count: number; images: string[]; skipped_unsupported: string[] };
  elapsed_s?: number | null;
  suggested_name?: string;
  upload_path?: string;
  uploaded?: number;
  skipped?: string[];
  geojson?: {
    footprints: GeoJSON.FeatureCollection;
    flight_path: GeoJSON.FeatureCollection;
  } | null;
}

export interface StageRecord {
  name: string;
  index: number;
  status: "pending" | "running" | "done" | "skipped" | "failed";
  started_at: string | null;
  finished_at: string | null;
  elapsed_s: number | null;
  detail: string | null;
  error: string | null;
  unsupported_reason: string | null;
  counters: Record<string, unknown>;
  rss_mb_at_end: number | null;
}

export interface OutputMetadata {
  produced: boolean;
  kind: string;
  crs: string | null;
  crs_name: string | null;
  transform: number[] | null;
  bounds: number[] | null;
  bounds_wgs84: number[] | null;
  width: number | null;
  height: number | null;
  bands: number;
  gsd_m: number | null;
  pixel_resolution_m: number | null;
  nodata: number | null;
  alpha_mask?: boolean;
  geotiff_path: string | null;
  geotiff_bytes: number | null;
  cog_path: string | null;
  cog_bytes: number | null;
  cog_driver: string | null;
  cog_messages?: string[];
  cog_validation?: Record<string, unknown>;
  tiles_dir: string | null;
  tile_count: number | null;
  min_zoom: number | null;
  max_zoom: number | null;
  tiles_produced?: boolean;
  tiles_messages?: string[];
  preview_png: string | null;
  georeferencing_basis: string | null;
  validation: Record<string, unknown>;
  messages: string[];
}

export interface BandwidthRow {
  mbps: number;
  input_seconds: number | null;
  input_human: string | null;
  output_seconds: number | null;
  output_human: string | null;
  saved_seconds: number | null;
  saved_human: string | null;
  /** Only what a browser needs: COG + XYZ tiles, excluding the lossless GeoTIFF. */
  web_seconds: number | null;
  web_human: string | null;
  web_saved_seconds: number | null;
  web_saved_human: string | null;
}

export interface MetricsRecord {
  run_id: string;
  profile: string;
  wall_clock_s: number | null;
  time_to_first_tile_s: number | null;
  peak_rss_mb: number | null;
  baseline_rss_mb: number | null;
  peak_rss_delta_mb: number | null;
  avg_cpu_percent: number | null;
  peak_cpu_percent: number | null;
  cpu_cores_effective: number | null;
  disk_read_bytes: number | null;
  disk_write_bytes: number | null;
  frames_total: number | null;
  frames_accepted: number | null;
  frames_rejected: number | null;
  frames_failed: number | null;
  frames_composed: number | null;
  throughput_fps: number | null;
  feature_detector: string | null;
  alignment_model: string | null;
  matching_megapixels: number | null;
  tile_size: number | null;
  output_crs: string | null;
  output_kind: string | null;
  input_bytes: number | null;
  output_bytes: number | null;
  reduction_factor: number | null;
  pairs_candidates: number | null;
  pairs_matched: number | null;
  pairs_failed: number | null;
  total_matches: number | null;
  total_inliers: number | null;
  mean_inlier_ratio: number | null;
  mean_reprojection_error_px: number | null;
  mean_gps_placement_error_m: number | null;
  profile_limit_cores: number | null;
  profile_limit_ram_mb: number | null;
  profile_enforcement: Record<string, unknown>;
  bandwidth: {
    formula: string;
    input_bytes: number | null;
    output_bytes: number | null;
    web_bytes: number | null;
    reduction_factor: number | null;
    web_reduction_factor: number | null;
    scenarios: Record<string, BandwidthRow>;
  };
  measurements_unavailable: string[];
  notes: string[];
  stage_metrics: StageRecord[];
}

export interface RunReport {
  run_id: string;
  name: string;
  status: string;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  crs: string | null;
  settings: Record<string, unknown>;
  profile: string;
  profile_enforcement: Record<string, unknown>;
  metadata_summary: IngestSummary;
  dataset_warnings: { code: string; text: string; detail: string }[];
  stages: StageRecord[];
  metrics: MetricsRecord;
  output: OutputMetadata;
  canvas: {
    width: number;
    height: number;
    megapixels: number;
    gsd_m: number;
    native_gsd_m: number | null;
    crs_epsg: number | null;
    crs_name: string | null;
    extent_m: Record<string, number>;
    output_capped: boolean;
    cap_message: string | null;
    georeferenced: boolean;
    basis: string | null;
  } | null;
  alignment: Record<string, unknown>;
  alignment_comparison: Record<string, unknown>;
  messages: string[];
  limitations: string[];
  artifacts: { kind: string; label: string; filename: string; bytes: number | null }[];
  plan?: {
    candidate_pairs: number;
    all_pairs_possible: number;
    pairs_below_overlap: number;
    reduction_factor: number | null;
    radius_m: number | null;
    selection_method: string;
    notes: string[];
  };
}

export interface RunListItem {
  run_id: string;
  name: string;
  source: string | null;
  created_at: string;
  finished_at: string | null;
  status: string;
  profile: string | null;
  preset: string | null;
  frames_total: number | null;
  frames_ok: number | null;
  output_bytes: number | null;
  wall_clock_s: number | null;
  peak_rss_mb: number | null;
  error: string | null;
  summary: Record<string, unknown>;
  metrics: Partial<MetricsRecord>;
  output: Partial<OutputMetadata>;
  artifacts: { kind: string; label: string; filename: string; bytes: number | null }[];
  stages: StageRecord[];
}

export interface SystemInfo {
  version: string;
  python: string;
  platform: string;
  cpu_logical: number;
  cpu_physical: number;
  ram_total_mb: number;
  data_dir: string;
  output_dir: string;
  profiles: { name: string; label: string; cpu_cores: number | null; ram_limit_mb: number | null; description: string; acceptance: boolean }[];
  presets: { name: string; label: string; description: string; settings: Record<string, unknown> }[];
  default_settings: Record<string, unknown>;
  capabilities: Record<string, boolean | string | null>;
  active_run_id: string | null;
  supported_extensions: string[];
}

export interface PerformanceRecord {
  run_id: string;
  name: string;
  created_at: string;
  status: string;
  profile: string | null;
  preset: string | null;
  source_kind: string | null;
  frames_total: number | null;
  frames_accepted: number | null;
  frames_failed: number | null;
  wall_clock_s: number | null;
  peak_rss_mb: number | null;
  baseline_rss_mb: number | null;
  peak_rss_delta_mb: number | null;
  time_to_first_tile_s: number | null;
  throughput_fps: number | null;
  input_bytes: number | null;
  output_bytes: number | null;
  disk_read_bytes: number | null;
  disk_write_bytes: number | null;
  avg_cpu_percent: number | null;
  peak_cpu_percent: number | null;
  cpu_cores_effective: number | null;
  pairs_candidates: number | null;
  pairs_matched: number | null;
  pairs_failed: number | null;
  mean_inlier_ratio: number | null;
  mean_reprojection_error_px: number | null;
  mean_gps_placement_error_m: number | null;
  alignment_model: string | null;
  output_width: number | null;
  output_height: number | null;
  output_crs: string | null;
  output_kind: string | null;
  bandwidth: MetricsRecord["bandwidth"];
  profile_enforcement: Record<string, unknown>;
  measurements_unavailable: string[];
  comparison: Record<string, unknown> | null;
}

export interface PairRow {
  source_id: string;
  target_id: string;
  distance_m: number;
  estimated_overlap: number | null;
  selection: string;
  status?: string;
  inliers?: number;
  inlier_ratio?: number | null;
  ratio_filtered_matches?: number;
  reprojection_error_px?: number | null;
  reprojection_error_m?: number | null;
  keypoints_source?: number;
  keypoints_target?: number;
  rotation_deg?: number | null;
  scale?: number | null;
  error?: string | null;
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  system: () => request<SystemInfo>("/system"),

  listRuns: () => request<{ runs: RunListItem[] }>("/runs"),

  getRun: (runId: string) =>
    request<{
      run: RunListItem & { report?: RunReport; settings?: Record<string, unknown> };
      live?: { status: string; settings: Record<string, unknown>; events?: Record<string, unknown>[] };
    }>(`/runs/${runId}`),

  report: (runId: string) =>
    fetch(`${BASE}/runs/${runId}/report.json`).then((r) => {
      if (!r.ok) throw new Error("report not available yet");
      return r.json() as Promise<RunReport>;
    }),

  /** The stored metadata validation report (reopened from disk, not recomputed). */
  metadataReport: (runId: string) =>
    request<{
      crs: string | null;
      summary: IngestSummary;
      dataset_warnings: { code: string; text: string; detail: string }[];
      suitable: boolean;
      unsuitability_reasons: string[];
      input_bytes: number;
      frames: FrameRecord[];
    }>(`/runs/${runId}/metadata_report.json`),

  pairs: (runId: string) =>
    request<{
      candidate_pairs: number;
      matched_pairs: number | null;
      radius_m: number | null;
      selection_method: string;
      reduction_factor: number | null;
      notes: string[];
      pairs: PairRow[];
    }>(`/runs/${runId}/pairs`),

  geojson: (runId: string) =>
    request<GeoJSON.FeatureCollection & { properties: Record<string, unknown> }>(`/runs/${runId}/geojson`),

  deleteRun: (runId: string, deleteFiles: boolean) =>
    request<{ deleted: string; files_removed: boolean }>(
      `/runs/${runId}?delete_files=${deleteFiles ? "true" : "false"}`,
      { method: "DELETE" },
    ),

  inspectPath: (path: string) =>
    request<InspectionResult>("/sources/inspect", { method: "POST", body: JSON.stringify({ path }) }),

  uploadFiles: async (files: File[], onProgress?: (sent: number, total: number) => void) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    // fetch has no upload progress event; report the count stepping so the UI
    // can still show that work is happening for large sets.
    onProgress?.(0, files.length);
    const res = await fetch(`${BASE}/sources/upload`, { method: "POST", body: form });
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body?.detail) detail = body.detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    onProgress?.(files.length, files.length);
    return (await res.json()) as InspectionResult;
  },

  browse: (path?: string) =>
    request<{
      path: string;
      parent: string | null;
      directories: { name: string; path: string }[];
      images_here: number;
      other_files_here: number;
      quota: { free_bytes: number; total_bytes: number };
    }>(`/browse${path ? `?path=${encodeURIComponent(path)}` : ""}`),

  samples: () =>
    request<{
      datasets: {
        key: string;
        label: string;
        description: string;
        license: string;
        repo: string;
        credit: string;
        expected_images: number;
        approx_bytes: number;
        gps: boolean;
        installed: boolean;
        path: string | null;
      }[];
    }>("/samples"),

  fetchSample: (key: string) =>
    request<{ key: string; path: string; images: number; license: string; log: string[] }>(
      `/samples/${key}/fetch`,
      { method: "POST" },
    ),

  createRun: (payload: {
    source: string;
    name: string;
    settings: Record<string, unknown>;
  }) => request<{ run_id: string; status: string }>("/runs", { method: "POST", body: JSON.stringify(payload) }),

  performance: () =>
    request<{ records: PerformanceRecord[]; count: number; bandwidth_rates_mbps: number[]; notes: string[] }>(
      "/performance",
    ),

  settings: () => request<{ settings: Record<string, unknown>; saved: Record<string, unknown> }>("/settings"),

  saveSettings: (pipeline: Record<string, unknown>) =>
    request<Record<string, unknown>>("/settings", { method: "PUT", body: JSON.stringify({ pipeline }) }),
};

export const artifactUrl = (runId: string, name: string) => `${BASE}/runs/${runId}/${name}`;
export const tileUrl = (runId: string) => `${BASE}/runs/${runId}/tiles/{z}/{x}/{y}.png`;
export const previewUrl = (runId: string) => `${BASE}/runs/${runId}/preview.png`;
export const tilesZipUrl = (runId: string) => `${BASE}/runs/${runId}/tiles.zip`;
export const geotiffUrl = (runId: string) => `${BASE}/runs/${runId}/orthomosaic.tif`;
export const cogUrl = (runId: string) => `${BASE}/runs/${runId}/orthomosaic_cog.tif`;
export const frameSourceUrl = (runId: string, frameId: string, maxPx = 1280) =>
  `${BASE}/runs/${runId}/frames/${encodeURIComponent(frameId)}/source.jpg?max_px=${maxPx}`;
export const reportUrl = (runId: string) => `${BASE}/runs/${runId}/report.json`;
export const metricsCsvUrl = (runId: string) => `${BASE}/runs/${runId}/metrics.csv`;
export const framesCsvUrl = (runId: string) => `${BASE}/runs/${runId}/frames.csv`;
export const metadataReportUrl = (runId: string) => `${BASE}/runs/${runId}/metadata_report.json`;
export const performanceExportUrl = (fmt: "json" | "csv") => `${BASE}/performance/export?fmt=${fmt}`;

/** Subscribe to a run's SSE stream. Returns an unsubscribe function. */
export function streamRun(
  runId: string,
  onEvent: (event: Record<string, unknown>) => void,
  onError?: (message: string) => void,
): () => void {
  const source = new EventSource(`${BASE}/runs/${runId}/events`);
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data));
    } catch {
      /* ignore malformed frames */
    }
  };
  source.onerror = () => {
    onError?.("live stream interrupted");
    source.close();
  };
  return () => source.close();
}
