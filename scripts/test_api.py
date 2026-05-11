#!/usr/bin/env python3
"""Standalone Qobuz API test script.

Qobuz's login endpoint is reCAPTCHA-protected — direct email/password auth
is blocked for all third-party clients. Use a browser-extracted session token.

Usage:
    python3 scripts/test_api.py <user_auth_token> [app_id]

How to get your token:
    1. Open https://play.qobuz.com in your browser and log in.
    2. Press F12 → Application tab → Local Storage → https://play.qobuz.com
    3. Click the 'localuser' row and copy the 'token' value.

The app_id defaults to 950096963. You can also set QOBUZ_APP_ID as an env var.

Requirements:
    pip install aiohttp
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

QOBUZ_API_BASE = "https://www.qobuz.com/api.json/0.2"
_HEADER_APP_ID = "X-App-Id"
_HEADER_AUTH_TOKEN = "X-User-Auth-Token"


def _mask(s: str, keep: int = 8) -> str:
    if not s or len(s) <= keep:
        return "***"
    return s[:keep] + "..." + s[-4:]


async def run(token: str, app_id: str) -> None:
    import aiohttp

    print(f"\n{'='*60}")
    print("  Qobuz API test")
    print(f"  token:  {_mask(token)}")
    print(f"  app_id: {app_id}")
    print(f"{'='*60}\n")

    headers = {_HEADER_APP_ID: app_id, _HEADER_AUTH_TOKEN: token}
    params_base = {"app_id": app_id, "user_auth_token": token}

    async with aiohttp.ClientSession() as session:

        # ---------------------------------------------------------------
        # Step 1: Validate token via /user/get
        # ---------------------------------------------------------------
        print("[ 1 ] Validating token via /user/get ...")
        async with session.get(
            f"{QOBUZ_API_BASE}/user/get",
            params=params_base,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            print(f"      HTTP status: {resp.status}")
            raw = await resp.text()

            if resp.status == 401:
                print("\n  ❌ Token rejected (401)")
                print(f"     Response: {raw[:500]}")
                print("\n  → Your token has likely expired. Extract a fresh one:")
                print("    play.qobuz.com → F12 → Application → Local Storage → localuser → token")
                return

            if resp.status != 200:
                print(f"\n  ❌ Unexpected status {resp.status}")
                print(f"     Response: {raw[:500]}")
                return

            try:
                user_data = json.loads(raw)
            except json.JSONDecodeError:
                print(f"\n  ❌ Response is not JSON:\n{raw[:500]}")
                return

        user_id = str(user_data.get("id", ""))
        display_name = user_data.get("display_name", user_data.get("login", "?"))
        print(f"  ✅ Token valid — user_id={user_id}, display_name={display_name!r}\n")

        # ---------------------------------------------------------------
        # Step 2: Playlist fetch
        # ---------------------------------------------------------------
        print("[ 2 ] Fetching playlists ...")
        pl_params = {**params_base, "limit": 10, "offset": 0}
        async with session.get(
            f"{QOBUZ_API_BASE}/playlist/getUserPlaylists",
            params=pl_params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            print(f"      HTTP status: {resp.status}")
            raw_pl = await resp.text()

            if resp.status == 401:
                print("  ❌ Playlist fetch got 401 — token rejected here too")
                print(f"     Response: {raw_pl[:500]}")
                return

            if resp.status != 200:
                print(f"  ⚠️  Status {resp.status}: {raw_pl[:200]}")
            else:
                try:
                    pl_data = json.loads(raw_pl)
                    playlists = (
                        pl_data.get("playlists", {}).get("items", [])
                        or pl_data.get("playlists", [])
                    )
                    print(f"  ✅ Playlists OK — found {len(playlists)} playlist(s)")
                    for pl in playlists[:5]:
                        print(f"     - {pl.get('name', '?')} (id={pl.get('id')})")
                except json.JSONDecodeError:
                    print(f"  ⚠️  Response is not JSON: {raw_pl[:200]}")

        # ---------------------------------------------------------------
        # Step 3: Playback state (optional endpoint)
        # ---------------------------------------------------------------
        print("\n[ 3 ] Checking playback state endpoint ...")
        async with session.get(
            f"{QOBUZ_API_BASE}/player/getState",
            params=params_base,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            print(f"      HTTP status: {resp.status}")
            if resp.status == 200:
                print("  ✅ Playback state endpoint exists")
            elif resp.status == 404:
                print("  ℹ️  Playback state endpoint not found (expected for most accounts)")
            elif resp.status == 401:
                print("  ❌ 401 on playback state — same token issue as above")
            else:
                print(f"  ℹ️  Status {resp.status}")

        print(f"\n{'='*60}")
        print("  Summary: token is working. The integration should function.")
        print(f"{'='*60}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    token = sys.argv[1].strip()
    app_id = (
        sys.argv[2].strip()
        if len(sys.argv) > 2
        else os.environ.get("QOBUZ_APP_ID", "950096963")
    )

    asyncio.run(run(token, app_id))


if __name__ == "__main__":
    main()
