"""Typed system and simulation configuration for MarketPulse."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(slots=True, frozen=True)
class SimulationConfig:
    """Immutable simulation configuration with reproducible hashing."""

    session_id: str = "default_session"
    seed: int = 42
    symbols: tuple[str, ...] = ("AAPL",)
    tick_size: float = 0.01
    default_interval_ns: int = 1_000_000  # 1 millisecond
    throttling_fps: int = 20  # Broadcast throttling (updates/sec)

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 hash of configuration parameters."""
        data = asdict(self)
        # Sort keys and tuple representations for stable hashing
        serialized = json.dumps(data, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
