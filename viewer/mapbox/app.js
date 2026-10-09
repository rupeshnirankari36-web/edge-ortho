// Edge-Ortho Mapbox GL / MapLibre WebGL Viewer

document.addEventListener("DOMContentLoaded", async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const manifestUrl = urlParams.get("manifest") || "../../outputs/manifest.json";

  const map = new maplibregl.Map({
    container: "map",
    style: {
      version: 8,
      sources: {
        "osm": {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          attribution: "© OpenStreetMap contributors"
        }
      },
      layers: [
        {
          id: "osm-layer",
          type: "raster",
          source: "osm"
        }
      ]
    },
    center: [0, 0],
    zoom: 2,
    pitch: 25,
    bearing: 0
  });

  map.addControl(new maplibregl.NavigationControl(), "top-left");

  map.on("load", async () => {
    try {
      const res = await fetch(manifestUrl);
      if (!res.ok) throw new Error(`Could not load manifest from ${manifestUrl}`);
      const manifest = await res.json();

      document.getElementById("dataset-title").textContent = manifest.name || "Orthomosaic";

      const [minLon, minLat, maxLon, maxLat] = manifest.bounds_wgs84;
      const centerLat = (minLat + maxLat) / 2;
      const centerLon = (minLon + maxLon) / 2;

      map.flyTo({
        center: [centerLon, centerLat],
        zoom: 17,
        essential: true
      });

      if (manifest.tiles) {
        const basePath = manifestUrl.substring(0, manifestUrl.lastIndexOf("/") + 1);
        const tileUrl = new URL(basePath + manifest.tiles, window.location.href).href;

        map.addSource("ortho-source", {
          type: "raster",
          tiles: [tileUrl],
          tileSize: 256,
          bounds: [minLon, minLat, maxLon, maxLat]
        });

        map.addLayer({
          id: "ortho-layer",
          type: "raster",
          source: "ortho-source",
          paint: {
            "raster-opacity": 1.0
          }
        });
      }

      // Load Metrics
      if (manifest.metrics) {
        const basePath = manifestUrl.substring(0, manifestUrl.lastIndexOf("/") + 1);
        try {
          const mRes = await fetch(basePath + manifest.metrics);
          if (mRes.ok) {
            const metrics = await mRes.json();
            document.getElementById("stat-ram").textContent = `${metrics.peak_rss_ram_mb.toFixed(1)} MB`;
            document.getElementById("stat-latency").textContent = `${metrics.total_latency_seconds.toFixed(1)} s`;
            document.getElementById("stat-gsd").textContent = `${(manifest.gsd_m * 100).toFixed(1)} cm/px`;
            document.getElementById("stat-bandwidth").textContent = `${metrics.bandwidth_reduction_factor.toFixed(1)}x`;
          }
        } catch (err) {
          console.warn("Metrics load error:", err);
        }
      }
    } catch (err) {
      console.warn("Manifest loading error:", err);
    }
  });

  // Opacity Slider Event
  const slider = document.getElementById("opacity-slider");
  const opacityVal = document.getElementById("opacity-val");
  slider.addEventListener("input", (e) => {
    const val = e.target.value;
    opacityVal.textContent = `${val}%`;
    if (map.getLayer("ortho-layer")) {
      map.setPaintProperty("ortho-layer", "raster-opacity", val / 100);
    }
  });

  // Toggle Pitch Event
  const togglePitch = document.getElementById("toggle-pitch");
  togglePitch.addEventListener("change", (e) => {
    map.easeTo({
      pitch: e.target.checked ? 45 : 0,
      duration: 500
    });
  });
});
