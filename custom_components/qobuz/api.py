"""Qobuz API client for Home Assistant integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientSession, ClientTimeout

from .const import QOBUZ_API_BASE

_LOGGER = logging.getLogger(__name__)


class QobuzAPIError(Exception):
    """Base exception for Qobuz API errors."""


class QobuzAuthError(QobuzAPIError):
    """Authentication failed."""


class QobuzAPIClient:
    """Async client for Qobuz REST API (unofficial endpoints)."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session
        self._user_id: str | None = None
        self._token: str | None = None
        self._app_id: str | None = None  # obtained or configured
        self._app_secret: str | None = None

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """Perform login and return user info + token."""
        # Placeholder: real impl would POST to /user/login or similar with email/pass
        # and handle 2FA if needed. Returns dict with user_id, token, etc.
        _LOGGER.debug("Attempting login for %s", email)
        # Simulate
        await asyncio.sleep(0.1)
        # In real: construct signed request, etc.
        self._user_id = "mock_user_123"
        self._token = "mock_jwt_token_for_qobuz"
        return {"user_id": self._user_id, "token": self._token, "email": email}

    async def _request(
        self, method: str, endpoint: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Internal request helper with auth headers."""
        url = f"{QOBUZ_API_BASE}{endpoint}"
        headers = kwargs.pop("headers", {})
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._app_id:
            headers["X-App-Id"] = self._app_id

        timeout = ClientTimeout(total=15)
        async with self._session.request(
            method, url, headers=headers, timeout=timeout, **kwargs
        ) as resp:
            if resp.status == 401:
                raise QobuzAuthError("Token expired or invalid")
            resp.raise_for_status()
            return await resp.json()

    async def get_playlists(self) -> list[dict[str, Any]]:
        """Fetch user playlists."""
        data = await self._request("GET", "/playlist/getUserPlaylists")
        return data.get("playlists", [])

    async def get_playlist_tracks(self, playlist_id: str) -> list[dict[str, Any]]:
        """Get tracks for a playlist."""
        data = await self._request(
            "GET", "/playlist/get", params={"playlist_id": playlist_id}
        )
        return data.get("tracks", {}).get("items", [])

    async def get_favorites(self, type: str = "tracks") -> list[dict[str, Any]]:
        """Get user favorites."""
        data = await self._request("GET", "/favorite/getUserFavorites", params={"type": type})
        return data.get("favorites", [])

    async def get_current_playback(self) -> dict[str, Any] | None:
        """Fetch current playback status if available via API."""
        # Many unofficial clients poll /player or similar; placeholder
        try:
            data = await self._request("GET", "/player/getState")
            return data
        except Exception:
            return None

    async def play_track(self, track_id: str) -> None:
        """Initiate playback of a track (if API supports)."""
        await self._request("POST", "/player/play", json={"track_id": track_id})

    # Add more methods: search, album details, etc. as discovered

    def set_credentials(self, app_id: str | None = None, app_secret: str | None = None) -> None:
        """Allow runtime override of app credentials."""
        if app_id:
            self._app_id = app_id
        if app_secret:
            self._app_secret = app_secret

    @property
    def is_authenticated(self) -> bool:
        return bool(self._token and self._user_id)
