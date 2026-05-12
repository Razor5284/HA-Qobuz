"""Qobuz API client for Home Assistant integration."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from typing import Any

from aiohttp import ClientResponseError, ClientSession, ClientTimeout

from .const import DEFAULT_QUALITY, QOBUZ_API_BASE, QOBUZ_APP_ID, QOBUZ_WS_BASE

_BUNDLE_URL_RE = re.compile(
    r'<script src="(/resources/[\d.\-a-z]+/bundle\.js)"></script>'
)
_APP_ID_RE = re.compile(r'production:\{api:\{appId:"(?P<app_id>\d{9})"')
_SEED_TZ_RE = re.compile(
    r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)'
)

_LOGGER = logging.getLogger(__name__)

# Qobuz expects these specific headers for auth; NOT standard Bearer.
_HEADER_APP_ID = "X-App-Id"
_HEADER_AUTH_TOKEN = "X-User-Auth-Token"

# Web-player-like context for createToken — some edge/CDN paths reject generic clients.
_QOBUZ_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class QobuzAPIError(Exception):
    """Base exception for Qobuz API errors."""


class QobuzAuthError(QobuzAPIError):
    """Authentication failed (bad credentials or expired token)."""


class QobuzAPIClient:
    """Async client for the Qobuz REST API (community-documented endpoints)."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._user_id: str | None = None
        self._token: str | None = None
        self._app_id: str = QOBUZ_APP_ID
        self._app_secret: str | None = None

    # ------------------------------------------------------------------
    # Credential scraping
    # ------------------------------------------------------------------

    async def scrape_app_id(self) -> str:
        """Scrape the current app_id from the Qobuz web player bundle."""
        bundle_js = await self._fetch_bundle()
        if not bundle_js:
            return QOBUZ_APP_ID
        am = _APP_ID_RE.search(bundle_js)
        if not am:
            _LOGGER.debug("Could not find app_id in Qobuz bundle JS")
            return QOBUZ_APP_ID
        scraped = am.group("app_id")
        _LOGGER.debug("Scraped Qobuz app_id: %s", scraped)
        return scraped

    async def scrape_app_credentials(self) -> tuple[str, str | None]:
        """Scrape both app_id and app_secret from the Qobuz bundle JS.

        The secret is embedded in obfuscated form; this uses the same
        seed+timezone+info+extras decode used by community tools (QobuzDL).
        Returns (app_id, app_secret | None).
        """
        bundle_js = await self._fetch_bundle()
        if not bundle_js:
            return QOBUZ_APP_ID, None

        am = _APP_ID_RE.search(bundle_js)
        app_id = am.group("app_id") if am else QOBUZ_APP_ID

        # Build timezone → secret arrays
        secrets: dict[str, list[str]] = {}
        for seed_m in _SEED_TZ_RE.finditer(bundle_js):
            tz = seed_m.group("timezone")
            secrets[tz] = [seed_m.group("seed")]

        if not secrets:
            _LOGGER.debug("No seed/timezone entries found in bundle; app_secret unavailable")
            return app_id, None

        timezones = "|".join(tz.capitalize() for tz in secrets)
        info_extras_re = re.compile(
            rf'name:"\w+/(?P<tz>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
        )
        for m in info_extras_re.finditer(bundle_js):
            tz = m.group("tz").lower()
            if tz in secrets:
                secrets[tz].extend([m.group("info"), m.group("extras")])

        for secret_parts in secrets.values():
            combined = "".join(secret_parts)[:-44]
            try:
                candidate = base64.b64decode(combined).decode("utf-8")
                if candidate:
                    _LOGGER.debug("Scraped Qobuz app_secret (first 6): %s...", candidate[:6])
                    return app_id, candidate
            except Exception:  # noqa: BLE001
                continue

        return app_id, None

    async def _fetch_bundle(self) -> str | None:
        """Fetch the Qobuz web player bundle JS; return None on failure."""
        try:
            timeout = ClientTimeout(total=20)
            async with self._session.get(
                "https://play.qobuz.com/login", timeout=timeout
            ) as resp:
                login_html = await resp.text()

            m = _BUNDLE_URL_RE.search(login_html)
            if not m:
                _LOGGER.debug("Could not locate bundle URL in Qobuz login page")
                return None

            bundle_path = m.group(1)
            async with self._session.get(
                f"https://play.qobuz.com{bundle_path}", timeout=timeout
            ) as resp:
                return await resp.text()

        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Bundle fetch failed: %s", err)
            return None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def validate_token(
        self, token: str, app_id: str | None = None
    ) -> dict[str, Any]:
        """Validate a browser-extracted session token via /user/get."""
        self._app_id = app_id or await self.scrape_app_id()
        self._token = token
        self._user_id = None

        _LOGGER.debug(
            "Validating Qobuz token (first %s...) with app_id=%s",
            token[:8] if len(token) > 8 else "?",
            self._app_id,
        )

        try:
            data = await self._request("GET", "/user/get")
        except QobuzAuthError:
            raise
        except QobuzAPIError as err:
            raise QobuzAuthError(f"Token validation failed: {err}") from err

        user_id = str(data.get("id", "") or data.get("user", {}).get("id", ""))
        if not user_id:
            _LOGGER.debug("User profile response keys: %s", list(data.keys()))
            raise QobuzAuthError("Token is valid but user profile returned no user_id")

        self._user_id = user_id
        _LOGGER.debug("Token valid for user_id=%s", user_id)
        return {"user_id": user_id, "app_id": self._app_id}

    def set_auth(self, token: str, user_id: str, app_id: str | None = None) -> None:
        """Restore credentials from a config entry."""
        self._token = token
        self._user_id = user_id
        if app_id:
            self._app_id = app_id

    def set_app_secret(self, secret: str) -> None:
        """Store the app_secret (required for stream URL signing)."""
        self._app_secret = secret

    def set_credentials(self, app_id: str | None = None, app_secret: str | None = None) -> None:
        """Runtime override (options flow)."""
        if app_id:
            self._app_id = app_id
        if app_secret:
            self._app_secret = app_secret

    @property
    def is_authenticated(self) -> bool:
        return bool(self._token and self._user_id)

    @property
    def has_stream_support(self) -> bool:
        """True if we have an app_secret and can generate signed stream URLs."""
        return bool(self._app_secret)

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------

    async def _request(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Execute an authenticated API request."""
        url = f"{QOBUZ_API_BASE}{endpoint}"
        headers: dict[str, str] = kwargs.pop("headers", {})
        params: dict[str, Any] = dict(kwargs.pop("params", {}))

        headers[_HEADER_APP_ID] = self._app_id
        if self._token:
            headers[_HEADER_AUTH_TOKEN] = self._token

        # Many Qobuz endpoints also require credentials as query params
        params["app_id"] = self._app_id
        if self._token:
            params["user_auth_token"] = self._token

        _LOGGER.debug(
            "Qobuz %s %s params=%s",
            method,
            endpoint,
            {k: v for k, v in params.items() if k not in {"user_auth_token"}},
        )

        timeout = ClientTimeout(total=15)
        try:
            async with self._session.request(
                method, url, headers=headers, params=params, timeout=timeout, **kwargs
            ) as resp:
                if resp.status == 401:
                    raise QobuzAuthError("Token expired or invalid")
                resp.raise_for_status()
                return await resp.json()
        except QobuzAuthError:
            raise
        except ClientResponseError as err:
            raise QobuzAPIError(f"{endpoint} failed: {err.status} {err.message}") from err

    # ------------------------------------------------------------------
    # User / account
    # ------------------------------------------------------------------

    async def get_user_info(self) -> dict[str, Any]:
        """Fetch the authenticated user's profile."""
        return await self._request("GET", "/user/get")

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------

    async def get_playlists(self) -> list[dict[str, Any]]:
        """Fetch the user's playlists."""
        data = await self._request(
            "GET",
            "/playlist/getUserPlaylists",
            params={"limit": 500, "offset": 0},
        )
        return data.get("playlists", {}).get("items", [])

    async def get_playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        """Fetch tracks for a specific playlist."""
        data = await self._request(
            "GET",
            "/playlist/get",
            params={"playlist_id": playlist_id, "limit": 500, "offset": 0, "extra": "tracks"},
        )
        return data.get("tracks", {}).get("items", [])

    async def get_favorite_tracks(self) -> list[dict[str, Any]]:
        """Fetch the user's favourite tracks."""
        data = await self._request(
            "GET",
            "/favorite/getUserFavorites",
            params={"type": "tracks", "limit": 500, "offset": 0},
        )
        return data.get("tracks", {}).get("items", [])

    async def get_favorite_albums(self) -> list[dict[str, Any]]:
        """Fetch the user's favourite albums."""
        data = await self._request(
            "GET",
            "/favorite/getUserFavorites",
            params={"type": "albums", "limit": 500, "offset": 0},
        )
        return data.get("albums", {}).get("items", [])

    async def get_favorite_artists(self) -> list[dict[str, Any]]:
        """Fetch the user's favourite artists."""
        data = await self._request(
            "GET",
            "/favorite/getUserFavorites",
            params={"type": "artists", "limit": 500, "offset": 0},
        )
        return data.get("artists", {}).get("items", [])

    async def get_album(self, album_id: str) -> dict[str, Any]:
        """Fetch album details including tracks."""
        return await self._request(
            "GET",
            "/album/get",
            params={"album_id": album_id, "extra": "tracks"},
        )

    async def search(self, query: str, limit: int = 20) -> dict[str, Any]:
        """Search across Qobuz catalogue."""
        return await self._request(
            "GET",
            "/catalog/search",
            params={"query": query, "limit": limit, "offset": 0},
        )

    # ------------------------------------------------------------------
    # Qobuz Connect (QWS) — WebSocket JWT
    # ------------------------------------------------------------------

    async def create_qws_token(self) -> dict[str, Any]:
        """Create a short-lived JWT for QConnect WebSocket (`/qws/createToken`).

        Returns a dict with at least:
          - ``jwt``: bearer string for Authenticate envelope
          - ``endpoint``: WebSocket URL (e.g. regional ``wss://qws-…/ws``)
          - ``exp``: optional unix expiry seconds

        The web player calls ``createQWSToken({tokenTypes: ["jwt_qws"]})``, which
        becomes form field **``jwt=jwt_qws``** (literal string) plus ``app_id``.
        The session token is sent only as **``X-User-Auth-Token``**, not as the
        ``jwt`` body value. Using the session string as ``jwt`` returns HTTP 400.
        """
        raw = await self._request_qws_token()
        return self._parse_qws_response(raw)

    def _qws_create_token_headers(self) -> dict[str, str]:
        """Headers aligned with the Qobuz web player for ``/qws/createToken``."""
        headers: dict[str, str] = {
            _HEADER_APP_ID: self._app_id,
            "User-Agent": _QOBUZ_BROWSER_UA,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-us,en;q=0.9",
            "Origin": "https://play.qobuz.com",
            "Referer": "https://play.qobuz.com/",
        }
        if self._token:
            headers[_HEADER_AUTH_TOKEN] = self._token
        return headers

    async def _post_qws_create_token(
        self, url: str, form: dict[str, str], label: str
    ) -> dict[str, Any] | None:
        """POST ``createToken`` once; return JSON on 200, None otherwise."""
        timeout = ClientTimeout(total=15)
        try:
            async with self._session.post(
                url,
                headers=self._qws_create_token_headers(),
                data=form,
                timeout=timeout,
            ) as resp:
                raw = await resp.text()
                if resp.status == 200:
                    _LOGGER.debug("createToken succeeded via POST (%s)", label)
                    return json.loads(raw)
                if resp.status == 401:
                    raise QobuzAuthError("Token expired or invalid")
                _LOGGER.debug(
                    "createToken POST %s -> HTTP %s: %s",
                    label,
                    resp.status,
                    raw[:400],
                )
        except QobuzAuthError:
            raise
        except json.JSONDecodeError as err:
            _LOGGER.debug("createToken POST %s: invalid JSON: %s", label, err)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("createToken POST %s failed: %s", label, err)
        return None

    async def _request_qws_token(self) -> dict[str, Any]:
        """Try multiple approaches to obtain a QWS token."""
        url = f"{QOBUZ_API_BASE}/qws/createToken"
        timeout = ClientTimeout(total=15)

        # Web bundle: createQWSToken({tokenTypes:["jwt_qws"]}) → paramsMapper → {jwt: tokenTypes}
        # So the form sends jwt=jwt_qws (discriminator), NOT the session string. Auth is headers only.
        post_attempts: list[tuple[str, dict[str, str]]] = [
            ("jwt_discriminator", {"app_id": self._app_id, "jwt": "jwt_qws"}),
            ("user_auth_token", {"app_id": self._app_id, "user_auth_token": self._token}),
        ] if self._token else [("app_id_only", {"app_id": self._app_id})]

        for label, form in post_attempts:
            parsed = await self._post_qws_create_token(url, form, label)
            if parsed is not None:
                return parsed

        # GET with query params (legacy / fallback)
        params: dict[str, str] = {"app_id": self._app_id}
        if self._token:
            params["user_auth_token"] = self._token
        try:
            async with self._session.get(
                url,
                headers=self._qws_create_token_headers(),
                params=params,
                timeout=timeout,
            ) as resp:
                if resp.status == 401:
                    raise QobuzAuthError("Token expired or invalid")
                if resp.status == 200:
                    _LOGGER.debug("createToken succeeded via GET")
                    return await resp.json()
                raw = await resp.text()
                _LOGGER.debug(
                    "createToken GET -> HTTP %s: %s", resp.status, raw[:400]
                )
                resp.raise_for_status()
        except QobuzAuthError:
            raise
        except ClientResponseError as err:
            raise QobuzAPIError(
                f"/qws/createToken failed: {err.status} {err.message}"
            ) from err

        raise QobuzAPIError("/qws/createToken: all methods exhausted")

    @staticmethod
    def _parse_qws_response(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize the various createToken response shapes."""
        nested = raw.get("jwt_qws")
        if isinstance(nested, dict):
            jwt = nested.get("jwt") or nested.get("token")
            endpoint = nested.get("endpoint") or nested.get("url") or QOBUZ_WS_BASE
            exp = nested.get("exp")
        else:
            jwt = raw.get("jwt") or raw.get("token")
            endpoint = raw.get("endpoint") or raw.get("url") or QOBUZ_WS_BASE
            exp = raw.get("exp")

        if not jwt or not isinstance(jwt, str):
            raise QobuzAPIError("createToken response missing jwt")

        if not isinstance(endpoint, str):
            endpoint = QOBUZ_WS_BASE

        return {"jwt": jwt.strip(), "endpoint": endpoint.strip(), "exp": exp}

    # ------------------------------------------------------------------
    # Playback / streaming
    # ------------------------------------------------------------------

    async def get_current_playback(self) -> dict[str, Any] | None:
        """Attempt to fetch current playback state (not available on all accounts)."""
        try:
            return await self._request("GET", "/player/getState")
        except QobuzAuthError:
            raise
        except (QobuzAPIError, Exception) as err:  # noqa: BLE001
            _LOGGER.debug("Could not fetch playback state: %s", err)
            return None

    async def get_track_url(
        self, track_id: str, format_id: int = DEFAULT_QUALITY
    ) -> str | None:
        """Return a signed stream URL for a track.

        Requires app_secret to be set (call scrape_app_credentials() first).
        Returns None if no secret is available.
        """
        if not self._app_secret:
            _LOGGER.debug("No app_secret — cannot generate stream URL")
            return None

        ts = int(time.time())
        r_sig = f"trackgetFileUrlformat_id{format_id}intentstreamtrack_id{track_id}{ts}{self._app_secret}"
        r_sig_hashed = hashlib.md5(r_sig.encode()).hexdigest()  # noqa: S324

        try:
            data = await self._request(
                "GET",
                "/track/getFileUrl",
                params={
                    "track_id": track_id,
                    "format_id": format_id,
                    "intent": "stream",
                    "request_ts": ts,
                    "request_sig": r_sig_hashed,
                },
            )
            return data.get("url")
        except QobuzAPIError as err:
            _LOGGER.debug("get_track_url failed for track %s: %s", track_id, err)
            return None

    async def get_track_info(self, track_id: str) -> dict[str, Any]:
        """Fetch metadata for a single track."""
        return await self._request("GET", "/track/get", params={"track_id": track_id})
