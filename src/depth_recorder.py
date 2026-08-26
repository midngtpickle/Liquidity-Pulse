"""
Liquidity-Pulse - Order Book Depth Recorder

Appends a continuous history of order book state to gzipped JSONL, one file per UTC day.

Exchanges do not serve historical order books, so the imbalance signal cannot be
backtested from data you can fetch later. It can only be tested against data you started
recording beforehand. This module exists so that recording starts now rather than after
the question becomes urgent.

Two tiers are written:

  depth    - derived band metrics, once per second. Small, and the series analysis
             actually runs over. ~13MB/day raw, 2-3MB gzipped.
  book     - top-N levels per side, once per minute. Insurance: derived-only logging
             locks you into the band widths and features you thought of on day one, and
             a book snapshot lets any of them be recomputed later. ~6MB/day.
  gap      - an explicit marker whenever continuity breaks.

Gap markers matter more than they look. A recorder that silently stitches across a
reconnect produces a series that appears continuous and is not, and nothing downstream
can tell. Every reseed, reconnect, start and stop is recorded.
"""

import gzip
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("DepthRecorder")


class DepthRecorder:
    # Wider than the dashboard's three bands. Recording is cheap; regret is not.
    BANDS: List[float] = [0.001, 0.0025, 0.005, 0.01, 0.02]

    def __init__(
        self,
        directory: Path,
        derived_interval: float = 1.0,
        snapshot_interval: float = 60.0,
        snapshot_levels: int = 500
    ):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.derived_interval = derived_interval
        self.snapshot_interval = snapshot_interval
        self.snapshot_levels = snapshot_levels

        self._handle: Optional[gzip.GzipFile] = None
        self._handle_date: Optional[str] = None
        self._last_derived: float = 0.0
        self._last_snapshot: float = 0.0
        self._records_written: int = 0

    # ------------------------------------------------------------------ files

    @staticmethod
    def _date_key(now: float) -> str:
        return datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")

    def _writer(self, now: float) -> Optional[gzip.GzipFile]:
        """Returns today's handle, rotating at the UTC day boundary."""
        date_key = self._date_key(now)
        if self._handle is not None and self._handle_date == date_key:
            return self._handle

        self._close_handle()
        path = self.directory / f"depth_{date_key}.jsonl.gz"
        try:
            # Append mode, so a restart mid-day extends the file rather than truncating it.
            self._handle = gzip.open(path, "at", encoding="utf-8")
            self._handle_date = date_key
            logger.info(f"Recording depth history to {path}")
        except Exception as err:
            logger.error(f"Could not open depth history file {path}: {err}")
            self._handle = None
            self._handle_date = None
        return self._handle

    def _close_handle(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            except Exception:
                pass
        self._handle = None
        self._handle_date = None

    def _write(self, record: Dict[str, Any], now: float) -> None:
        handle = self._writer(now)
        if handle is None:
            return
        try:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._records_written += 1
            # Cheap insurance against losing the tail of the file on an unclean exit.
            if self._records_written % 60 == 0:
                handle.flush()
        except Exception as err:
            logger.error(f"Depth history write failed: {err}")
            self._close_handle()

    # ---------------------------------------------------------------- records

    def mark_gap(self, reason: str, detail: Optional[str] = None) -> None:
        """
        Records a break in continuity. Analysis must treat a gap as a boundary, not
        interpolate across it.
        """
        now = time.time()
        record = {"t": round(now, 3), "type": "gap", "reason": reason}
        if detail:
            record["detail"] = detail
        self._write(record, now)
        logger.info(f"Depth history gap marked: {reason}")

    def _band_metrics(self, book, mid_price: float) -> Dict[str, Dict[str, float]]:
        """Single pass per side across every band, as in ws_feed.calculate_depth_delta."""
        floors = [mid_price * (1.0 - b) for b in self.BANDS]
        ceilings = [mid_price * (1.0 + b) for b in self.BANDS]
        bid_totals = [0.0] * len(self.BANDS)
        ask_totals = [0.0] * len(self.BANDS)

        for price, qty in book.bids.items():
            notional = price * qty
            for i, floor in enumerate(floors):
                if price >= floor:
                    bid_totals[i] += notional

        for price, qty in book.asks.items():
            notional = price * qty
            for i, ceiling in enumerate(ceilings):
                if price <= ceiling:
                    ask_totals[i] += notional

        return {
            f"{band * 100:g}%": {"b": round(bid_totals[i], 2), "a": round(ask_totals[i], 2)}
            for i, band in enumerate(self.BANDS)
        }

    def _snapshot(self, book, limit: int) -> Dict[str, List[List[float]]]:
        bids = sorted(book.bids.items(), key=lambda kv: kv[0], reverse=True)[:limit]
        asks = sorted(book.asks.items(), key=lambda kv: kv[0])[:limit]
        return {
            "bids": [[round(p, 2), q] for p, q in bids],
            "asks": [[round(p, 2), q] for p, q in asks]
        }

    def record(self, book, now: Optional[float] = None) -> None:
        """
        Called on every applied diff event. Writes at most one derived record per
        `derived_interval` and one book snapshot per `snapshot_interval`.
        """
        if not book.synced or not book.bids or not book.asks:
            return

        now = now if now is not None else time.time()
        due_derived = now - self._last_derived >= self.derived_interval
        due_snapshot = now - self._last_snapshot >= self.snapshot_interval
        if not (due_derived or due_snapshot):
            return

        best_bid = max(book.bids)
        best_ask = min(book.asks)
        mid_price = (best_bid + best_ask) / 2.0

        if due_derived:
            self._last_derived = now
            self._write({
                "t": round(now, 3),
                "type": "depth",
                "mid": round(mid_price, 2),
                "spread": round(best_ask - best_bid, 2),
                "uid": book.last_update_id,
                "bands": self._band_metrics(book, mid_price),
                # The reach the book is complete to. Bands wider than this are floors,
                # not measurements, and analysis needs to know which is which.
                "span": {
                    "bid": round(book.complete_bid_span_pct, 3),
                    "ask": round(book.complete_ask_span_pct, 3)
                }
            }, now)

        if due_snapshot:
            self._last_snapshot = now
            record = {
                "t": round(now, 3),
                "type": "book",
                "mid": round(mid_price, 2),
                "uid": book.last_update_id
            }
            record.update(self._snapshot(book, self.snapshot_levels))
            self._write(record, now)

    def close(self) -> None:
        self.mark_gap("stop")
        if self._handle is not None:
            try:
                self._handle.flush()
            except Exception:
                pass
        self._close_handle()
