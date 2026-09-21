"""FastAPI REST and WebSocket API adapter edge layer for MarketPulse."""

from marketpulse.api.broadcaster import Broadcaster
from marketpulse.api.server import create_app

__all__ = ["Broadcaster", "create_app"]
