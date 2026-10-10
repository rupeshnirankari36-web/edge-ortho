import { useEffect, useState } from "react";
import { ArrowLeft, Download, Image as ImageIcon, Map as MapIcon } from "lucide-react";
import { cogUrl, geotiffUrl, type RunListItem } from "../lib/api";
import { fmtBytes, fmtCm, fmtNumber } from "../lib/format";
import { PhotoMap } from "../components/PhotoMap";
import { Button, EmptyState, Panel, PanelHeader, Stat } from "../components/ui";
import { PRECOMPUTED_DEMO_RUN_ID, type PageProps } from "./shared";

export default function ImageViewer({ runId, activeRunId, onNavigate }: PageProps & { runId: string | null }) {
  const effectiveId = runId ?? activeRunId ?? PRECOMPUTED_DEMO_RUN_ID;
  const [run, setRun] = useState<RunListItem | null>(null);

  useEffect(() => {
    if (!effectiveId) {
      return;
    }
    let cancelled = false;
    void fetch(`/api/runs/${effectiveId}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("run not found"))))
      .then((data: { run: RunListItem }) => {
        if (!cancelled) setRun(data.run);
      })
    return () => {
      cancelled = true;
    };
  }, [effectiveId]);

  if (!effectiveId) {
    return (
      <div className="p-5">
        <Panel>
          <EmptyState icon={<ImageIcon size={18} />} title="No precomputed image selected" action={<Button onClick={() => onNavigate("overview")}>Back to overview</Button>}>
            Choose the precomputed dataset pair from the Overview page to open its final photographic mosaic.
          </EmptyState>
        </Panel>
      </div>
    );
  }

  const output = (run?.output ?? { produced: true }) as { width?: number; height?: number; pixel_resolution_m?: number; geotiff_bytes?: number; cog_bytes?: number; produced?: boolean };

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col gap-4 bg-stone-100 p-5">
      <Panel className="overflow-hidden">
        <PanelHeader
          title="Final photographic mosaic"
          subtitle="Image-first view · no basemap, footprints, or map styling"
          icon={<ImageIcon size={14} />}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Button icon={<ArrowLeft size={13} />} onClick={() => onNavigate("overview")}>Overview</Button>
              <Button icon={<MapIcon size={13} />} onClick={() => onNavigate("map", effectiveId)}>Map layers</Button>
            </div>
          }
        />
        <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_300px]">
          <div className="h-[78vh] min-h-[420px] bg-white">
            <PhotoMap className="h-full w-full" />
          </div>
          <aside className="border-t border-stone-200 bg-stone-50 p-4 xl:border-l xl:border-t-0">
            <h2 className="text-sm font-semibold text-stone-900">Brighton Beach · 18 frames</h2>
            <p className="mt-1 text-2xs leading-relaxed text-stone-600">
              This view shows the generated RGB image directly. It does not add a third-party basemap or GIS overlays.
            </p>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <Stat label="Raster" value={output.width && output.height ? `${fmtNumber(output.width)} × ${fmtNumber(output.height)}` : null} hint="full output" />
              <Stat label="Pixel size" value={fmtCm(output.pixel_resolution_m)} hint="native GSD" />
              <Stat label="Input frames" value={run?.frames_ok ? String(run.frames_ok) : "18"} hint="accepted" />
              <Stat label="GeoTIFF" value={fmtBytes(output.geotiff_bytes)} hint="lossless raster" />
            </div>
            <div className="mt-5 space-y-2">
              <a className="flex items-center justify-between rounded-[3px] border border-stone-300 bg-white px-2.5 py-2 text-xs text-stone-700 hover:bg-stone-100" href={geotiffUrl(effectiveId)} download>
                <span>Download full GeoTIFF</span><Download size={13} />
              </a>
              <a className="flex items-center justify-between rounded-[3px] border border-stone-300 bg-white px-2.5 py-2 text-xs text-stone-700 hover:bg-stone-100" href={cogUrl(effectiveId)} download>
                <span>Download COG</span><Download size={13} />
              </a>
            </div>
          </aside>
        </div>
      </Panel>
    </div>
  );
}
