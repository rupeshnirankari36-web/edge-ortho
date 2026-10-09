// Edge-Ortho Interactive Leaflet Viewer

document.addEventListener("DOMContentLoaded", async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const manifestUrl = urlParams.get("manifest") || "../../outputs/manifest.json";

  // Base map layers
  const osmLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 22,
    attribution: "© OpenStreetMap contributors"
  });

  const satLayer = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 22,
    attribution: "Tiles © Esri"
  });

  const map = L.map("map", {
    center: [0, 0],
    zoom: 2,
    layers: [satLayer],
    zoomControl: true
  });

  L.control.layers({
    "Satellite Imagery": satLayer,
    "Street Map (OSM)": osmLayer
  }, null, { position: "topleft" }).addTo(map);

  let orthoLayer = null;
  let boundsLayer = null;

  try {
    const res = await fetch(manifestUrl);
    if (!res.ok) throw new Error(`Could not load manifest from ${manifestUrl}`);
    const manifest = await res.json();

    document.getElementById("dataset-title").textContent = manifest.name || "Orthomosaic";

    const [minLon, minLat, maxLon, maxLat] = manifest.bounds_wgs84;
    const centerLat = (minLat + maxLat) / 2;
    const centerLon = (minLon + maxLon) / 2;

    map.setView([centerLat, centerLon], 17);

    // Survey bounding rectangle
    const bounds = [[minLat, minLon], [maxLat, maxLon]];
    boundsLayer = L.rectangle(bounds, {
      color: "#38bdf8",
      weight: 2,
      fill: false,
      dashArray: "4, 6"
    }).addTo(map);

    map.fitBounds(bounds, { padding: [40, 40] });

    // XYZ Tile Layer
    if (manifest.tiles) {
      // Resolve relative path to tiles
      const basePath = manifestUrl.substring(0, manifestUrl.lastIndexOf("/") + 1);
      const tileUrl = basePath + manifest.tiles;

      orthoLayer = L.tileLayer(tileUrl, {
        minZoom: 10,
        maxNativeZoom: 21,
        maxZoom: 24,
        opacity: 1.0,
        tms: false
      }).addTo(map);
    }

    // Set download button
    if (manifest.geotiff) {
      const basePath = manifestUrl.substring(0, manifestUrl.lastIndexOf("/") + 1);
      const downloadBtn = document.getElementById("btn-download-geotiff");
      downloadBtn.href = basePath + manifest.geotiff;
    }

    // Load Telemetry Metrics
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
    console.warn("Manifest loading failed; fallback to demo view:", err);
  }

  // Opacity Slider Event
  const slider = document.getElementById("opacity-slider");
  const opacityVal = document.getElementById("opacity-val");
  slider.addEventListener("input", (e) => {
    const val = e.target.value;
    opacityVal.textContent = `${val}%`;
    if (orthoLayer) {
      orthoLayer.setOpacity(val / 100);
    }
  });

  // Toggle Bounds Event
  const toggleBounds = document.getElementById("toggle-bounds");
  toggleBounds.addEventListener("change", (e) => {
    if (boundsLayer) {
      if (e.target.checked) {
        map.addLayer(boundsLayer);
      } else {
        map.removeLayer(boundsLayer);
      }
    }
  });
});
