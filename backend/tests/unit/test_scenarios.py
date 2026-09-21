"""Unit tests for market scenarios, exogenous shocks, and halt mechanics."""

from __future__ import annotations

from marketpulse.core.clock import SimulatedClock
from marketpulse.core.events import (
    MarketEvent,
    OrderRejected,
    OrderSubmitted,
    OrderType,
    Side,
    TimeInForce,
)
from marketpulse.core.orderbook import MatchingEngine
from marketpulse.core.scenarios import (
    SCENARIO_CATALOG,
    create_earnings_shock,
    create_halt_event,
    create_resume_event,
    create_volatility_regime,
    get_available_scenarios,
)
from marketpulse.sim.agent_source import AgentOrderSource


def test_scenario_catalog() -> None:
    """Verify SCENARIO_CATALOG integrity and serialization."""
    scenarios = get_available_scenarios()
    assert len(scenarios) >= 5
    ids = [s["id"] for s in scenarios]
    assert "earnings_shock_positive" in ids
    assert "earnings_shock_negative" in ids
    assert "flash_crash" in ids
    assert "high_volatility_regime" in ids
    assert "halt_trading" in ids
    assert "resume_trading" in ids

    # Check each definition has non-empty fields
    for s in SCENARIO_CATALOG:
        assert len(s.id) > 0
        assert len(s.name) > 0
        assert len(s.description) > 0
        assert len(s.category) > 0


def test_scenario_factories() -> None:
    """Verify scenario creation helper functions."""
    shock = create_earnings_shock("AAPL", 0.05, 1, 1000, volatility_mult=2.5)
    assert shock.symbol == "AAPL"
    assert shock.kind == "EARNINGS_SHOCK"
    assert shock.params["jump_pct"] == 0.05
    assert shock.params["volatility_multiplier"] == 2.5

    vol = create_volatility_regime("AAPL", "HIGH", 3.0, 2, 2000)
    assert vol.kind == "VOLATILITY_REGIME"
    assert vol.params["regime"] == "HIGH"
    assert vol.params["volatility_multiplier"] == 3.0

    halt = create_halt_event("AAPL", "CIRCUIT_BREAKER", 3, 3000)
    assert halt.kind == "HALT"
    assert halt.params["reason"] == "CIRCUIT_BREAKER"

    resume = create_resume_event("AAPL", 4, 4000)
    assert resume.kind == "RESUME"


def test_matching_engine_halt_and_resume() -> None:
    """Verify MatchingEngine halts, rejects orders, and resumes properly."""
    engine = MatchingEngine(symbol="AAPL", initial_seq=1)
    assert not engine.is_halted

    # Post initial passive order
    b1 = OrderSubmitted(
        seq=1,
        ts_ns=1000,
        symbol="AAPL",
        order_id="b1",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=100,
        tif=TimeInForce.GTC,
    )
    events = engine.submit_order(b1)
    assert len(events) == 2  # Accepted + Delta

    # Halt trading
    halt_evts = engine.halt(ts_ns=2000, reason="MANUAL_HALT")
    assert engine.is_halted
    assert len(halt_evts) == 1
    assert halt_evts[0].kind == "HALT"

    # Subsequent orders must be rejected with MARKET_HALTED
    s1 = OrderSubmitted(
        seq=2,
        ts_ns=3000,
        symbol="AAPL",
        order_id="s1",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=50,
        tif=TimeInForce.GTC,
    )
    rej_evts = engine.submit_order(s1)
    assert len(rej_evts) == 1
    assert isinstance(rej_evts[0], OrderRejected)
    assert rej_evts[0].reason == "MARKET_HALTED"

    # Resume trading
    resume_evts = engine.resume(ts_ns=4000)
    assert not engine.is_halted
    assert len(resume_evts) == 1
    assert resume_evts[0].kind == "RESUME"

    # Orders should execute normally now
    s2 = OrderSubmitted(
        seq=3,
        ts_ns=5000,
        symbol="AAPL",
        order_id="s2",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price_ticks=15000,
        qty=50,
        tif=TimeInForce.GTC,
    )
    ok_evts = engine.submit_order(s2)
    # Trade should execute against the resting b1 order
    executed = [e for e in ok_evts if e.event_type.value == "TRADE_EXECUTED"]
    assert len(executed) == 1


def test_agent_order_source_scenario_injection() -> None:
    """Verify injecting events into AgentOrderSource propagates to agents and engine."""
    clock = SimulatedClock(0)
    source = AgentOrderSource(
        seed=123,
        symbol="AAPL",
        initial_price=150.0,
        clock=clock,
    )

    # Drain initial bootstrap liquidity quotes
    while source._pending_events:
        source.next_event()

    # 1. Inject Earnings Shock (+10%)
    shock = MarketEvent(
        seq=1,
        ts_ns=1000,
        symbol="AAPL",
        kind="EARNINGS_SHOCK",
        params={"jump_pct": 0.10, "volatility_multiplier": 2.0},
    )
    injected = source.inject_market_event(shock)
    assert len(injected) == 1
    assert source._current_ref_price_ticks > source._initial_price_ticks

    # Next event from source should be the injected shock
    evt = source.next_event()
    assert isinstance(evt, MarketEvent)
    assert evt.kind == "EARNINGS_SHOCK"

    # 2. Inject Halt
    halt = MarketEvent(
        seq=2,
        ts_ns=2000,
        symbol="AAPL",
        kind="HALT",
        params={"reason": "LULD_LIMIT"},
    )
    source.inject_market_event(halt)
    assert source.engine.is_halted

    # Next event is the halt
    evt2 = source.next_event()
    assert isinstance(evt2, MarketEvent)
    assert evt2.kind == "HALT"

    # 3. Inject Resume
    resume = MarketEvent(
        seq=3,
        ts_ns=3000,
        symbol="AAPL",
        kind="RESUME",
        params={},
    )
    source.inject_market_event(resume)
    assert not source.engine.is_halted


def test_scenario_determinism() -> None:
    """Verify identical simulation runs with identical injections yield identical streams."""

    def run_sim(seed: int) -> list[str]:
        clock = SimulatedClock(0)
        source = AgentOrderSource(
            seed=seed,
            symbol="AAPL",
            initial_price=100.0,
            clock=clock,
        )
        stream_log: list[str] = []

        # Run 25 steps
        for _ in range(25):
            e = source.next_event()
            if e:
                stream_log.append(f"{e.seq}:{e.event_type.value}")

        # Inject shock
        source.inject_market_event(
            MarketEvent(
                seq=100,
                ts_ns=max(1, clock.now_ns()),
                symbol="AAPL",
                kind="EARNINGS_SHOCK",
                params={"jump_pct": 0.05},
            )
        )

        # Run 25 more steps
        for _ in range(25):
            e = source.next_event()
            if e:
                stream_log.append(f"{e.seq}:{e.event_type.value}")

        return stream_log

    run1 = run_sim(42)
    run2 = run_sim(42)
    assert run1 == run2
