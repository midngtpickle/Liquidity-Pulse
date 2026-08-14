/**
 * Liquidity-Pulse — Dashboard Frontend Logic
 */

document.addEventListener("DOMContentLoaded", () => {
  let telemetryData = null;
  let depthData = null;
  let currentFilter = "all";
  let vpChart = null;
  let telemetryTimer = null;
  let briefingTimer = null;
  let depthTimer = null;

  const btnRefresh = document.getElementById("btn-refresh");
  const filterBtns = document.querySelectorAll(".filter-btn");

  // Initial Fetch & Start Polling
  fetchAllData();
  startPolling();

  // Page Visibility API to optimize client CPU and backend network load
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPolling();
    } else {
      fetchAllData();
      startPolling();
    }
  });

  // Event Listeners
  btnRefresh.addEventListener("click", triggerManualRefresh);
  filterBtns.forEach(btn => {
    btn.addEventListener("click", (e) => {
      filterBtns.forEach(b => b.classList.remove("active"));
      e.target.classList.add("active");
      currentFilter = e.target.getAttribute("data-filter");
      renderSRTable();
    });
  });

  function startPolling() {
    stopPolling();
    telemetryTimer = setInterval(fetchTelemetry, 5000);
    depthTimer = setInterval(fetchDepth, 2000);
    briefingTimer = setInterval(fetchBriefing, 15000);
  }

  function stopPolling() {
    if (telemetryTimer) clearInterval(telemetryTimer);
    if (depthTimer) clearInterval(depthTimer);
    if (briefingTimer) clearInterval(briefingTimer);
  }

  function fetchAllData() {
    fetchTelemetry();
    fetchDepth();
    fetchBriefing();
  }

  async function fetchTelemetry() {
    try {
      const res = await fetch("/api/telemetry");
      if (!res.ok) throw new Error("Failed to fetch telemetry");
      telemetryData = await res.json();
      renderHeaderAndStats();
      renderSRTable();
      renderVolumeProfileChart();
    } catch (err) {
      console.error("Telemetry fetch error:", err);
    }
  }

  async function fetchDepth() {
    try {
      const res = await fetch("/api/depth");
      if (!res.ok) return;
      depthData = await res.json();
      renderDepthDelta();
    } catch (err) {
      console.debug("Depth fetch error:", err);
    }
  }

  async function fetchBriefing() {
    try {
      const res = await fetch("/api/briefing");
      if (!res.ok) throw new Error("Failed to fetch briefing");
      const data = await res.json();
      const briefingContainer = document.getElementById("briefing-container");
      
      if (data.content && typeof marked !== "undefined") {
        const rawHtml = marked.parse(data.content);
        // DOMPurify sanitization against XSS attacks
        const cleanHtml = typeof DOMPurify !== "undefined" ? DOMPurify.sanitize(rawHtml) : rawHtml;
        briefingContainer.innerHTML = cleanHtml;
        document.getElementById("briefing-timestamp").innerText = "Updated Live";
      }
    } catch (err) {
      console.error("Briefing fetch error:", err);
    }
  }

  async function triggerManualRefresh() {
    btnRefresh.disabled = true;
    btnRefresh.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Refreshing...`;
    try {
      const res = await fetch("/api/refresh", { method: "POST" });
      const data = await res.json();
      showToast(data.message || "Refresh initiated!", res.status === 429 ? "error" : "success");
      // Wait slightly and fetch new data
      setTimeout(fetchAllData, 1500);
    } catch (err) {
      showToast("Error triggering refresh: " + err.message, "error");
    } finally {
      setTimeout(() => {
        btnRefresh.disabled = false;
        btnRefresh.innerHTML = `<i class="fa-solid fa-rotate-right"></i> Refresh Telemetry`;
      }, 2000);
    }
  }

  function renderHeaderAndStats() {
    if (!telemetryData) return;

    const currentPrice = telemetryData.current_price || 0;
    const vpoc = telemetryData.volume_profile?.vpoc || 0;
    const high24h = telemetryData.high_24h || 0;
    const low24h = telemetryData.low_24h || 0;
    const vol24h = telemetryData.volume_24h || 0;
    const summary = telemetryData.market_summary || {};

    document.getElementById("header-price").innerText = `$${currentPrice.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
    document.getElementById("stat-24h-range").innerText = `$${low24h.toLocaleString()} - $${high24h.toLocaleString()}`;
    document.getElementById("stat-24h-vol").innerText = `24h Vol: ${vol24h.toLocaleString(undefined, {maximumFractionDigits: 1})} BTC`;
    document.getElementById("stat-vpoc").innerText = `$${vpoc.toLocaleString(undefined, {minimumFractionDigits: 2})}`;
    document.getElementById("stat-high-conviction").innerText = summary.high_conviction_count || 0;

    // Session determination
    const nowUtcHour = new Date().getUTCHours() + (new Date().getUTCMinutes() / 60.0);
    let sessionName = "NY CLOSE (21:00 UTC)";
    if (nowUtcHour >= 0 && nowUtcHour < 7) sessionName = "ASIA (00:00 UTC Open)";
    else if (nowUtcHour >= 7 && nowUtcHour < 13.5) sessionName = "LONDON (07:00 UTC Open)";
    else if (nowUtcHour >= 13.5 && nowUtcHour < 21) sessionName = "NEW YORK (13:30 UTC Open)";

    document.getElementById("header-session").innerText = sessionName;

    // Market Bias
    const biasElem = document.getElementById("stat-bias");
    if (currentPrice > vpoc) {
      biasElem.innerText = "BULLISH";
      biasElem.className = "stat-value text-green";
    } else {
      biasElem.innerText = "BEARISH";
      biasElem.className = "stat-value text-red";
    }
  }

  function renderSRTable() {
    if (!telemetryData || !telemetryData.sr_levels) return;

    const tbody = document.getElementById("sr-table-body");
    let levels = telemetryData.sr_levels;

    if (currentFilter === "SUPPORT") levels = levels.filter(l => l.type === "SUPPORT");
    else if (currentFilter === "RESISTANCE") levels = levels.filter(l => l.type === "RESISTANCE");
    else if (currentFilter === "HIGH") levels = levels.filter(l => l.conviction === "HIGH");

    if (levels.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted pad-20">No levels match filter criteria.</td></tr>`;
      return;
    }

    tbody.innerHTML = levels.map(l => {
      const typeBadge = l.type === "SUPPORT" ? `<span class="badge badge-support">SUPPORT</span>` : `<span class="badge badge-resistance">RESISTANCE</span>`;
      const convBadge = l.conviction === "HIGH" ? `<span class="badge badge-high">🔥 HIGH</span>` : (l.conviction === "MEDIUM" ? `<span class="badge badge-med">⚡ MED</span>` : `<span class="badge badge-low">MINOR</span>`);
      const volTag = l.volume_confluence ? `<span class="text-green"><i class="fa-solid fa-check"></i> VPOC/HVN</span>` : `<span class="text-muted">---</span>`;
      const distColor = l.distance_pct < 0 ? "text-green" : "text-red";

      return `
        <tr>
          <td><strong>$${l.price.toLocaleString(undefined, {minimumFractionDigits: 2})}</strong></td>
          <td>${typeBadge}</td>
          <td>${convBadge}</td>
          <td>${l.touch_count} touches</td>
          <td class="${distColor}">${l.distance_pct > 0 ? "+" : ""}${l.distance_pct.toFixed(2)}%</td>
          <td>${volTag}</td>
        </tr>
      `;
    }).join("");
  }

  function renderVolumeProfileChart() {
    if (!telemetryData || !telemetryData.volume_profile) return;

    const canvas = document.getElementById("volumeProfileChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const vp = telemetryData.volume_profile;
    const vpoc = vp.vpoc;
    const hvns = new Set(vp.hvn_zones || []);
    const lvns = new Set(vp.lvn_zones || []);

    let bins = vp.bins;
    // If backend provided structured bins, sample them for charting
    if (bins && bins.length > 0) {
      // Pick representative sample (e.g. 20 bins)
      const step = Math.max(1, Math.floor(bins.length / 20));
      bins = bins.filter((_, idx) => idx % step === 0);
    } else {
      // Fallback: construct bins around key levels
      const basePrice = vpoc - 1000;
      bins = [];
      for (let i = 0; i < 15; i++) {
        const binPrice = roundVal(basePrice + i * 150, 2);
        let vol = 250;
        let tag = "NORMAL";
        if (Math.abs(binPrice - vpoc) < 100) { vol = 1000; tag = "VPOC"; }
        else if (Array.from(hvns).some(h => Math.abs(h - binPrice) < 100)) { vol = 700; tag = "HVN"; }
        else if (Array.from(lvns).some(l => Math.abs(l - binPrice) < 100)) { vol = 80; tag = "LVN"; }
        bins.push({ price: binPrice, volume: vol, tag });
      }
    }

    const labels = bins.map(b => `$${b.price.toLocaleString()}`);
    const dataVals = bins.map(b => b.volume);
    const bgColors = bins.map(b => {
      if (b.tag === "VPOC" || Math.abs(b.price - vpoc) < 50) return "#ffd700"; // gold VPOC
      if (b.tag === "HVN" || Array.from(hvns).some(h => Math.abs(h - b.price) < 75)) return "#00f2fe"; // cyan HVN
      if (b.tag === "LVN" || Array.from(lvns).some(l => Math.abs(l - b.price) < 75)) return "#e040fb"; // magenta LVN
      return "rgba(255, 255, 255, 0.15)";
    });

    if (vpChart) {
      vpChart.data.labels = labels;
      vpChart.data.datasets[0].data = dataVals;
      vpChart.data.datasets[0].backgroundColor = bgColors;
      vpChart.update();
      return;
    }

    vpChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [{
          label: "Volume Profile",
          data: dataVals,
          backgroundColor: bgColors,
          borderRadius: 4
        }]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false }
        },
        scales: {
          x: {
            grid: { color: "rgba(255, 255, 255, 0.05)" },
            ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } }
          },
          y: {
            grid: { display: false },
            ticks: { color: "#94a3b8", font: { family: "JetBrains Mono" } }
          }
        }
      }
    });
  }

  function renderDepthDelta() {
    const container = document.getElementById("depth-bands-container");
    if (!container) return;

    const bandsData = depthData?.bands;
    if (!bandsData || Object.keys(bandsData).length === 0) {
      container.innerHTML = `
        <div class="depth-band-item">
          <div class="band-header">
            <span>Orderbook Stream</span>
            <span class="band-delta text-muted">Awaiting stream packets...</span>
          </div>
        </div>
      `;
      return;
    }

    const bandKeys = ["0.5%", "1.0%", "2.0%"];
    container.innerHTML = bandKeys.map(key => {
      const b = bandsData[key] || { bid_depth_usd: 0, ask_depth_usd: 0, imbalance_delta_pct: 0 };
      const bidUSD = (b.bid_depth_usd / 1_000_000).toFixed(2);
      const askUSD = (b.ask_depth_usd / 1_000_000).toFixed(2);
      const totalUSD = b.bid_depth_usd + b.ask_depth_usd;
      const bidPct = totalUSD > 0 ? Math.round((b.bid_depth_usd / totalUSD) * 100) : 50;
      const askPct = 100 - bidPct;

      const delta = b.imbalance_delta_pct;
      const deltaText = delta > 0 ? `+${delta.toFixed(1)}% (Bid Heavy)` : `${delta.toFixed(1)}% (Ask Heavy)`;
      const deltaClass = delta > 0 ? "text-green" : (delta < 0 ? "text-red" : "text-muted");

      return `
        <div class="depth-band-item">
          <div class="band-header">
            <span>${key} Depth Band</span>
            <span class="band-delta ${deltaClass}">${deltaText}</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill bid-fill" style="width: ${bidPct}%;"></div>
            <div class="progress-fill ask-fill" style="width: ${askPct}%;"></div>
          </div>
          <div class="band-footer">
            <span class="text-green"><i class="fa-solid fa-arrow-up"></i> Bids: $${bidUSD}M (${bidPct}%)</span>
            <span class="text-red">Asks: $${askUSD}M (${askPct}%) <i class="fa-solid fa-arrow-down"></i></span>
          </div>
        </div>
      `;
    }).join("");
  }

  function showToast(msg, type = "success") {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.style.cssText = `
      background: rgba(15, 23, 42, 0.95);
      border-left: 4px solid ${type === "success" ? "#00e676" : "#ff1744"};
      color: #fff;
      padding: 12px 18px;
      border-radius: 8px;
      margin-top: 10px;
      font-size: 13px;
      box-shadow: 0 4px 14px rgba(0,0,0,0.4);
      animation: fadeIn 0.3s ease;
    `;
    toast.innerText = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
  }

  function roundVal(val, decimals = 2) {
    return Number(Math.round(val + "e" + decimals) + "e-" + decimals);
  }
});
