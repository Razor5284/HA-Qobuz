"""Constants for the Qobuz integration."""

DOMAIN = "qobuz"

# Config keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # used only during initial login flow, never stored
CONF_APP_ID = "app_id"

# Defaults
DEFAULT_POLL_INTERVAL = 30  # seconds
DEFAULT_QUALITY = "lossless"

# Qobuz web-player app_id. This is a well-known value used by many community
# projects and is publicly visible in the Qobuz web player JavaScript.
# Users can override this in the integration options if Qobuz rotates it.
QOBUZ_APP_ID = "950096963"

# API
QOBUZ_API_BASE = "https://www.qobuz.com/api.json/0.2"
QOBUZ_WS_BASE = "wss://play.qobuz.com/ws"

# Media player
ATTR_QOBUZ_TRACK_ID = "qobuz_track_id"
ATTR_ALBUM_ID = "album_id"
ATTR_PLAYLIST_ID = "playlist_id"
