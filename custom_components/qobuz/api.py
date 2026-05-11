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

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """Authenticate with Qobuz and return session data.

        Uses the community-documented /user/login endpoint.  The app_id is
        required by Qobuz for all API requests; the default value (QOBUZ_APP_ID)
        is the publicly visible web-player app_id used by many open-source
        Qobuz clients.
        """
        _LOGGER.debug("Attempting Qobuz login for %s", email)

        url = f"{QOBUZ_API_BASE}/user/login"
        params = {
            "email": email,
            "password": password,
            "app_id": self._app_id,
        }
        headers = {_HEADER_APP_ID: self._app_id}

        try:
            timeout = ClientTimeout(total=15)
            async with self._session.request(
                "GET", url, params=params, headers=headers, timeout=timeout
            ) as resp:
                if resp.status in {400, 401, 403}:
                    raise QobuzAuthError("Invalid email or password")
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json()
        except QobuzAuthError:
            raise
        except ClientResponseError as err:
            raise QobuzAPIError(f"Login request failed: {err.status} {err.message}") from err
        except Exception as err:  # noqa: BLE001
            raise QobuzAPIError(f"Login request failed: {err}") from err

        token: str = data.get("user_auth_token", "")
        if not token:
            _LOGGER.debug("Login response: %s", data)
            raise QobuzAuthError("No auth token in Qobuz login response")

        user_id: str = str(data.get("user", {}).get("id", ""))

        self._token = token
        self._user_id = user_id

        _LOGGER.debug("Login successful for user_id=%s", user_id)
        return {"user_id": user_id, "token": token, "app_id": self._app_id, "email": email}

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
        """Execute an authenticated API request."""
        url = f"{QOBUZ_API_BASE}{endpoint}"
        headers: dict[str, str] = kwargs.pop("headers", {})
        headers[_HEADER_APP_ID] = self._app_id
        if self._token:
            headers[_HEADER_AUTH_TOKEN] = self._token

        timeout = ClientTimeout(total=15)
        try:
            async with self._session.request(
                method, url, headers=headers, timeout=timeout, **kwargs
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
