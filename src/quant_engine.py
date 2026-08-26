"""
Liquidity-Pulse - Quantitative Telemetry Engine

Fetches 15m $BTC market data from public REST endpoints, calculates Pine Script-style
Pivot High/Low Support & Resistance clusters, volume profile metrics, and exports
structured telemetry to workspace/telemetry_latest.json.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import requests
from pydantic import BaseModel, Field

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("QuantEngine")

# In-memory TTL cache to prevent exchange REST API rate limits
_KLINE_CACHE: Dict[Tuple[str, str, int], Tuple[float, List[Dict[str, float]]]] = {}
CACHE_TTL_SECONDS: float = 30.0


# Data Schemas using Pydantic
class SRLevel(BaseModel):
    price: float = Field(..., description="Calculated center price of S/R cluster")
    type: str = Field(..., description="SUPPORT or RESISTANCE")
    touch_count: int = Field(..., description="Number of candle price range touches")
    conviction: str = Field(..., description="HIGH, MEDIUM, or LOW based on touches & volume")
    distance_pct: float = Field(..., description="Percentage offset from current mid-price")
    volume_confluence: bool = Field(..., description="True if level overlaps with high volume node")


class VolumeProfileBin(BaseModel):
    price: float = Field(..., description="Bin center price")
    volume: float = Field(..., description="Accumulated volume in this price bin")
    tag: str = Field(..., description="VPOC, HVN, LVN, or NORMAL")


class VolumeProfile(BaseModel):
    vpoc: float = Field(..., description="Volume Point of Control (highest volume price level)")
    hvn_zones: List[float] = Field(..., description="High Volume Nodes (top percentile volume bins)")
    lvn_zones: List[float] = Field(..., description="Low Volume Nodes (bottom percentile volume bins)")
    bins: List[VolumeProfileBin] = Field(default_factory=list, description="All histogram price bins")


class TelemetryPayload(BaseModel):
    timestamp: str
    symbol: str
    current_price: float
    high_24h: float
    low_24h: float
    volume_24h: float
    sr_levels: List[SRLevel]
    volume_profile: VolumeProfile
    market_summary: Dict[str, Any]


class QuantEngine:
    BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
    BYBIT_KLINES_URL = "https://api.bybit.com/v5/market/kline"

    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m", limit: int = 500):
        self.symbol = symbol
        self.interval = interval
        self.limit = limit

    def fetch_klines(self, use_cache: bool = True) -> List[Dict[str, float]]:
        """
        Fetches kline/candlestick data with fallback handling and in-memory TTL caching.
        """
        cache_key = (self.symbol, self.interval, self.limit)
        now = time.time()
        if use_cache and cache_key in _KLINE_CACHE:
            cached_time, cached_klines = _KLINE_CACHE[cache_key]
            if now - cached_time < CACHE_TTL_SECONDS:
                logger.info(f"Serving {len(cached_klines)} klines from in-memory cache (age: {now - cached_time:.1f}s).")
                return cached_klines

        headers = {"User-Agent": "LiquidityPulse/1.0"}
        
        # Primary: Binance REST
        try:
            logger.info(f"Fetching {self.limit} candles ({self.interval}) from Binance for {self.symbol}...")
            response = requests.get(
                self.BINANCE_KLINES_URL,
                params={"symbol": self.symbol, "interval": self.interval, "limit": self.limit},
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            klines = []
            for row in data:
                klines.append({
                    "open_time": float(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": float(row[6])
                })
            logger.info(f"Successfully fetched {len(klines)} klines from Binance.")
            _KLINE_CACHE[cache_key] = (now, klines)
            return klines
        except Exception as err:
            logger.warning(f"Binance fetch failed: {err}. Attempting Bybit fallback...")

        # Fallback: Bybit REST
        try:
            logger.info(f"Fetching klines from Bybit fallback...")
            interval_bybit = "15" if self.interval == "15m" else "60"
            response = requests.get(
                self.BYBIT_KLINES_URL,
                params={"category": "spot", "symbol": self.symbol, "interval": interval_bybit, "limit": self.limit},
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            res_json = response.json()
            list_data = res_json.get("result", {}).get("list", [])
            
            klines = []
            # Bybit returns reverse chronological order
            for row in reversed(list_data):
                klines.append({
                    "open_time": float(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": float(row[0]) + 900000.0
                })
            logger.info(f"Successfully fetched {len(klines)} klines from Bybit.")
            _KLINE_CACHE[cache_key] = (now, klines)
            return klines
        except Exception as err:
            logger.error(f"Bybit fallback failed: {err}")
            # If network fails completely and we have stale cache, serve stale cache as fallback
            if cache_key in _KLINE_CACHE:
                logger.warning("Serving stale cached klines due to network failure.")
                return _KLINE_CACHE[cache_key][1]
            raise RuntimeError(f"Failed to fetch market data from all REST endpoints: {err}")

    @staticmethod
    def _parse_binance_kline_row(row: List[Any]) -> Dict[str, float]:
        return {
            "open_time": float(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": float(row[6])
        }

    def fetch_klines_paginated(self, total: int) -> List[Dict[str, float]]:
        """
        Fetches more history than the exchange's 1000-candle per-request cap by
        walking endTime backwards.

        Production only ever needs the single trailing window fetch_klines() returns.
        This exists for the backtester, where a thousand candles is far too little
        history to conclude anything about hit rates. Deliberately no Bybit fallback
        and no caching: a benchmark should fail loudly rather than quietly splice two
        exchanges together or reuse a stale window.
        """
        headers = {"User-Agent": "LiquidityPulse/1.0"}
        collected: List[Dict[str, float]] = []
        end_time: Optional[int] = None
        page_cap = 1000

        while len(collected) < total:
            batch_size = min(page_cap, total - len(collected))
            params: Dict[str, Any] = {
                "symbol": self.symbol,
                "interval": self.interval,
                "limit": batch_size
            }
            if end_time is not None:
                params["endTime"] = end_time

            response = requests.get(
                self.BINANCE_KLINES_URL, params=params, headers=headers, timeout=15
            )
            response.raise_for_status()
            data = response.json()
            if not data:
                logger.warning(
                    f"No further history available; stopping at {len(collected)} candles."
                )
                break

            # Binance returns oldest -> newest, so each page prepends to the front.
            page = [self._parse_binance_kline_row(row) for row in data]
            collected = page + collected
            end_time = int(page[0]["open_time"]) - 1

            if len(data) < batch_size:
                logger.warning(
                    f"Exchange history exhausted at {len(collected)} candles."
                )
                break

        logger.info(
            f"Fetched {len(collected)} candles ({self.interval}) across paginated requests."
        )
        return collected

    def calculate_pine_pivots(
        self, klines: List[Dict[str, float]], left_bars: int = 10, right_bars: int = 10
    ) -> List[float]:
        """
        Calculates Pine Script-style Pivot High and Pivot Low points.
        """
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        n = len(klines)
        pivots = []

        for i in range(left_bars, n - right_bars):
            # Check Pivot High
            current_high = highs[i]
            is_pivot_high = all(current_high > highs[i - k] for k in range(1, left_bars + 1)) and \
                            all(current_high >= highs[i + k] for k in range(1, right_bars + 1))
            if is_pivot_high:
                pivots.append(current_high)

            # Check Pivot Low
            current_low = lows[i]
            is_pivot_low = all(current_low < lows[i - k] for k in range(1, left_bars + 1)) and \
                           all(current_low <= lows[i + k] for k in range(1, right_bars + 1))
            if is_pivot_low:
                pivots.append(current_low)

        logger.info(f"Identified {len(pivots)} raw Pine pivots.")
        return pivots

    @staticmethod
    def grade_conviction(touch_count: int, volume_confluence: bool) -> str:
        """
        Conviction tiers per CLAUDE.md: HIGH requires >= 3 distinct touches AND
        overlap with a High Volume Node or the VPOC. Touch count alone never
        reaches HIGH — a level price revisits often but that no volume has
        accepted is not an institutional level.
        """
        if touch_count >= 3 and volume_confluence:
            return "HIGH"
        if touch_count >= 2:
            return "MEDIUM"
        return "LOW"

    def apply_volume_confluence(
        self,
        sr_levels: List["SRLevel"],
        volume_prof: "VolumeProfile",
        reference_price: float
    ) -> None:
        """
        Tags each level with HVN/VPOC confluence and regrades conviction in place.

        Conviction cannot be finalised inside cluster_sr_levels() because the volume
        profile does not exist yet, so any caller wanting production-grade tiers must
        run this. Skipping it leaves every level capped at MEDIUM.
        """
        for level in sr_levels:
            near_vpoc = abs(level.price - volume_prof.vpoc) / reference_price <= 0.005
            near_hvn = any(
                abs(level.price - hvn) / reference_price <= 0.005
                for hvn in volume_prof.hvn_zones
            )
            level.volume_confluence = near_vpoc or near_hvn
            level.conviction = self.grade_conviction(level.touch_count, level.volume_confluence)

    def cluster_sr_levels(
        self,
        pivots: List[float],
        klines: List[Dict[str, float]],
        current_price: float,
        threshold_pct: float = 0.0035
    ) -> List[SRLevel]:
        """
        Clusters pivot points into density S/R zones, counts distinct touches across the
        full candle set, and assigns conviction tiers.
        """
        if not pivots:
            return []

        sorted_pivots = sorted(pivots)
        clusters: List[List[float]] = []

        for price in sorted_pivots:
            if not clusters:
                clusters.append([price])
            else:
                last_cluster = clusters[-1]
                cluster_mean = np.mean(last_cluster)
                if abs(price - cluster_mean) / cluster_mean <= threshold_pct:
                    last_cluster.append(price)
                else:
                    clusters.append([price])

        # Pre-compute numpy arrays for vectorized touch counting
        lows_arr = np.array([k["low"] for k in klines], dtype=np.float64)
        highs_arr = np.array([k["high"] for k in klines], dtype=np.float64)

        sr_levels: List[SRLevel] = []
        for cluster in clusters:
            level_price = round(float(np.mean(cluster)), 2)
            
            # Vectorized touch count across all klines. Only rising edges count —
            # a candle entering the zone from outside. Counting every candle whose
            # range overlaps the level instead measures how long price loitered
            # near it, which pushed every level past the HIGH threshold and made
            # the conviction tiers meaningless. Mirrors the debounce in
            # liquidity_pulse_sr.pine.
            tolerance = level_price * threshold_pct
            in_zone = (lows_arr <= (level_price + tolerance)) & (highs_arr >= (level_price - tolerance))
            entered_from_outside = np.empty_like(in_zone)
            entered_from_outside[0] = True
            entered_from_outside[1:] = ~in_zone[:-1]
            touch_count = int(np.count_nonzero(in_zone & entered_from_outside))

            level_type = "SUPPORT" if level_price < current_price else "RESISTANCE"
            distance_pct = round(((level_price - current_price) / current_price) * 100, 2)

            # Provisional grade. Volume confluence is unknown until the volume
            # profile is built, so run() regrades once it is.
            conviction = self.grade_conviction(touch_count, volume_confluence=False)

            sr_levels.append(SRLevel(
                price=level_price,
                type=level_type,
                touch_count=touch_count,
                conviction=conviction,
                distance_pct=distance_pct,
                volume_confluence=False  # updated later during volume profile calculation
            ))

        # Sort levels by proximity to current price
        sr_levels.sort(key=lambda x: abs(x.distance_pct))
        return sr_levels

    def calculate_volume_profile(
        self, klines: List[Dict[str, float]], num_bins: int = 50
    ) -> VolumeProfile:
        """
        Calculates Volume Point of Control (VPOC), High Volume Nodes (HVN), Low Volume Nodes (LVN),
        and price bin histogram for frontend charting.
        """
        prices = []
        volumes = []
        for k in klines:
            # Distribute volume across candle range (mid-price approximation)
            mid = (k["high"] + k["low"]) / 2.0
            prices.append(mid)
            volumes.append(k["volume"])

        hist, bin_edges = np.histogram(prices, bins=num_bins, weights=volumes)
        
        # VPOC: Bin with max volume
        max_idx = int(np.argmax(hist))
        vpoc = round(float((bin_edges[max_idx] + bin_edges[max_idx + 1]) / 2.0), 2)

        # HVN (top 20 percentile volume) & LVN (bottom 20 percentile volume)
        p80 = float(np.percentile(hist, 80))
        p20 = float(np.percentile(hist, 20))

        hvn_zones = []
        lvn_zones = []
        all_bins: List[VolumeProfileBin] = []

        for idx, vol in enumerate(hist):
            center_price = round(float((bin_edges[idx] + bin_edges[idx + 1]) / 2.0), 2)
            vol_val = round(float(vol), 2)
            tag = "NORMAL"

            if idx == max_idx:
                tag = "VPOC"
            elif vol >= p80:
                hvn_zones.append(center_price)
                tag = "HVN"
            elif vol <= p20 and vol > 0:
                lvn_zones.append(center_price)
                tag = "LVN"

            all_bins.append(VolumeProfileBin(
                price=center_price,
                volume=vol_val,
                tag=tag
            ))

        return VolumeProfile(
            vpoc=vpoc,
            hvn_zones=hvn_zones,
            lvn_zones=lvn_zones,
            bins=all_bins
        )

    def run(self, output_path: str = "workspace/telemetry_latest.json", use_cache: bool = True) -> TelemetryPayload:
        """
        Main execution workflow.
        """
        klines = self.fetch_klines(use_cache=use_cache)
        current_price = round(klines[-1]["close"], 2)
        high_24h = round(max(k["high"] for k in klines[-96:]), 2)
        low_24h = round(min(k["low"] for k in klines[-96:]), 2)
        volume_24h = round(sum(k["volume"] for k in klines[-96:]), 2)

        pivots = self.calculate_pine_pivots(klines)
        sr_levels = self.cluster_sr_levels(pivots, klines, current_price)
        volume_prof = self.calculate_volume_profile(klines)

        self.apply_volume_confluence(sr_levels, volume_prof, current_price)

        telemetry = TelemetryPayload(
            timestamp=datetime.now(timezone.utc).isoformat(),
            symbol=self.symbol,
            current_price=current_price,
            high_24h=high_24h,
            low_24h=low_24h,
            volume_24h=volume_24h,
            sr_levels=sr_levels[:12],  # Top 12 closest S/R levels
            volume_profile=volume_prof,
            market_summary={
                "total_candles_analyzed": len(klines),
                "pine_pivots_found": len(pivots),
                "support_levels_count": len([l for l in sr_levels if l.type == "SUPPORT"]),
                "resistance_levels_count": len([l for l in sr_levels if l.type == "RESISTANCE"]),
                "high_conviction_count": len([l for l in sr_levels if l.conviction == "HIGH"])
            }
        )

        # Ensure target directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(telemetry.model_dump(), f, indent=2)

        logger.info(f"Telemetry successfully written to {output_path}")
        return telemetry


if __name__ == "__main__":
    # Determine base workspace directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.abspath(os.path.join(script_dir, "..", "workspace"))
    output_file = os.path.join(workspace_dir, "telemetry_latest.json")

    engine = QuantEngine(symbol="BTCUSDT", interval="15m", limit=500)
    engine.run(output_path=output_file, use_cache=False)
