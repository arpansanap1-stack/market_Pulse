"""Historical replay event source backed by SQLiteEventStore."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator

from marketpulse.core.clock import Clock, SimulatedClock
from marketpulse.core.events import Event
from marketpulse.storage.event_store import SQLiteEventStore


class ReplayEventSource:
    """Replays sequenced historical events from SQLiteEventStore with pacing and seeking."""

    __slots__ = (
        "_buffer",
        "_chunk_size",
        "_clock",
        "_current_seq",
        "_event_store",
        "_is_paused",
        "_last_ts_ns",
        "_session_id",
        "_speed_multiplier",
        "_total_events",
    )

    def __init__(
        self,
        event_store: SQLiteEventStore,
        session_id: str,
        speed_multiplier: float = 1.0,
        clock: Clock | None = None,
        chunk_size: int = 250,
    ) -> None:
        """Initialize the historical replay event source.

        Args:
            event_store: The SQLiteEventStore holding recorded events.
            session_id: Identifier of the session to replay.
            speed_multiplier: Playback speed multiplier (e.g. 1.0 = real-time, 2.0 = 2x).
            clock: Optional Clock abstraction (defaults to SimulatedClock).
            chunk_size: Buffer prefetch size for batch database retrieval.
        """
        if speed_multiplier <= 0:
            raise ValueError(f"speed_multiplier must be > 0, got {speed_multiplier}")
        if chunk_size < 1:
            raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")

        self._event_store = event_store
        self._session_id = session_id
        self._speed_multiplier = speed_multiplier
        self._chunk_size = chunk_size
        self._current_seq: int = 1
        self._is_paused: bool = False
        self._last_ts_ns: int | None = None
        self._buffer: deque[Event] = deque()

        session = self._event_store.get_session(session_id)
        if session is not None and session.total_events > 0:
            self._total_events = session.total_events
        else:
            self._total_events = self._event_store.count_events(session_id)

        start_time = session.start_ts_ns if session else 0
        self._clock: Clock = clock if clock is not None else SimulatedClock(start_time)

    @property
    def session_id(self) -> str:
        """Return the replayed session identifier."""
        return self._session_id

    @property
    def current_seq(self) -> int:
        """Return the next sequence number to be emitted."""
        return self._current_seq

    @property
    def total_events(self) -> int:
        """Return total events recorded in the session."""
        return self._total_events

    @property
    def speed_multiplier(self) -> float:
        """Return the current playback speed multiplier."""
        return self._speed_multiplier

    @property
    def is_paused(self) -> bool:
        """Return whether replay is currently paused."""
        return self._is_paused

    @property
    def clock(self) -> Clock:
        """Return the internal simulation clock."""
        return self._clock

    def set_speed(self, multiplier: float) -> None:
        """Update the replay speed multiplier.

        Args:
            multiplier: Speed factor (e.g. 0.5, 1.0, 2.0, 5.0, 10.0).
        """
        if multiplier <= 0:
            raise ValueError(f"speed_multiplier must be > 0, got {multiplier}")
        self._speed_multiplier = multiplier

    def pause(self) -> None:
        """Pause replay progression."""
        self._is_paused = True

    def resume(self) -> None:
        """Resume replay progression."""
        self._is_paused = False

    def seek(self, target_seq: int) -> None:
        """Reposition replay cursor to the specified sequence number.

        Args:
            target_seq: Target 1-based sequence number.
        """
        clamped_seq = max(1, target_seq)
        self._current_seq = clamped_seq
        self._buffer.clear()
        self._last_ts_ns = None

    def reset(self, seed: int = 0) -> None:
        """Reset replay cursor back to sequence 1 (conforms to EventSource protocol)."""
        self.seek(1)

    def has_next(self) -> bool:
        """Check if unread events remain in the replayed session."""
        if self._buffer:
            return True
        return self._current_seq <= self._total_events

    def calculate_delay_s(
        self,
        prev_ts_ns: int | None,
        curr_ts_ns: int,
        max_delay_s: float = 2.0,
    ) -> float:
        """Calculate paced wall-clock sleep duration for real-time replay simulation.

        Args:
            prev_ts_ns: Timestamp of prior emitted event (nanoseconds).
            curr_ts_ns: Timestamp of current event (nanoseconds).
            max_delay_s: Maximum delay ceiling to avoid idle hanging on market lulls.

        Returns:
            Sleep duration in seconds, scaled by speed_multiplier.
        """
        if prev_ts_ns is None or curr_ts_ns <= prev_ts_ns:
            return 0.0
        # If speed multiplier is huge (e.g. >= 1000x / MAX mode), yield immediately
        if self._speed_multiplier >= 1000.0:
            return 0.0

        delta_ns = curr_ts_ns - prev_ts_ns
        delta_s = (delta_ns / 1_000_000_000.0) / self._speed_multiplier
        return max(0.0, min(delta_s, max_delay_s))

    def _refill_buffer(self) -> None:
        """Prefetch next chunk of events into buffer."""
        events = self._event_store.get_events(
            session_id=self._session_id,
            from_seq=self._current_seq,
            limit=self._chunk_size,
        )
        for e in events:
            self._buffer.append(e)

    def next_event(self) -> Event | None:
        """Fetch the next event in the replayed stream, advancing cursor."""
        if self._is_paused:
            return None

        if not self._buffer:
            self._refill_buffer()
            if not self._buffer:
                return None

        event = self._buffer.popleft()
        self._current_seq = event.seq + 1

        # Synchronize simulation clock with event timestamp
        if isinstance(self._clock, SimulatedClock):
            if event.ts_ns >= self._clock.now_ns():
                self._clock.set_time(event.ts_ns)
            else:
                self._clock.reset(event.ts_ns)

        self._last_ts_ns = event.ts_ns
        return event

    def stream(self) -> Iterator[Event]:
        """Iterate continuously until session ends."""
        while self.has_next():
            event = self.next_event()
            if event is not None:
                yield event
            elif self._is_paused:
                break
