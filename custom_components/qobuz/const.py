"""Constants for the Qobuz integration."""

DOMAIN = "qobuz"

# Config
CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # used only during initial login flow

# Defaults
DEFAULT_POLL_INTERVAL = 30  # seconds
DEFAULT_QUALITY = "lossless"  # or hi-res, etc.

# API
QOBUZ_API_BASE = "https://www.qobuz.com/api.json/0.2"
QOBUZ_WS_BASE = "wss://play.qobuz.com/ws"  # or region specific

# Media player
ATTR_QOBUZ_TRACK_ID = "qobuz_track_id"
ATTR_ALBUM_ID = "album_id"
ATTR_PLAYLIST_ID = "playlist_id"