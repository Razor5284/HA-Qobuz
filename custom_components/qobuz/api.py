"""Qobuz API client for Home Assistant integration."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientResponseError, ClientSession, ClientTimeout

from .const import QOBUZ_API_BASE, QOBUZ_APP_ID

_LOGGER = logging.getLogger(__name__)

# Qobuz expects these specific headers for auth; NOT standard Bearer.
_HEADER_APP_ID = "X-App-Id"
_HEADER_AUTH_TOKEN = "X-User-Auth-Token"


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

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def validate_token(
        self, token: str, app_id: str | None = None
    ) -> dict[str, Any]:
        """Validate a browser-extracted session token by making a real API call.

        Qobuz's direct email/password login endpoint is reCAPTCHA-protected and
        cannot be used by automated clients. Users must extract their session token
        from play.qobuz.com browser Local Storage (localuser → token).

        Returns a dict with user_id and app_id on success, raises QobuzAuthError
        on failure.
        """
        if app_id:
            self._app_id = app_id

        self._token = token
        self._user_id = None  # will be populated by the validation call

        _LOGGER.debug("Validating Qobuz token (first %s...)", token[:8] if len(token) > 8 else "?")

        try:
            # /user/get validates the token and returns the user profile
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
        """Restore credentials from a previously obtained session (e.g. config entry)."""
        self._token = token
        self._user_id = user_id
        if app_id:
            self._app_id = app_id

    def set_credentials(self, app_id: str | None = None, app_secret: str | None = None) -> None:
        """Allow runtime override of app credentials (options flow)."""
        if app_id:
            self._app_id = app_id

    @property
    def is_authenticated(self) -> bool:
        return bool(self._token and self._user_id)

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------

    async def _request(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Execute an authenticated API request.

        Qobuz accepts credentials as both HTTP headers AND query parameters
        depending on the API version and endpoint.  We send both to maximise
        compatibility with whichever convention a given endpoint enforces.
        """
        url = f"{QOBUZ_API_BASE}{endpoint}"
        headers: dict[str, str] = kwargs.pop("headers", {})
        # Merge caller-supplied params so we don't overwrite them
        params: dict[str, Any] = dict(kwargs.pop("params", {}))

        # Credentials in headers
        headers[_HEADER_APP_ID] = self._app_id
        if self._token:
            headers[_HEADER_AUTH_TOKEN] = self._token

        # Credentials also in query params — many Qobuz endpoints require this
        params["app_id"] = self._app_id
        if self._token:
            params["user_auth_token"] = self._token

        _LOGGER.debug("Qobuz request: %s %s params=%s", method, endpoint, {k: v for k, v in params.items() if k != "user_auth_token"})

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
    # Library endpoints
    # ------------------------------------------------------------------

    async def get_playlists(self) -> list[dict[str, Any]]:
        """Fetch the authenticated user's playlists."""
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

    async def get_favorites(self, favor_type: str = "tracks") -> list[dict[str, Any]]:
        """Fetch the user's favourited items."""
        data = await self._request(
            "GET",
            "/favorite/getUserFavorites",
            params={"type": favor_type, "limit": 500, "offset": 0},
        )
        return data.get(favor_type, {}).get("items", [])

    async def get_current_playback(self) -> dict[str, Any] | None:
        """Attempt to fetch current playback state.

        Returns None if the endpoint does not exist or returns an error; this
        endpoint is not consistently available across all account types.
        Auth errors are re-raised so the coordinator can trigger reauth.
        """
        try:
            return await self._request("GET", "/player/getState")
        except QobuzAuthError:
            raise
        except (QobuzAPIError, Exception) as err:  # noqa: BLE001
            _LOGGER.debug("Could not fetch playback state (endpoint may not exist): %s", err)
            return None

    async def play_track(self, track_id: str) -> None:
        """Request playback of a specific track."""
        await self._request("POST", "/player/play", json={"track_id": track_id})
