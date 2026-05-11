"""Constants for the Qobuz integration."""

DOMAIN = "qobuz"

# Config / options keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"  # used only during initial login flow, never stored
CONF_APP_ID = "app_id"
CONF_POLL_INTERVAL = "poll_interval"

# Defaults
DEFAULT_POLL_INTERVAL = 30  # seconds
DEFAULT_QUALITY = 27  # FLAC 24-bit / hi-res; Qobuz quality IDs: 5=MP3_128, 6=MP3_320, 7=FLAC, 27=HiRes

# Qobuz web-player app_id, scraped from play.qobuz.com/bundle.js.
# The integration auto-scrapes the live value on startup and falls back to this
# constant if scraping fails. Update here if the fallback stops working.
QOBUZ_APP_ID = "798273057"

# Qobuz quality format IDs
QUALITY_MP3_128 = 5
QUALITY_MP3_320 = 6
QUALITY_FLAC = 7
QUALITY_HIRES = 27
QUALITY_LABELS = {
    QUALITY_MP3_128: "MP3 128kbps",
    QUALITY_MP3_320: "MP3 320kbps",
    QUALITY_FLAC: "FLAC (Lossless)",
    QUALITY_HIRES: "FLAC Hi-Res (24-bit)",
}

# API
QOBUZ_API_BASE = "https://www.qobuz.com/api.json/0.2"
QOBUZ_WS_BASE = "wss://play.qobuz.com/ws"

# Browse content IDs
BROWSE_ROOT = "root"
BROWSE_PLAYLISTS = "qobuz:playlists"
BROWSE_FAVORITES_TRACKS = "qobuz:favorites:tracks"
BROWSE_FAVORITES_ALBUMS = "qobuz:favorites:albums"
BROWSE_FAVORITES_ARTISTS = "qobuz:favorites:artists"

# Entity attribute names
ATTR_QOBUZ_TRACK_ID = "qobuz_track_id"
ATTR_ALBUM_ID = "album_id"
ATTR_PLAYLIST_ID = "playlist_id"
ATTR_MEDIA_FORMAT = "media_format"
ATTR_MEDIA_BIT_DEPTH = "media_bit_depth"
ATTR_MEDIA_SAMPLING_RATE = "media_sampling_rate"
ATTR_SUBSCRIPTION_TYPE = "subscription_type"
