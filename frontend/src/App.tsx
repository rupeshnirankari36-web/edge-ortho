import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  Cpu,
  FolderOpen,
  Grid3x3,
  History as HistoryIcon,
  Map as MapIcon,
  PlusSquare,
  Settings as SettingsIcon,
} from "lucide-react";
import { api, type RunListItem, type SystemInfo } from "./lib/api";
import { cx, StatusChip, Tooltip } from "./components/ui";
import Overview from "./pages/Overview";
import NewProject from "./pages/NewProject";
import Processing from "./pages/Processing";
import MapViewer from "./pages/MapViewer";
import ImageViewer from "./pages/ImageViewer";
import Results from "./pages/Results";
import PerformanceLab from "./pages/PerformanceLab";
import History from "./pages/History";
import SettingsPage from "./pages/Settings";

export interface Route {
  page: string;
  param: string | null;
}

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [page, param] = raw.split("/");
  return { page: page || "overview", param: param || null };
}

export function navigate(page: string, param?: string) {
  const target = param ? `#/${page}/${param}` : `#/${page}`;
  if (window.location.hash !== target) window.location.hash = target;
}

const NAV = [
  { page: "overview", label: "Overview", icon: Grid3x3 },
  { page: "new", label: "New project", icon: PlusSquare },
  { page: "processing", label: "Processing", icon: Cpu },
  { page: "map", label: "Map viewer", icon: MapIcon },
  { page: "results", label: "Results", icon: FolderOpen },
  { page: "performance", label: "Performance lab", icon: BarChart3 },
  { page: "history", label: "Run history", icon: HistoryIcon },
  { page: "settings", label: "Settings", icon: SettingsIcon },
] as const;

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseHash());
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [systemError, setSystemError] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(
    () => window.localStorage.getItem("edgeortho.activeRun"),
  );

  useEffect(() => {
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    if (!window.location.hash) window.location.hash = "#/overview";
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const refreshSystem = useCallback(async () => {
    try {
      setSystem(await api.system());
      setSystemError(null);
    } catch (err) {
      setSystemError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const refreshRuns = useCallback(async () => {
    try {
      const { runs: list } = await api.listRuns();
      setRuns(list);
      return list;
    } catch {
      return [];
    }
  }, []);

  useEffect(() => {
    void refreshSystem();
    void refreshRuns();
  }, [refreshSystem, refreshRuns]);

  useEffect(() => {
    if (activeRunId) window.localStorage.setItem("edgeortho.activeRun", activeRunId);
    else window.localStorage.removeItem("edgeortho.activeRun");
  }, [activeRunId]);

  const selectRun = useCallback((runId: string | null) => setActiveRunId(runId), []);

  const shared = useMemo(
    () => ({ system, runs, refreshRuns, refreshSystem, activeRunId, selectRun, systemError }),
    [system, runs, refreshRuns, refreshSystem, activeRunId, selectRun, systemError],
  );

  const activeRun = runs.find((r) => r.run_id === activeRunId) ?? null;
  const runningCount = runs.filter((r) => r.status === "running").length;

  return (
    <div className="flex h-full min-h-screen bg-stone-100">
      <a
        href="#/overview"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50
          focus:rounded focus:bg-stone-50 focus:px-3 focus:py-1.5 focus:text-sm"
      >
        Skip to content
      </a>

      <Sidebar route={route} system={system} activeRun={activeRun} runsCount={runs.length} running={runningCount} />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          route={route}
          system={system}
          activeRun={activeRun}
          onRefresh={() => {
            void refreshSystem();
            void refreshRuns();
          }}
        />
        <main className="min-h-0 flex-1 overflow-y-auto scroll-thin">
          {systemError ? (
            <div className="m-4 rounded-card border border-signal-red/40 bg-signal-red/[0.06] px-4 py-3 text-xs text-stone-800">
              <div className="font-semibold text-signal-red">The local backend is not reachable</div>
              <p className="mt-1 leading-relaxed text-stone-600">
                Start it with <code className="kbd">python -m edge_ortho.cli serve</code> from the{" "}
                <code className="kbd">backend</code> folder. Detail: {systemError}
              </p>
            </div>
          ) : null}

          {route.page === "overview" ? <Overview {...shared} onNavigate={navigate} /> : null}
          {route.page === "new" ? <NewProject {...shared} onNavigate={navigate} /> : null}
          {route.page === "processing" ? <Processing {...shared} runId={route.param} onNavigate={navigate} /> : null}
          {route.page === "map" ? <MapViewer {...shared} runId={route.param} onNavigate={navigate} /> : null}
          {route.page === "image" ? <ImageViewer {...shared} runId={route.param} onNavigate={navigate} /> : null}
          {route.page === "results" ? <Results {...shared} runId={route.param} onNavigate={navigate} /> : null}
          {route.page === "performance" ? <PerformanceLab {...shared} onNavigate={navigate} /> : null}
          {route.page === "history" ? <History {...shared} onNavigate={navigate} /> : null}
          {route.page === "settings" ? <SettingsPage {...shared} onNavigate={navigate} /> : null}
        </main>
      </div>
    </div>
  );
}

function Sidebar({
  route,
  system,
  activeRun,
  runsCount,
  running,
}: {
  route: Route;
  system: SystemInfo | null;
  activeRun: RunListItem | null;
  runsCount: number;
  running: number;
}) {
  return (
    <aside className="app-sidebar flex w-60 shrink-0 flex-col border-r border-stone-900/40 bg-stone-900 text-white">
      <div className="flex items-center gap-3 border-b border-white/10 px-4 py-4">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[5px] border border-forest-400/60 bg-forest-800">
          <svg viewBox="0 0 32 32" className="h-4 w-4" aria-hidden>
            <path
              d="M7 22V10l9 7 9-7v12"
              stroke="#FFFFFF"
              strokeWidth="2.4"
              fill="none"
              strokeLinejoin="round"
            />
          </svg>
        </span>
        <div className="brand-copy min-w-0">
          <div className="truncate text-[11px] font-semibold uppercase tracking-[0.18em] text-forest-300">GEOAI 01</div>
          <div className="truncate text-sm font-semibold tracking-tight text-white">EDGE-ORTHO</div>
          <div className="truncate text-2xs text-stone-400">edge-based drone mapping</div>
        </div>
      </div>

      <nav className="flex-1 px-2 py-3" aria-label="Primary">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = route.page === item.page;
          const badge =
            item.page === "history" && runsCount ? String(runsCount) : item.page === "processing" && running ? "•" : null;
          return (
            <button
              key={item.page}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => navigate(item.page)}
              className={cx(
                "group mb-0.5 flex w-full items-center gap-2.5 rounded-[5px] border-l-2 px-2.5 py-2 text-left text-xs transition-colors",
                active
                  ? "border-forest-400 bg-forest-800/80 font-semibold text-white"
                  : "border-transparent text-stone-400 hover:bg-white/[0.06] hover:text-white",
              )}
            >
              <Icon size={15} className={active ? "text-forest-300" : "text-stone-500"} />
              <span className="nav-label flex-1 truncate">{item.label}</span>
              {badge ? (
                  <span className="rounded-full bg-white/10 px-1.5 text-2xs tabular-nums text-stone-300">
                  {badge}
                </span>
              ) : null}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-meta border-t border-white/10 px-3 py-3">
        {activeRun ? (
          <button
            type="button"
            onClick={() => navigate("results", activeRun.run_id)}
            className="run-context mb-2 w-full rounded-[5px] border border-white/10 bg-white/[0.06] px-2 py-1.5 text-left hover:bg-white/[0.1]"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-2xs font-semibold uppercase tracking-[0.07em] text-stone-500">
                Current run
              </span>
              <StatusChip status={activeRun.status} />
            </div>
            <div className="mt-1 truncate text-2xs text-stone-300" title={activeRun.name}>
              {activeRun.name}
            </div>
          </button>
        ) : null}

        <div className="flex items-center gap-1.5 text-2xs text-stone-400">
          <span
            className={cx(
              "h-1.5 w-1.5 rounded-full",
              system ? "bg-forest-500" : "bg-signal-red",
            )}
          />
          <span className="truncate">
            {system ? `local backend ${system.version}` : "backend offline"}
          </span>
        </div>
        {system ? (
          <div className="mt-0.5 truncate text-2xs text-stone-500">
            {system.cpu_logical} cores · {(system.ram_total_mb / 1024).toFixed(0)} GB RAM
          </div>
        ) : null}
        <div className="mt-1.5 truncate text-2xs text-stone-500" title="Raw imagery stays on this machine">
          raw imagery stays local · no cloud upload
        </div>
      </div>
    </aside>
  );
}

const TITLES: Record<string, { title: string; subtitle: string }> = {
  overview: { title: "Overview", subtitle: "Recent runs, measurements and quick access to the last mosaic" },
  new: { title: "New mapping project", subtitle: "Validate a folder of geotagged drone imagery before processing" },
  processing: { title: "Processing workspace", subtitle: "Live pipeline stages, diagnostics and measured resource usage" },
  map: { title: "Map viewer", subtitle: "Generated mosaic, image footprints and flight path" },
  image: { title: "Final photographic mosaic", subtitle: "Native-resolution RGB output without map overlays" },
  results: { title: "Results and export", subtitle: "Outputs, geospatial metadata and downloadable evidence" },
  performance: { title: "Performance lab", subtitle: "Measured runtime, RAM, throughput and bandwidth across runs" },
  history: { title: "Run history", subtitle: "Every executed run with its settings, outputs and reports" },
  settings: { title: "Settings", subtitle: "Processing profile, matching resolution, tile size and alignment method" },
};

function TopBar({
  route,
  system,
  activeRun,
  onRefresh,
}: {
  route: Route;
  system: SystemInfo | null;
  activeRun: RunListItem | null;
  onRefresh: () => void;
}) {
  const meta = TITLES[route.page] ?? TITLES.overview;
  return (
    <header className="flex min-h-16 shrink-0 items-center justify-between gap-4 border-b border-stone-300 bg-white px-5 py-3">
      <div className="min-w-0">
        <div className="mb-0.5 text-2xs font-medium uppercase tracking-[0.08em] text-stone-500">GEOAI 01 / {meta.title}</div>
        <h1 className="truncate text-[17px] font-semibold tracking-tight text-stone-900">{meta.title}</h1>
        <p className="truncate text-xs text-stone-500">{meta.subtitle}</p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <Tooltip
          text={
            system
              ? `Profile limits and geospatial tooling are detected on this machine (${system.platform}, ${system.cpu_logical} cores).`
              : "Backend not reachable"
          }
        >
          <span className="hidden items-center gap-1.5 text-2xs text-stone-500 sm:flex">
            <Cpu size={12} />
            {system ? `local · ${system.cpu_logical} cores · ${(system.ram_total_mb / 1024).toFixed(0)} GB` : "backend unavailable"}
          </span>
        </Tooltip>
        {activeRun ? <StatusChip status={activeRun.status} label={`run ${activeRun.status}`} /> : null}
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-[3px] border border-stone-300 bg-stone-50 px-2 py-1 text-2xs text-stone-600 hover:bg-stone-200"
        >
          Refresh
        </button>
      </div>
    </header>
  );
}
