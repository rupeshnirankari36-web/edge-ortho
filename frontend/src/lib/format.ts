/** Formatting helpers.
 *
 * Central rule: a missing measurement renders as "not measured" (or an em dash),
 * never as `0`, `NaN` or a blank that could be mistaken for a real value. Every
 * formatter takes `number | null | undefined` on purpose.
 */

export const UNAVAILABLE = "not measured";
export const DASH = "—";

type Maybe<T> = T | null | undefined;

export function isMeasured(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function fmtNumber(value: Maybe<number>, digits = 0, fallback = DASH): string {
  if (!isMeasured(value)) return fallback;
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Bytes with binary units. */
export function fmtBytes(value: Maybe<number>, fallback = DASH): string {
  if (!isMeasured(value)) return fallback;
  if (value < 1024) return `${Math.round(value)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = value / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

export function fmtDuration(seconds: Maybe<number>, fallback = DASH): string {
  if (!isMeasured(seconds)) return fallback;
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  if (minutes < 60) return `${minutes}m ${Math.round(rest)}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes - hours * 60}m`;
}

export function fmtPercent(value: Maybe<number>, digits = 1, fallback = DASH): string {
  if (!isMeasured(value)) return fallback;
  const scaled = Math.abs(value) <= 1.5 ? value * 100 : value;
  return `${scaled.toFixed(digits)}%`;
}

export function fmtCm(metres: Maybe<number>, fallback = DASH): string {
  if (!isMeasured(metres)) return fallback;
  if (metres < 0.01) return `${(metres * 1000).toFixed(1)} mm`;
  return `${(metres * 100).toFixed(2)} cm`;
}

export function fmtMetres(value: Maybe<number>, digits = 1, fallback = DASH): string {
  if (!isMeasured(value)) return fallback;
  return `${value.toFixed(digits)} m`;
}

export function fmtTimestamp(value: Maybe<string>): { relative: string; absolute: string } {
  if (!value) return { relative: DASH, absolute: DASH };
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { relative: value, absolute: value };
  const absolute = date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.round(diffMs / 60000);
  let relative: string;
  if (diffMin < 1) relative = "just now";
  else if (diffMin < 60) relative = `${diffMin} min ago`;
  else if (diffMin < 60 * 24) relative = `${Math.round(diffMin / 60)} h ago`;
  else if (diffMin < 60 * 24 * 30) relative = `${Math.round(diffMin / (60 * 24))} d ago`;
  else relative = absolute;
  return { relative, absolute };
}

export function fmtLatLon(lat: Maybe<number>, lon: Maybe<number>, digits = 6): string {
  if (!isMeasured(lat) || !isMeasured(lon)) return DASH;
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(digits)}°${ns}, ${Math.abs(lon).toFixed(digits)}°${ew}`;
}

export function fmtBoundsWgs84(bounds: Maybe<number[]>): string {
  if (!bounds || bounds.length < 4 || !bounds.every((b) => isMeasured(b))) return DASH;
  const [w, s, e, n] = bounds;
  return `${s.toFixed(5)}°S–${n.toFixed(5)}°N, ${w.toFixed(5)}°–${e.toFixed(5)}°E`;
}

export function metricLabel(unit: string, note: string): string {
  return unit ? `${unit} · ${note}` : note;
}

export const STAGE_LABELS: Record<string, string> = {
  ingest: "Ingest",
  validate_gps: "Validate GPS",
  plan_neighbours: "Plan Neighbours",
  match_features: "Match Features",
  align: "Align",
  compose_tiles: "Compose Tiles",
  georeference: "Georeference",
  export: "Export",
};

export const STAGE_HELP: Record<string, string> = {
  ingest: "Discover supported image files and read EXIF/XMP metadata for each frame.",
  validate_gps: "Accept or reject each frame, project coordinates to UTM and estimate ground sampling distance.",
  plan_neighbours: "Use the projected GPS positions to select candidate image pairs instead of comparing everything.",
  match_features: "Detect ORB features on downscaled copies, ratio-filter matches and validate a transform with RANSAC.",
  align: "Resolve the camera heading, solve per-frame placement globally and anchor the layout to the GPS track.",
  compose_tiles: "Warp only the frames that intersect each output tile, with feathered blending and bounded memory.",
  georeference: "Write the CRS, transform and bounds, then validate the raster by reopening it.",
  export: "Produce COG, XYZ web tiles, the preview image and the JSON/CSV reports.",
};

export const REJECT_REASON_LABELS: Record<string, string> = {
  unreadable: "Unreadable file",
  unsupported_format: "Unsupported format",
  missing_gps: "No GPS tags",
  invalid_gps: "Invalid GPS tags",
  gps_out_of_range: "GPS out of range",
  zero_size: "Empty file",
  decode_failed: "Decode failed",
};

export const statusTone: Record<string, string> = {
  succeeded: "text-forest-700 border-forest-300 bg-forest-50",
  done: "text-forest-700 border-forest-300 bg-forest-50",
  running: "text-signal-blue border-signal-blue/30 bg-signal-blue/10",
  queued: "text-stone-600 border-stone-300 bg-stone-100",
  pending: "text-stone-500 border-stone-300 bg-stone-100",
  skipped: "text-signal-amber border-signal-amber/30 bg-signal-amber/10",
  failed: "text-signal-red border-signal-red/30 bg-signal-red/10",
};

export function pluralise(count: number, singular: string, plural?: string): string {
  return count === 1 ? `${count} ${singular}` : `${count} ${plural ?? `${singular}s`}`;
}
