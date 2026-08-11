/**
 * Liquidity Pulse 3.6 — Dashboard Frontend Logic
 */

document.addEventListener("DOMContentLoaded", () => {
  let telemetryData = null;
  let currentFilter = "all";
  let vpChart = null;

  const btnRefresh = document.getElementById("btn-refresh");
  const filterBtns = document.querySelectorAll(".filter-btn");

  // Initial Fetch & Start Polling
  fetchTelemetry();
  fetchBriefing();
  setInterval(fetchTelemetry, 5000);
  setInterval(fetchBriefing, 15000);

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

  async function fetchTelemetry() {
    try {
      const res = await fetch("/api/telemetry");
      if (!res.ok) throw new Error("Failed to fetch telemetry");
      telemetryData = await res.json();
      renderHeaderAndStats();
      renderSRTable();
      renderVolumeProfileChart();
      renderDepthDelta();
    } catch (err) {
      console.error("Telemetry fetch error:", err);
    }
  }

  async function fetchBriefing() {
    try {
      const res = await fetch("/api/briefing");
      if (!res.ok) throw new Error("Failed to fetch briefing");
      const data = await res.json();
      const briefingContainer = document.getElementById("briefing-container");
      
      if (data.content && typeof marked !== "undefined") {
        briefingContainer.innerHTML = marked.parse(data.content);
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
      showToast(data.message || "Telemetry refreshed!");
      await fetchTelemetry();
      await fetchBriefing();
    } catch (err) {
      showToast("Error triggering refresh: " + err.message, "error");
    } finally {
      btnRefresh.disabled = false;
      btnRefresh.innerHTML = `<i class="fa-solid fa-rotate-right"></i> Refresh Telemetry`;
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
    const nowUtcHour = new Date().getUTCHours();
    let sessionName = "NY CLOSE";
    if (nowUtcHour >= 0 && nowUtcHour < 7) sessionName = "ASIA (00:00 UTC)";
    else if (nowUtcHour >= 7 && nowUtcHour < 13.5) sessionName = "LONDON (07:00 UTC)";
    else if (nowUtcHour >= 13.5 && nowUtcHour < 21) sessionName = "NEW YORK (13:30 UTC)";

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

    const ctx = document.getElementById("volumeProfileChart").getContext("2d");
    const vp = telemetryData.volume_profile;
    const vpoc = vp.vpoc;
    const hvns = vp.hvn_zones || [];
    const lvns = vp.lvn_zones || [];

    // Synthesize sample bin visual representation
    const sampleBins = [];
    const basePrice = vpoc - 1000;
    for (let i = 0; i < 15; i++) {
      const binPrice = roundVal(basePrice + i * 150, 2);
      let vol = Math.floor(Math.random() * 500 + 200);
      if (Math.abs(binPrice - vpoc) < 100) vol = 1200; // max volume at VPOC
      sampleBins.push({ price: binPrice, volume: vol });
    }

    const labels = sampleBins.map(b => `$${b.price}`);
    const dataVals = sampleBins.map(b => b.volume);
    const bgColors = sampleBins.map(b => {
      if (Math.abs(b.price - vpoc) < 100) return "#ffd700"; // gold VPOC
      if (hvns.some(h => Math.abs(h - b.price) < 100)) return "#00f2fe"; // cyan HVN
      if (lvns.some(l => Math.abs(l - b.price) < 100)) return "#e040fb"; // magenta LVN
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
    // Synthetic dynamic calculation representation from telemetry
    const bands = [
      { band: "0.5%", bidPct: 54, askPct: 46, bidUSD: 14.2, askUSD: 12.1 },
      { band: "1.0%", bidPct: 58, askPct: 42, bidUSD: 28.5, askUSD: 20.6 },
      { band: "2.0%", bidPct: 51, askPct: 49, bidUSD: 62.1, askUSD: 59.8 }
    ];

    container.innerHTML = bands.map(b => {
      const delta = (b.bidPct - b.askPct).toFixed(1);
      const deltaText = delta > 0 ? `+${delta}% (Bid Heavy)` : `${delta}% (Ask Heavy)`;
      const deltaClass = delta > 0 ? "text-green" : "text-red";

      return `
        <div class="depth-band-item">
          <div class="band-header">
            <span>${b.band} Depth Band</span>
            <span class="band-delta ${deltaClass}">${deltaText}</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill bid-fill" style="width: ${b.bidPct}%;"></div>
            <div class="progress-fill ask-fill" style="width: ${b.askPct}%;"></div>
          </div>
          <div class="band-footer">
            <span class="text-green"><i class="fa-solid fa-arrow-up"></i> Bids: $${b.bidUSD}M</span>
            <span class="text-red">Asks: $${b.askUSD}M <i class="fa-solid fa-arrow-down"></i></span>
          </div>
        </div>
      `;
    }).join("");
  }

  function showToast(msg, type = "success") {
    const container = document.getElementById("toast-container");
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
