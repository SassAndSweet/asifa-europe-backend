"""
Telegram Signal Source for Europe Conflict Dashboard
v1.0.0 — March 2026

Bridges Telethon (async) with Flask (sync) to pull messages
from monitored Telegram channels and feed them into the
European conflict probability scanner.

Channels monitored:
- Ukraine war channels (Rybar, DeepState, Ukraine NOW)
- NATO/European defense channels
- Azeri/Armenian conflict channels
- OSINT aggregators covering European theatre

Usage:
    from telegram_signals_europe import fetch_europe_telegram_signals
    messages = fetch_europe_telegram_signals(hours_back=24)
    # Returns list of dicts with 'title', 'url', 'published', 'source' keys
"""

import os
import asyncio
import base64
from datetime import datetime, timezone, timedelta

# Telethon import with graceful fallback
try:
    from telethon import TelegramClient
    from telethon.tl.functions.messages import GetHistoryRequest
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    print("[Telegram Europe] ⚠️ telethon not installed — Telegram signals disabled")


# ========================================
# CONFIGURATION
# ========================================

TELEGRAM_API_ID = os.environ.get('TELEGRAM_API_ID')
TELEGRAM_API_HASH = os.environ.get('TELEGRAM_API_HASH')
TELEGRAM_PHONE = os.environ.get('TELEGRAM_PHONE')
SESSION_NAME = 'asifah_session'

# Core European conflict channels
# v1.2.0: Audited April 2026 — removed all dead/invalid channels from logs
EUROPE_CHANNELS = [
    # ── Ukraine war — CONFIRMED WORKING ──────────────────────────
    'DeepStateUA',         # ✅ DeepState Map — Ukrainian front updates (16 msg)
    'mod_russia_en',       # ✅ Russian MoD English (49 msg)
    'C_Military1',         # ✅ Conflict/military OSINT (37 msg)
    'ClashReport',         # ✅ Clash Report — conflict monitoring (47 msg)
    'WarMonitors',         # ✅ War Monitor — multilingual (46 msg)
    'OSINTdefender',       # ✅ OSINT Defender — English, high signal (50 msg)
    'France24_en',         # ✅ France 24 English (50 msg)

    # ── Ukraine war — NEW ADDITIONS (verified active) ─────────────
    'intelslava',          # Intel Slava Z — very active OSINT aggregator
    'wartranslated',       # War Translated — Russian/Ukrainian mil comms EN
    'UkraineNow',          # Ukraine Now — war updates
    'front_ukrainian',     # Ukrainian front OSINT
    'rybar',               # Rybar — primary Russian mil blogger OSINT
    'MiddleEastSpectator', # Cross-theater (ME-Russia links)
    'disclosetv',          # Disclose.tv — breaking conflict news

    # ── Russia domestic signals ───────────────────────────────────
    'currenttime',         # Current Time — RFE/RL Russian service
    'meduzaio',            # Meduza — independent Russian journalism
    'nexta_tv',            # NEXTA — Belarus/Russia opposition

    # ── European / NATO ───────────────────────────────────────────
    'eurointegration',     # European integration news (Ukraine-EU)
    'bbcrussian',          # BBC Russian service
]

# Extended channels — Baltic, Arctic, Poland (v1.2.0 audit)
# Only channels with verified Telegram presence included
EXTENDED_EUROPE_CHANNELS = [
    # ── Caucasus (verified working) ───────────────────────────────
    'ArmenianUnified',     # ✅ Armenian news aggregator (0 msg but exists)

    # ── Arctic / Nordic (verified) ────────────────────────────────
    'arctictoday',         # ✅ Arctic Today (0 msg but exists — slow channel)
    'NorwayMFA',           # ✅ Norwegian MFA (0 msg but exists)

    # ── Additional OSINT (verified active) ────────────────────────
    'militarylandnet',     # Military Land — order of battle tracking
    'UkraineWeaponsTracker', # Ukraine weapons tracking
    'GeoConfirmed',        # GeoConfirmed — geolocation OSINT
    'KyivPost',            # Kyiv Post — English Ukraine news

    # ── Baltic / Eastern Europe ───────────────────────────────────
    'lrtlt',               # LRT Lithuania — Baltic signals
    'latvianpublichroadcasting', # LSM Latvia

    # ── Nuclear / strategic watch ─────────────────────────────────
    'nuclearsecrecy',      # Nuclear Secrecy — arms control/nuclear signals
]

# ── Greenland-specific channel list (v1.1.0) ──
# Used by rhetoric_tracker_greenland.py
# Focuses on U.S. pressure, Danish/NATO response,
# Inuit voice, Russian Arctic opportunism, Nordic OSINT
GREENLAND_CHANNELS = [
    # ── U.S. pressure signals ─────────────────────────────────────
    'CENTCOM',             # ✅ CENTCOM official (confirmed handle)
    'StateDept',           # ✅ State Dept (confirmed working in ME backend)
    # ── Russia Arctic opportunism ─────────────────────────────────
    'mod_russia_en',       # ✅ Russian MoD English (49 msg confirmed)
    'intelslava',          # ✅ Intel Slava — Russia Arctic signals
    # ── Arctic / Nordic OSINT ─────────────────────────────────────
    'arctictoday',         # ✅ Arctic Today (exists, slow channel)
    'NorwayMFA',           # ✅ Norwegian MFA (exists)
    'OSINTdefender',       # ✅ OSINT Defender — high signal (50 msg confirmed)
    'ClashReport',         # ✅ Clash Report — catches Arctic incidents
    # ── General high-signal (catches Greenland mentions) ──────────
    'WarMonitors',         # ✅ War Monitor — multilingual
    'France24_en',         # ✅ France 24 — covers Arctic/NATO stories
]


# ── Russia-specific channel list (v1.2.0) ──
# Used by rhetoric_tracker_russia.py
# Focuses on Russian military ops, Ukraine front,
# nuclear/strategic signals, Baltic/Arctic, domestic Russia
RUSSIA_CHANNELS = [
    # ── Russian military / MoD ────────────────────────────────────
    'mod_russia_en',       # ✅ Russian MoD English (49 msg confirmed)
    'rybar',               # ✅ Rybar — primary Russian mil blogger
    'intelslava',          # ✅ Intel Slava Z — very active OSINT
    # ── Ukraine front ────────────────────────────────────────────
    'DeepStateUA',         # ✅ DeepState Map — front updates (16 msg)
    'wartranslated',       # War Translated — Russian/Ukrainian mil comms EN
    'front_ukrainian',     # Ukrainian front OSINT
    'OSINTdefender',       # ✅ OSINT Defender (50 msg confirmed)
    'ClashReport',         # ✅ Clash Report (47 msg confirmed)
    'WarMonitors',         # ✅ War Monitor (46 msg confirmed)
    'C_Military1',         # ✅ Conflict OSINT (37 msg confirmed)
    # ── Russia domestic / opposition ──────────────────────────────
    'meduzaio',            # Meduza — independent Russian journalism
    'nexta_tv',            # NEXTA — Belarus/Russia opposition
    'currenttime',         # Current Time — RFE/RL Russian service
    # ── Nuclear / strategic ───────────────────────────────────────
    'nuclearsecrecy',      # Nuclear Secrecy — arms control signals
    # ── Arctic / NATO flank ───────────────────────────────────────
    'arctictoday',         # Arctic Today — Northern Fleet/Arctic signals
    'NorwayMFA',           # Norwegian MFA — Arctic/NATO flank
    # ── Cross-theater (ME-Russia links) ───────────────────────────
    'MiddleEastSpectator', # ME-Russia axis signals
]


def fetch_greenland_telegram_signals(hours_back=48):
    """
    Fetch Telegram signals for Greenland sovereignty rhetoric tracker.
    Uses 48h window — Greenland moves slower than active warzones.
    """
    if not _telegram_available():
        print("[Telegram Greenland] Signals unavailable — skipping")
        return []
    try:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _async_fetch_messages(GREENLAND_CHANNELS, hours_back))
                return future.result(timeout=120)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_async_fetch_messages(GREENLAND_CHANNELS, hours_back))
            finally:
                loop.close()
    except Exception as e:
        print(f"[Telegram Greenland] ❌ fetch error: {str(e)[:200]}")
        return []


def fetch_russia_telegram_signals(hours_back=168):
    """
    Fetch Telegram signals for Russia rhetoric tracker.
    Uses 168h (7 day) window — matches Russia tracker scan interval
    and captures slower-moving strategic signals like nuclear/Arctic.
    """
    if not _telegram_available():
        print("[Telegram Russia] Signals unavailable — skipping")
        return []
    try:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _async_fetch_messages(RUSSIA_CHANNELS, hours_back))
                return future.result(timeout=120)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_async_fetch_messages(RUSSIA_CHANNELS, hours_back))
            finally:
                loop.close()
    except Exception as e:
        print(f"[Telegram Russia] ❌ fetch error: {str(e)[:200]}")
        return []


def _telegram_available():
    """Check if Telegram integration is fully configured."""
    if not TELETHON_AVAILABLE:
        return False
    if not all([TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE]):
        print("[Telegram Europe] ⚠️ Missing environment variables")
        return False
    return True


def _ensure_session_file():
    """Decode session file from base64 env var if needed."""
    session_path = f'{SESSION_NAME}.session'
    if os.path.exists(session_path):
        return True

    session_b64 = os.environ.get('TELEGRAM_SESSION_BASE64')
    if session_b64:
        try:
            session_data = base64.b64decode(session_b64)
            with open(session_path, 'wb') as f:
                f.write(session_data)
            print(f"[Telegram Europe] ✅ Session file decoded ({len(session_data)} bytes)")
            return True
        except Exception as e:
            print(f"[Telegram Europe] ❌ Session decode error: {str(e)[:100]}")
            return False

    print("[Telegram Europe] ⚠️ No session file and no TELEGRAM_SESSION_BASE64 env var")
    return False


async def _async_fetch_messages(channels, hours_back=24):
    """
    Async function to fetch messages from Telegram channels.
    Returns list of messages compatible with Europe backend article format.
    """
    if not _ensure_session_file():
        return []

    messages = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    try:
        client = TelegramClient(SESSION_NAME, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            print("[Telegram Europe] ❌ Session not authorized")
            await client.disconnect()
            return []

        print(f"[Telegram Europe] ✅ Connected, fetching from {len(channels)} channels...")

        for channel in channels:
            try:
                entity = await client.get_entity(channel)
                history = await client(GetHistoryRequest(
                    peer=entity,
                    limit=50,
                    offset_date=None,
                    offset_id=0,
                    max_id=0,
                    min_id=0,
                    add_offset=0,
                    hash=0
                ))

                channel_count = 0
                for msg in history.messages:
                    if msg.date and msg.date.replace(tzinfo=timezone.utc) > since and msg.message:
                        messages.append({
                            'title': msg.message[:200],
                            'url': f'https://t.me/{channel}/{msg.id}',
                            'published': msg.date.replace(tzinfo=timezone.utc).isoformat(),
                            'query': f'telegram_{channel}',
                            'source': f'Telegram @{channel}',
                            'views': getattr(msg, 'views', 0) or 0,
                            'forwards': getattr(msg, 'forwards', 0) or 0,
                        })
                        channel_count += 1

                print(f"[Telegram Europe] @{channel}: {channel_count} messages (last {hours_back}h)")

            except Exception as e:
                print(f"[Telegram Europe] @{channel} error: {str(e)[:100]}")
                continue

        await client.disconnect()
        print(f"[Telegram Europe] ✅ Total: {len(messages)} messages from {len(channels)} channels")

    except Exception as e:
        print(f"[Telegram Europe] ❌ Connection error: {str(e)[:200]}")
        try:
            await client.disconnect()
        except:
            pass

    return messages


def fetch_europe_telegram_signals(hours_back=24, include_extended=True):
    """
    Synchronous wrapper to fetch European Telegram messages.

    Args:
        hours_back: How many hours back to fetch (default 24)
        include_extended: Whether to include extended channel list (Caucasus, Baltic, etc.)

    Returns:
        List of dicts with keys: title, url, published, query, source, views, forwards
    """
    if not _telegram_available():
        print("[Telegram Europe] Signals unavailable — skipping")
        return []

    channels = EUROPE_CHANNELS.copy()
    if include_extended:
        channels.extend(EXTENDED_EUROPE_CHANNELS)

    # Bridge async to sync
    try:
        try:
            loop = asyncio.get_running_loop()
            print("[Telegram Europe] ⚠️ Event loop already running — using thread")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _async_fetch_messages(channels, hours_back))
                return future.result(timeout=120)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_async_fetch_messages(channels, hours_back))
            finally:
                loop.close()
    except Exception as e:
        print(f"[Telegram Europe] ❌ fetch error: {str(e)[:200]}")
        return []


def get_europe_telegram_status():
    """Return status info for health check / debugging."""
    return {
        'telethon_installed': TELETHON_AVAILABLE,
        'api_configured': bool(TELEGRAM_API_ID and TELEGRAM_API_HASH),
        'phone_configured': bool(TELEGRAM_PHONE),
        'session_available': os.path.exists(f'{SESSION_NAME}.session') or bool(os.environ.get('TELEGRAM_SESSION_BASE64')),
        'core_channels': EUROPE_CHANNELS,
        'extended_channels': EXTENDED_EUROPE_CHANNELS,
        'ready': _telegram_available() and (os.path.exists(f'{SESSION_NAME}.session') or bool(os.environ.get('TELEGRAM_SESSION_BASE64')))
    }
