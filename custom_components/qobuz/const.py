"""Constants for the Qobuz integration."""

DOMAIN = "qobuz"

# Config keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # used only during initial login flow, never stored
CONF_APP_ID = "app_id"

# Defaults
DEFAULT_POLL_INTERVAL = 30  # seconds
DEFAULT_QUALITY = "lossless"

# Qobuz web-player app_id, scraped from play.qobuz.com/bundle.js.
# The integration auto-scrapes the live value on startup and falls back to this
# constant if scraping fails.  Update here if the fallback stops working.
QOBUZ_APP_ID = "798273057"

# API
QOBUZ_API_BASE = "https://www.qobuz.com/api.json/0.2"
QOBUZ_WS_BASE = "wss://play.qobuz.com/ws"

# Media player
ATTR_QOBUZ_TRACK_ID = "qobuz_track_id"
ATTR_ALBUM_ID = "album_id"
ATTR_PLAYLIST_ID = "playlist_id"
