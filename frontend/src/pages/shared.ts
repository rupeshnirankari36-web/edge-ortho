import type { RunListItem, SystemInfo } from "../lib/api";

/** Persisted demo run shipped by the local preview environment. */
export const PRECOMPUTED_DEMO_RUN_ID = "20261009-204206-5b4281";
export const PRECOMPUTED_DEMO_BOUNDS_WGS84 = [-91.99515790452753, 46.84186863551548, -91.99285552107159, 46.84344940280311] as const;

export interface PageProps {
  system: SystemInfo | null;
  runs: RunListItem[];
  refreshRuns: () => Promise<RunListItem[]>;
  refreshSystem: () => Promise<void>;
  activeRunId: string | null;
  selectRun: (runId: string | null) => void;
  systemError: string | null;
  onNavigate: (page: string, param?: string) => void;
}

export function runThumbnail(run: RunListItem): string | null {
  const hasPreview = run.artifacts?.some((a) => a.kind === "preview_png" || a.kind === "orthomosaic_preview");
  const produced = (run.output as { produced?: boolean })?.produced;
  if (!hasPreview && !produced) return null;
  return `/api/runs/${run.run_id}/preview.png`;
}
