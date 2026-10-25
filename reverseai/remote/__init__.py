"""Remote-control surfaces: a local desktop broker and a Telegram channel.

These are transports and control planes, not a VNC server or a public bot. They
are denied by default, require a capability opt-in, and require a scoped approval
for any consequential action. No input-injection backend is bundled.
"""

from .desktop import DesktopBroker, DesktopControlServer, DesktopSession
from .telegram import TelegramBot, TelegramConfig, TelegramTransport

__all__ = [
    "DesktopBroker", "DesktopControlServer", "DesktopSession",
    "TelegramBot", "TelegramConfig", "TelegramTransport",
]
