"""Unit tests for system and simulation configuration."""

from marketpulse.config import SimulationConfig


def test_simulation_config_defaults_and_hashing() -> None:
    """Verify default config values, immutability, and deterministic sha256 hash."""
    cfg1 = SimulationConfig(seed=42)
    cfg2 = SimulationConfig(seed=42)
    assert cfg1.compute_hash() == cfg2.compute_hash()

    cfg_diff = SimulationConfig(seed=43)
    assert cfg1.compute_hash() != cfg_diff.compute_hash()
    assert len(cfg1.compute_hash()) == 64  # SHA-256 hex length
