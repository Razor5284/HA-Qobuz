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

For /qws/createToken, the web player sends form field ``jwt=jwt_qws`` (literal
string) plus ``app_id``; your session token is only in ``X-User-Auth-Token``.

The app_id defaults to QOBUZ_APP_ID. You can also set QOBUZ_APP_ID as an env var.

Requirements:
    pip install aiohttp
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

# Fallback app_id used if scraping fails. Kept in sync with const.py manually.
_FALLBACK_APP_ID = "798273057"

QOBUZ_API_BASE = "https://www.qobuz.com/api.json/0.2"
_HEADER_APP_ID = "X-App-Id"
_HEADER_AUTH_TOKEN = "X-User-Auth-Token"


def _mask(s: str, keep: int = 8) -> str:
    if not s or len(s) <= keep:
        return "***"
    return s[:keep] + "..." + s[-4:]


async def scrape_app_id(session: Any) -> str:
    """Scrape the live app_id from the Qobuz web player bundle."""
    import re

    try:
        async with session.get("https://play.qobuz.com/login") as resp:
            html = await resp.text()
        m = re.search(r'<script src="(/resources/[\d.\-a-z]+/bundle\.js)"></script>', html)
        if not m:
            return _FALLBACK_APP_ID
        async with session.get(f"https://play.qobuz.com{m.group(1)}") as resp:
            bundle = await resp.text()
        am = re.search(r'production:\{api:\{appId:"(?P<app_id>\d{9})"', bundle)
        return am.group("app_id") if am else _FALLBACK_APP_ID
    except Exception:  # noqa: BLE001
        return _FALLBACK_APP_ID


async def run(token: str, app_id: str | None) -> None:
    import aiohttp

    async with aiohttp.ClientSession() as session:
        if not app_id:
            print("[ 0 ] Scraping live app_id from Qobuz web player ...")
            app_id = await scrape_app_id(session)
            print(f"      app_id: {app_id}\n")

        print(f"\n{'='*60}")
        print("  Qobuz API test")
        print(f"  token:  {_mask(token)}")
        print(f"  app_id: {app_id}")
        print(f"{'='*60}\n")

        headers = {_HEADER_APP_ID: app_id, _HEADER_AUTH_TOKEN: token}
        params_base = {"app_id": app_id, "user_auth_token": token}

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
        # Step 3: Playback state (optional endpoint — often broken server-side)
        # ---------------------------------------------------------------
        print("\n[ 3 ] Checking REST playback endpoint (/player/getState) ...")
        async with session.get(
            f"{QOBUZ_API_BASE}/player/getState",
            params=params_base,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            print(f"      HTTP status: {resp.status}")
            if resp.status == 200:
                print("  ✅ REST playback state returned (unusual but valid)")
            elif resp.status == 404:
                print("  ℹ️  Not found — common; Home Assistant uses Qobuz Connect instead")
            elif resp.status == 503:
                print(
                    "  ℹ️  503 Service Unavailable — common for this endpoint; "
                    "not a token or subscription problem."
                )
                print(
                    "     The integration does not rely on this for now-playing; "
                    "it uses Qobuz Connect (WebSocket) when /qws/createToken succeeds."
                )
            elif resp.status == 401:
                print("  ❌ 401 on playback state — same token issue as above")
            else:
                print(f"  ℹ️  Status {resp.status} (REST playback may be unavailable)")

        # ---------------------------------------------------------------
        # Step 4: Qobuz Connect token (what HA uses for multi-device control)
        # ---------------------------------------------------------------
        print("\n[ 4 ] Checking Qobuz Connect token (/qws/createToken, POST) ...")
        ua_headers = {
            _HEADER_APP_ID: app_id,
            _HEADER_AUTH_TOKEN: token,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-us,en;q=0.9",
            "Origin": "https://play.qobuz.com",
            "Referer": "https://play.qobuz.com/",
        }
        # Web player: POST body jwt=jwt_qws (literal) + app_id; session = X-User-Auth-Token only.
        post_body = {"app_id": app_id, "jwt": "jwt_qws"}
        async with session.post(
            f"{QOBUZ_API_BASE}/qws/createToken",
            headers=ua_headers,
            data=post_body,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            raw_ct = await resp.text()
            print(
                f"      HTTP status: {resp.status} "
                "(POST body: app_id + jwt=jwt_qws; session token in X-User-Auth-Token only)"
            )
            if resp.status == 200:
                try:
                    data_ct = json.loads(raw_ct)
                except json.JSONDecodeError:
                    print(f"  ⚠️  Response is not JSON: {raw_ct[:200]}")
                else:
                    nested = data_ct.get("jwt_qws")
                    if isinstance(nested, dict):
                        jwt_preview = nested.get("jwt") or nested.get("token")
                        ep = nested.get("endpoint") or nested.get("url")
                    else:
                        jwt_preview = data_ct.get("jwt") or data_ct.get("token")
                        ep = data_ct.get("endpoint") or data_ct.get("url")
                    if jwt_preview:
                        print("  ✅ createToken OK — Qobuz Connect WebSocket should be available")
                        print(f"     endpoint: {ep or '(default)'}")
                        print(f"     jwt: {_mask(str(jwt_preview), keep=12)}")
                    else:
                        print(f"  ⚠️  200 but no jwt in payload: {str(data_ct)[:300]}")
            elif resp.status == 401:
                print("  ❌ createToken 401 — token rejected for Connect")
            else:
                print(f"  ⚠️  createToken failed — Connect features need this (response: {raw_ct[:200]})")

        print(f"\n{'='*60}")
        print("  Summary: if [1] and [2] pass, your token and catalogue API work.")
        print("  For playback on other devices, [4] should be 200 with a jwt.")
        print(f"{'='*60}\n")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    token = sys.argv[1].strip()
    # If a second arg or env var is given use it; otherwise scrape live value
    app_id: str | None = (
        sys.argv[2].strip() if len(sys.argv) > 2
        else os.environ.get("QOBUZ_APP_ID")  # None → will scrape
    )

    asyncio.run(run(token, app_id))


if __name__ == "__main__":
    main()
