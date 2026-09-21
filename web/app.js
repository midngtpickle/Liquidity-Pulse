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

  // Render caching fingerprints to prevent DOM thrashing
  let _lastSRFingerprint = "";
  let _lastHeaderFingerprint = "";
  let _lastVPFingerprint = "";
  let _lastPoolsFingerprint = "";

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
      _lastSRFingerprint = ""; // force re-render on filter change
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
      renderPools();
      renderPositioning();
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
        renderBriefingAge(data.age_seconds);
      }
    } catch (err) {
      console.error("Briefing fetch error:", err);
    }
  }

  // The briefing only regenerates when sentinel.py runs or /api/refresh is posted,
  // while the panels around it refresh on their own. A stale one used to render
  // under a green "Updated Live" badge, so a ten-day-old BEARISH call sat directly
  // beneath a live BULLISH one. Say the age, and stop calling it live once the
  // telemetry beside it has moved on.
  const BRIEFING_STALE_AFTER_S = 15 * 60;

  function renderBriefingAge(ageSeconds) {
    const badge = document.getElementById("briefing-timestamp");
    if (!badge) return;

    if (ageSeconds === null || ageSeconds === undefined) {
      badge.innerText = "Never generated";
      badge.className = "badge badge-warn";
      badge.title = "Run sentinel.py, or hit Refresh Telemetry, to generate one.";
      return;
    }

    const stale = ageSeconds >= BRIEFING_STALE_AFTER_S;
    badge.innerText = stale ? `Stale — ${formatAge(ageSeconds)} old` : "Updated Live";
    badge.className = stale ? "badge badge-warn" : "badge badge-success";
    badge.title = stale
      ? "This briefing predates the live telemetry above it. Hit Refresh Telemetry to regenerate."
      : "";

    const container = document.getElementById("briefing-container");
    if (container) container.classList.toggle("briefing-stale", stale);
  }

  function formatAge(s) {
    if (s < 90) return `${Math.round(s)}s`;
    if (s < 5400) return `${Math.round(s / 60)}m`;
    if (s < 172800) return `${Math.round(s / 3600)}h`;
    return `${Math.round(s / 86400)}d`;
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

    const fingerprint = `${currentPrice}_${vpoc}_${high24h}_${low24h}_${vol24h}_${summary.high_conviction_count}_${telemetryData.order_flow?.cvd ?? "x"}`;
    if (fingerprint === _lastHeaderFingerprint) return;
    _lastHeaderFingerprint = fingerprint;

    // Name the instrument the numbers actually describe, rather than assuming it.
    const symbolEl = document.getElementById("header-symbol");
    if (symbolEl && telemetryData.market) symbolEl.innerText = telemetryData.market;

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

    renderOrderFlow(telemetryData.order_flow);

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

  // Taker flow. Binance reports per-kline taker-buy volume, so this is who crossed
  // the spread rather than an inference from candle shape. Absent on the Bybit
  // fallback, which is shown as "no data" and never as a balanced market.
  function renderOrderFlow(flow) {
    const valueEl = document.getElementById("stat-cvd");
    const subEl = document.getElementById("stat-cvd-sub");
    if (!valueEl || !subEl) return;

    if (!flow || !flow.available) {
      valueEl.innerText = "n/a";
      valueEl.className = "stat-value text-muted";
      subEl.innerText = "Venue supplies no taker data";
      return;
    }

    const cvd = flow.cvd || 0;
    valueEl.innerText = `${cvd > 0 ? "+" : ""}${cvd.toLocaleString(undefined, {maximumFractionDigits: 0})} BTC`;
    valueEl.className = `stat-value ${cvd > 0 ? "text-green" : (cvd < 0 ? "text-red" : "text-muted")}`;

    const d24 = flow.cvd_24h || 0;
    const div = flow.divergence || 0;
    // Divergence is signed CVD-minus-price movement, both scaled by their own recent
    // magnitude, so it reads as "flow is running ahead of / behind price".
    const divNote = Math.abs(div) < 1
      ? "flow tracking price"
      : (div > 0 ? "buying not lifting price" : "selling not pressing price");
    subEl.innerText = `24h ${d24 > 0 ? "+" : ""}${d24.toLocaleString(undefined, {maximumFractionDigits: 0})} BTC · ${divNote}`;
  }

  const QUADRANT = {
    NEW_LONGS: ["New longs", "price up on rising OI — fresh money joining"],
    SHORT_COVERING: ["Short covering", "price up on falling OI — positions closing, not opening"],
    NEW_SHORTS: ["New shorts", "price down on rising OI — fresh money selling"],
    LONG_UNWIND: ["Long unwind", "price down on falling OI — positions closing, not opening"]
  };

  function fmtCountdown(s) {
    if (!s || s < 0) return "—";
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  // Open interest, funding and crowd ratio. Deliberately carries a caveat the other
  // cards do not: the exchange caps OI and ratio history at 30 days, which is far too
  // little for the walk-forward benchmark, so unlike the level derivations these
  // numbers have never been tested. They describe; they do not predict.
  function renderPositioning() {
    const grid = document.getElementById("positioning-grid");
    const note = document.getElementById("positioning-note");
    if (!grid) return;

    const p = telemetryData?.positioning;
    if (!p || !p.available) {
      grid.innerHTML = `<div class="pos-empty text-muted">Positioning endpoints unavailable.</div>`;
      if (note) note.hidden = true;
      return;
    }

    const fr = p.funding_rate || 0;
    const ann = p.funding_annualised_pct || 0;
    // Funding sign says who pays whom, which is the readable part.
    const frClass = fr > 0 ? "text-red" : (fr < 0 ? "text-green" : "text-muted");
    const frWho = fr > 0 ? "longs pay shorts" : (fr < 0 ? "shorts pay longs" : "flat");

    const oiChange = p.oi_change_24h_pct || 0;
    const oiClass = oiChange > 0 ? "text-green" : (oiChange < 0 ? "text-red" : "text-muted");
    const oiBn = (p.open_interest_value_usd || 0) / 1e9;

    const ls = p.top_long_short_ratio || 0;
    const lsClass = ls > 1 ? "text-green" : (ls > 0 && ls < 1 ? "text-red" : "text-muted");

    const q = QUADRANT[p.oi_price_quadrant];

    grid.innerHTML = `
      <div class="pos-item">
        <div class="pos-label">Funding (8h)</div>
        <div class="pos-value ${frClass}">${(fr * 100).toFixed(4)}%</div>
        <div class="pos-sub">${ann.toFixed(1)}%/yr · ${frWho}</div>
      </div>
      <div class="pos-item">
        <div class="pos-label">Next funding</div>
        <div class="pos-value">${fmtCountdown(p.seconds_to_funding)}</div>
        <div class="pos-sub">settles every 8h</div>
      </div>
      <div class="pos-item">
        <div class="pos-label">Open interest</div>
        <div class="pos-value">$${oiBn.toFixed(2)}B</div>
        <div class="pos-sub ${oiClass}">${oiChange > 0 ? "+" : ""}${oiChange.toFixed(2)}% 24h</div>
      </div>
      <div class="pos-item">
        <div class="pos-label">Top traders L/S</div>
        <div class="pos-value ${lsClass}">${ls.toFixed(2)}</div>
        <div class="pos-sub">by position size</div>
      </div>
      ${q ? `<div class="pos-item pos-item-wide">
        <div class="pos-label">OI vs price, 24h</div>
        <div class="pos-value">${q[0]}</div>
        <div class="pos-sub">${q[1]}</div>
      </div>` : ""}
    `;

    if (note) {
      note.innerHTML = `<i class="fa-solid fa-circle-info"></i><span>Binance caps open interest and long/short history at <strong>${p.oi_history_days} days</strong> — too short for the walk-forward benchmark, so these are <strong>untested</strong>, unlike the S/R derivations. Funding <em>was</em> tested across 36 conditions and separated from its control in none of them. Read this card as description, not signal.</span>`;
      note.hidden = false;
    }
  }

  const POOL_LABEL = {
    UNTESTED_SWING: "Untested swing",
    EQUAL_HIGHS: "Equal highs",
    EQUAL_LOWS: "Equal lows",
    SESSION: "Session extreme"
  };

  function renderPools() {
    const body = document.getElementById("pools-tbody");
    const note = document.getElementById("pools-note");
    if (!body) return;

    const pools = telemetryData?.liquidity_pools || [];
    if (note) {
      // Said once, here, rather than left for the reader to assume. The benchmark
      // found these are reached more often than a displaced control and then
      // reverse LESS often -- so they are targets, not places to fade.
      note.innerHTML = pools.length
        ? `Prices with unfilled stop orders behind them. The benchmark finds price is drawn <strong>through</strong> these and keeps going — treat them as targets, not as support or resistance.`
        : `No untested pools in the current window.`;
    }

    const fingerprint = pools.map(p => `${p.price}_${p.kind}_${p.strength}_${p.distance_pct}`).join("|");
    if (fingerprint === _lastPoolsFingerprint) return;
    _lastPoolsFingerprint = fingerprint;

    body.innerHTML = pools.map(p => {
      const above = p.side === "ABOVE";
      const sideBadge = above
        ? `<span class="badge badge-resistance">Sell-side</span>`
        : `<span class="badge badge-support">Buy-side</span>`;
      const distClass = p.distance_pct > 0 ? "text-red" : "text-green";
      const stacked = p.strength > 1 ? `<strong>×${p.strength}</strong>` : "—";
      return `
        <tr>
          <td class="price-cell">$${p.price.toLocaleString(undefined, {minimumFractionDigits: 2})}</td>
          <td class="text-muted">${POOL_LABEL[p.kind] || p.kind}</td>
          <td>${sideBadge}</td>
          <td>${stacked}</td>
          <td class="${distClass}">${p.distance_pct > 0 ? "+" : ""}${p.distance_pct.toFixed(2)}%</td>
        </tr>`;
    }).join("");
  }

  function renderSRTable() {
    if (!telemetryData || !telemetryData.sr_levels) return;

    const tbody = document.getElementById("sr-table-body");
    let levels = telemetryData.sr_levels;

    if (currentFilter === "SUPPORT") levels = levels.filter(l => l.type === "SUPPORT");
    else if (currentFilter === "RESISTANCE") levels = levels.filter(l => l.type === "RESISTANCE");
    else if (currentFilter === "HIGH") levels = levels.filter(l => l.conviction === "HIGH");

    const fingerprint = `${currentFilter}_` + levels.map(l => `${l.price}_${l.touch_count}_${l.conviction}_${l.distance_pct}_${l.volume_confluence}`).join("|");
    if (fingerprint === _lastSRFingerprint) return;
    _lastSRFingerprint = fingerprint;

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

    let bins = vp.bins || [];
    if (bins.length === 0) {
      return;
    }

    const labels = bins.map(b => `$${b.price.toLocaleString()}`);
    const dataVals = bins.map(b => b.volume);
    const bgColors = bins.map(b => {
      if (b.tag === "VPOC" || Math.abs(b.price - vpoc) < 50) return "#ffd700"; // gold VPOC
      if (b.tag === "HVN" || Array.from(hvns).some(h => Math.abs(h - b.price) < 75)) return "#00f2fe"; // cyan HVN
      if (b.tag === "LVN" || Array.from(lvns).some(l => Math.abs(l - b.price) < 75)) return "#e040fb"; // magenta LVN
      return "rgba(255, 255, 255, 0.15)";
    });

    const fingerprint = `${vpoc}_` + dataVals.join(",");
    if (fingerprint === _lastVPFingerprint && vpChart) {
      return;
    }
    _lastVPFingerprint = fingerprint;

    if (vpChart) {
      vpChart.data.labels = labels;
      vpChart.data.datasets[0].data = dataVals;
      vpChart.data.datasets[0].backgroundColor = bgColors;
      vpChart.update("none");
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
        animation: { duration: 300 },
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
    const bandKeys = ["0.5%", "1.0%", "2.0%"];

    // Initialize band skeleton DOM elements if not already present
    if (!container.querySelector('[data-band="0.5%"]')) {
      container.innerHTML = bandKeys.map(key => `
        <div class="depth-band-item" data-band="${key}">
          <div class="band-header">
            <span>${key} Depth Band<span class="band-partial" hidden>partial</span></span>
            <span class="band-delta text-muted">Connecting...</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill bid-fill" style="width: 50%;"></div>
            <div class="progress-fill ask-fill" style="width: 50%;"></div>
          </div>
          <div class="band-footer">
            <span class="band-bid-info text-green"><i class="fa-solid fa-arrow-up"></i> Bids: $0.00M (50%)</span>
            <span class="band-ask-info text-red">Asks: $0.00M (50%) <i class="fa-solid fa-arrow-down"></i></span>
          </div>
        </div>
      `).join("");
    }

    if (!bandsData || Object.keys(bandsData).length === 0) return;

    // In-place update of existing DOM nodes for smooth CSS width transitions
    bandKeys.forEach(key => {
      const b = bandsData[key] || { bid_depth_usd: 0, ask_depth_usd: 0, imbalance_delta_pct: 0 };
      const itemEl = container.querySelector(`[data-band="${key}"]`);
      if (!itemEl) return;

      const bidUSD = (b.bid_depth_usd / 1_000_000).toFixed(2);
      const askUSD = (b.ask_depth_usd / 1_000_000).toFixed(2);
      const totalUSD = b.bid_depth_usd + b.ask_depth_usd;
      const bidPct = totalUSD > 0 ? Math.round((b.bid_depth_usd / totalUSD) * 100) : 50;
      const askPct = 100 - bidPct;

      const delta = b.imbalance_delta_pct;
      const deltaText = delta > 0 ? `+${delta.toFixed(1)}% (Bid Heavy)` : `${delta.toFixed(1)}% (Ask Heavy)`;
      const deltaClass = delta > 0 ? "text-green" : (delta < 0 ? "text-red" : "text-muted");

      // The REST snapshot only reaches so far from mid, and the diff stream
      // reports a resting level only once it changes. A band wider than that
      // reach is under-reported, so its delta is a floor rather than a
      // measurement — say so instead of rendering it like a solid number.
      const complete = depthData?.bands_complete?.[key];
      const isPartial = complete === false;

      const partialEl = itemEl.querySelector(".band-partial");
      if (partialEl) partialEl.hidden = !isPartial;
      itemEl.classList.toggle("band-incomplete", isPartial);

      const deltaEl = itemEl.querySelector(".band-delta");
      if (deltaEl) {
        // The depth sums are floors. The delta between them is not: it is a
        // difference of two independently under-reported sides, biased in an
        // unknown direction, and it drifts on its own for minutes after a seed as
        // the diff stream fills the book in. Measured against the span the book is
        // actually complete to, it disagreed even on sign about half the time.
        deltaEl.textContent = isPartial ? `${deltaText} — unreliable` : deltaText;
        deltaEl.className = `band-delta ${deltaClass}`;
        deltaEl.title = isPartial
          ? "Depths are floors across this band. Their delta is not — both sides are under-reported by unknown and unequal amounts, so treat the sign as unconfirmed and read the complete-span figure instead."
          : "";
      }

      const bidFill = itemEl.querySelector(".bid-fill");
      if (bidFill) bidFill.style.width = `${bidPct}%`;

      const askFill = itemEl.querySelector(".ask-fill");
      if (askFill) askFill.style.width = `${askPct}%`;

      const bidInfo = itemEl.querySelector(".band-bid-info");
      if (bidInfo) bidInfo.innerHTML = `<i class="fa-solid fa-arrow-up"></i> Bids: $${bidUSD}M (${bidPct}%)`;

      const askInfo = itemEl.querySelector(".band-ask-info");
      if (askInfo) askInfo.innerHTML = `Asks: $${askUSD}M (${askPct}%) <i class="fa-solid fa-arrow-down"></i>`;
    });

    renderCompleteSpan();
    renderDepthBookNote();
  }

  // One line stating how far the book is actually vouched for, shown only while
  // some band exceeds that reach.
  function renderDepthBookNote() {
    const noteEl = document.getElementById("depth-book-note");
    if (!noteEl) return;

    const book = depthData?.book;
    const complete = depthData?.bands_complete;
    const anyPartial = complete && Object.values(complete).some(v => v === false);

    if (!book || !anyPartial) {
      noteEl.hidden = true;
      return;
    }

    const reach = Math.min(book.complete_bid_span_pct ?? 0, book.complete_ask_span_pct ?? 0);
    const age = book.age_seconds ?? 0;
    // The note is a flex row of icon + text, so the text has to stay inside one
    // element. Inline tags left loose here become sibling flex items and the
    // sentence renders as columns.
    noteEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i><span>Snapshot vouches for the book to ±${reach.toFixed(2)}% of mid. Bands marked <span class="band-partial">partial</span> extend past that: their depths are floors, and their deltas are <strong>not</strong> — both sides are under-reported unequally, and they keep drifting as the stream fills the book in (seeded ${formatAge(age)} ago). Read the complete-span figure above them.</span>`;
    noteEl.hidden = false;
  }

  // The one depth number measured entirely inside the book's vouched-for reach, and
  // therefore the only one comparable against a reading taken at another time.
  function renderCompleteSpan() {
    const el = document.getElementById("depth-complete-span");
    if (!el) return;

    const cs = depthData?.complete_span;
    if (!cs || !cs.band_pct) {
      el.hidden = true;
      return;
    }

    const d = cs.imbalance_delta_pct;
    const cls = d > 0 ? "text-green" : (d < 0 ? "text-red" : "text-muted");
    const label = d > 0 ? "Bid Heavy" : (d < 0 ? "Ask Heavy" : "Balanced");
    const bid = (cs.bid_depth_usd / 1_000_000).toFixed(2);
    const ask = (cs.ask_depth_usd / 1_000_000).toFixed(2);

    el.innerHTML = `
      <div class="cs-label">Complete-book imbalance <span class="cs-width">±${cs.band_pct.toFixed(2)}% of mid</span></div>
      <div class="cs-value ${cls}">${d > 0 ? "+" : ""}${d.toFixed(1)}% <span class="cs-tag">${label}</span></div>
      <div class="cs-detail">Bids $${bid}M · Asks $${ask}M — both sides fully known across this span</div>
    `;
    el.hidden = false;
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
});
