"""Scenario definitions, exogenous market event generators, and scenario metadata.

Provides educational stress-test scenarios for MarketPulse:
- Earnings Shock
- Flash Crash & Circuit Breaker
- Volatility Regime Shift
- Liquidity Dry-Up
- Trading Halt & Resume
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from marketpulse.core.events import MarketEvent


@dataclass(slots=True, frozen=True)
class ScenarioDefinition:
    """Metadata describing an educational market stress-test scenario."""

    id: str
    name: str
    description: str
    category: str
    default_params: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SCENARIO_CATALOG: list[ScenarioDefinition] = [
    ScenarioDefinition(
        id="earnings_shock_positive",
        name="Earnings Surprise (+5%)",
        description=(
            "Company beats earnings expectations. Asset valuation jumps 5% "
            "with temporary volatility spike and high volume."
        ),
        category="Valuation Shock",
        default_params={"jump_pct": 0.05, "volatility_mult": 2.5},
    ),
    ScenarioDefinition(
        id="earnings_shock_negative",
        name="Earnings Miss (-5%)",
        description=(
            "Company misses revenue expectations. Asset valuation drops 5% "
            "with aggressive selling and wider spreads."
        ),
        category="Valuation Shock",
        default_params={"jump_pct": -0.05, "volatility_mult": 2.5},
    ),
    ScenarioDefinition(
        id="flash_crash",
        name="Flash Crash & Circuit Breaker",
        description=(
            "Sudden cascade of massive sell volume triggers a rapid 10% drop, "
            "activating the regulatory circuit breaker halt."
        ),
        category="Microstructure Crisis",
        default_params={"crash_pct": -0.10, "halt_duration_s": 5.0},
    ),
    ScenarioDefinition(
        id="high_volatility_regime",
        name="High Volatility Regime",
        description=(
            "Exogenous macroeconomic uncertainty shifts market to high volatility "
            "regime (3x variance, wider spreads)."
        ),
        category="Regime Shift",
        default_params={"regime": "HIGH", "multiplier": 3.0},
    ),
    ScenarioDefinition(
        id="normal_volatility_regime",
        name="Normal Volatility Regime",
        description=(
            "Market returns to standard volatility regime with balanced liquidity "
            "and tight spreads."
        ),
        category="Regime Shift",
        default_params={"regime": "NORMAL", "multiplier": 1.0},
    ),
    ScenarioDefinition(
        id="halt_trading",
        name="Halt Trading (Circuit Breaker)",
        description=(
            "Immediately halt trading for the symbol. All aggressive orders are "
            "rejected until market resumes."
        ),
        category="Market Control",
        default_params={"reason": "REGULATORY_LULD_LIMIT"},
    ),
    ScenarioDefinition(
        id="resume_trading",
        name="Resume Trading",
        description="Reopen halted market for orderly order book quoting and trade matching.",
        category="Market Control",
        default_params={},
    ),
]


def get_available_scenarios() -> list[dict[str, Any]]:
    """Return list of all registered scenarios for REST consumption."""
    return [s.to_dict() for s in SCENARIO_CATALOG]


def create_earnings_shock(
    symbol: str,
    jump_pct: float,
    seq: int,
    ts_ns: int,
    volatility_mult: float = 2.0,
) -> MarketEvent:
    """Create an EARNINGS_SHOCK MarketEvent."""
    return MarketEvent(
        seq=seq,
        ts_ns=ts_ns,
        symbol=symbol,
        kind="EARNINGS_SHOCK",
        params={
            "jump_pct": jump_pct,
            "volatility_multiplier": volatility_mult,
        },
    )


def create_volatility_regime(
    symbol: str,
    regime: str,
    multiplier: float,
    seq: int,
    ts_ns: int,
) -> MarketEvent:
    """Create a VOLATILITY_REGIME MarketEvent."""
    return MarketEvent(
        seq=seq,
        ts_ns=ts_ns,
        symbol=symbol,
        kind="VOLATILITY_REGIME",
        params={
            "regime": regime.upper(),
            "volatility_multiplier": multiplier,
        },
    )


def create_halt_event(
    symbol: str,
    reason: str,
    seq: int,
    ts_ns: int,
) -> MarketEvent:
    """Create a HALT MarketEvent."""
    return MarketEvent(
        seq=seq,
        ts_ns=ts_ns,
        symbol=symbol,
        kind="HALT",
        params={"reason": reason},
    )


def create_resume_event(
    symbol: str,
    seq: int,
    ts_ns: int,
) -> MarketEvent:
    """Create a RESUME MarketEvent."""
    return MarketEvent(
        seq=seq,
        ts_ns=ts_ns,
        symbol=symbol,
        kind="RESUME",
        params={},
    )
