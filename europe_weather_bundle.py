"""
═══════════════════════════════════════════════════════════════════════
 ASIFAH ANALYTICS · EUROPE BACKEND · WEATHER BUNDLE MODULE v1.0.0
 April 2026
═══════════════════════════════════════════════════════════════════════

 PURPOSE
 -------
 Replaces 9 parallel external calls to api.open-meteo.com from the
 frontend with a single cached bundle call to the Europe backend.

 BEFORE:
   europe.html landing fires 9 calls → open-meteo.com (no caching)
   → every user eats 9 external round trips

 AFTER:
   europe.html landing fires 1 call → /api/europe/weather (Redis-cached)
   → 9 external calls happen once per hour, server-side
   → users eat a single sub-100ms Redis-backed response

 DESIGN NOTES
 ------------
 This module mirrors app.py's existing patterns:
   - Same Upstash REST style: json={"value": payload} for SET
   - Same age-based freshness check via `cached_at` timestamp
   - Same env var names (UPSTASH_REDIS_URL / UPSTASH_REDIS_TOKEN)
   - Same log prefix convention
   - register_*_endpoints(app) + start_*_refresh() pattern

═══════════════════════════════════════════════════════════════════════
"""

import json
import os
import threading
import time
from datetime import datetime, timezone

import requests
from flask import jsonify, request


# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

# 12 European/Central Asian capitals — MUST match WEATHER_CAPITALS in europe.html
WEATHER_CAPITALS = {
    'armenia':      {'name': 'Yerevan',   'lat': 40.19, 'lon':  44.52},
    'azerbaijan':   {'name': 'Baku',      'lat': 40.41, 'lon':  49.87},
    'belarus':      {'name': 'Minsk',     'lat': 53.90, 'lon':  27.57},
    'cyprus':       {'name': 'Nicosia',   'lat': 35.17, 'lon':  33.36},
    'greenland':    {'name': 'Nuuk',      'lat': 64.17, 'lon': -51.74},
    'hungary':      {'name': 'Budapest',  'lat': 47.49, 'lon':  19.04},
    'kazakhstan':   {'name': 'Astana',    'lat': 51.17, 'lon':  71.45},
    'poland':       {'name': 'Warsaw',    'lat': 52.23, 'lon':  21.01},
    'russia':       {'name': 'Moscow',    'lat': 55.75, 'lon':  37.62},
    'turkey':       {'name': 'Ankara',    'lat': 39.93, 'lon':  32.86},
    'turkmenistan': {'name': 'Ashgabat',  'lat': 37.96, 'lon':  58.38},
    'ukraine':      {'name': 'Kyiv',      'lat': 50.45, 'lon':  30.52},
}

WEATHER_REDIS_KEY  = 'europe_weather_bundle'
WEATHER_CACHE_TTL  = 60 * 60              # 1 hour (age check)
REFRESH_INTERVAL   = 50 * 60              # Refresh every 50 min (before TTL expires)
BOOT_DELAY         = 90                   # Defer first scan 90s after boot
OPEN_METEO_TIMEOUT = (5, 15)              # (connect, read) seconds
INTER_CALL_PAUSE   = 0.2                  # Polite pause between open-meteo calls

# Env vars — same names as app.py
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')


# ═══════════════════════════════════════════════════════════════════════
# REDIS HELPERS — mirrors app.py's load_X_cache_redis / save_X_cache_redis style
# ═══════════════════════════════════════════════════════════════════════

def load_weather_cache_redis():
    """Load weather bundle from Upstash Redis. Returns dict or None."""
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{WEATHER_REDIS_KEY}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get("result"):
                cache = json.loads(data["result"])
                return cache
        except Exception as e:
            print(f"[Weather Bundle] Redis load error: {e}", flush=True)
    return None


def save_weather_cache_redis(data):
    """Save weather bundle to Upstash Redis."""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            payload = json.dumps(data, default=str)
            resp = requests.post(
                f"{UPSTASH_REDIS_URL}/set/{WEATHER_REDIS_KEY}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"value": payload},
                timeout=10
            )
            if resp.status_code == 200:
                print(f"[Weather Bundle] ✅ Saved bundle to Redis ({data.get('ok_count','?')}/{data.get('total_count','?')} capitals)", flush=True)
            else:
                print(f"[Weather Bundle] Redis save HTTP {resp.status_code}", flush=True)
        except Exception as e:
            print(f"[Weather Bundle] Redis save error: {e}", flush=True)


def is_weather_cache_fresh():
    """Check if Redis cache exists and is under TTL. Returns (fresh_bool, cache_or_None).
    Note: returns stale cache as fallback — caller can use it or force rebuild."""
    cached = load_weather_cache_redis()
    if not cached or 'cached_at' not in cached:
        return False, None
    try:
        cached_at = datetime.fromisoformat(cached['cached_at'])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age < WEATHER_CACHE_TTL:
            return True, cached
        print(f"[Weather Bundle] Cache stale ({age/60:.0f}min old)", flush=True)
    except Exception as e:
        print(f"[Weather Bundle] Freshness check error: {e}", flush=True)
    return False, cached  # Return stale cache as fallback


# ═══════════════════════════════════════════════════════════════════════
# OPEN-METEO FETCH
# ═══════════════════════════════════════════════════════════════════════

def _fetch_single_capital(target, cap):
    """
    Fetch 7-day forecast for a single capital from open-meteo.
    Returns the raw open-meteo JSON (shape europe.html's renderer expects)
    or None on failure.
    """
    url = 'https://api.open-meteo.com/v1/forecast'
    params = {
        'latitude':      cap['lat'],
        'longitude':     cap['lon'],
        'daily':         'weather_code,temperature_2m_max,temperature_2m_min',
        'timezone':      'auto',
        'forecast_days': 7,
    }
    try:
        resp = requests.get(url, params=params, timeout=OPEN_METEO_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        print(f"[Weather Bundle] Open-Meteo {target} returned HTTP {resp.status_code}", flush=True)
    except Exception as e:
        print(f"[Weather Bundle] Open-Meteo {target} fetch error: {e}", flush=True)
    return None


def _fetch_all_capitals():
    """Fetch all 9 capitals sequentially with small pauses.
    Returns dict keyed by target with raw open-meteo payload (or None)."""
    results = {}
    for target, cap in WEATHER_CAPITALS.items():
        results[target] = _fetch_single_capital(target, cap)
        time.sleep(INTER_CALL_PAUSE)
    return results


# ═══════════════════════════════════════════════════════════════════════
# BUNDLE ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════

def build_fresh_bundle():
    """Fetch fresh weather for all capitals and save to Redis."""
    print("[Weather Bundle] Refreshing fresh bundle from open-meteo...", flush=True)
    start = time.time()
    capitals = _fetch_all_capitals()
    elapsed = round(time.time() - start, 2)

    ok_count = sum(1 for v in capitals.values() if v is not None)
    print(f"[Weather Bundle] Fresh bundle: {ok_count}/{len(WEATHER_CAPITALS)} capitals OK in {elapsed}s", flush=True)

    bundle = {
        'success':       True,
        'capitals':      capitals,
        'scan_seconds':  elapsed,
        'ok_count':      ok_count,
        'total_count':   len(WEATHER_CAPITALS),
    }
    save_weather_cache_redis(bundle)
    return bundle


def get_weather_bundle(force=False):
    """
    Return the cached weather bundle.
    - force=True  → rebuild unconditionally
    - force=False → use fresh cache if available; rebuild only if missing/stale
    """
    if not force:
        fresh, cached = is_weather_cache_fresh()
        if fresh and cached:
            return cached
    return build_fresh_bundle()


# ═══════════════════════════════════════════════════════════════════════
# BACKGROUND REFRESH DAEMON
# ═══════════════════════════════════════════════════════════════════════

_refresh_started = False
_refresh_lock    = threading.Lock()


def _refresh_loop():
    """Daemon thread: refreshes the cache every REFRESH_INTERVAL seconds."""
    time.sleep(BOOT_DELAY)  # Let app.py's existing boot sequence run first
    while True:
        try:
            build_fresh_bundle()
        except Exception as e:
            print(f"[Weather Bundle] Refresh loop error: {e}", flush=True)
        time.sleep(REFRESH_INTERVAL)


def start_weather_refresh():
    """Kick off the background refresh thread (idempotent)."""
    global _refresh_started
    with _refresh_lock:
        if _refresh_started:
            return
        _refresh_started = True
    t = threading.Thread(target=_refresh_loop, name='europe-weather-refresh', daemon=True)
    t.start()
    print(f"[Weather Bundle] Background refresh started ({BOOT_DELAY}s boot delay, {REFRESH_INTERVAL//60}min interval)", flush=True)


# ═══════════════════════════════════════════════════════════════════════
# FLASK ENDPOINT REGISTRATION
# ═══════════════════════════════════════════════════════════════════════

def register_weather_endpoints(app):
    """
    Register /api/europe/weather on the provided Flask app.

    Usage in app.py:
        from europe_weather_bundle import register_weather_endpoints
        register_weather_endpoints(app)
    """
    from flask_cors import cross_origin  # same decorator used throughout app.py

    @app.route('/api/europe/weather', methods=['GET', 'OPTIONS'])
    @cross_origin()
    def europe_weather_bundle_endpoint():
        """Return cached weather for all 9 European capitals in one call."""
        if request.method == 'OPTIONS':
            return '', 200

        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        # Serve from cache if fresh — skip rebuild on user-triggered landings
        if not force:
            fresh, cached = is_weather_cache_fresh()
            if fresh and cached:
                resp = jsonify(cached)
                resp.headers['Cache-Control'] = 'public, max-age=600'
                return resp

        # Cache miss or force: synchronous rebuild. The background thread
        # keeps this warm, so this path usually only hits on first boot or
        # manual force refresh.
        bundle = get_weather_bundle(force=force)
        resp = jsonify(bundle)
        resp.headers['Cache-Control'] = 'public, max-age=600'
        return resp

    print("[Weather Bundle] ✅ Endpoint registered: GET /api/europe/weather", flush=True)


# ═══════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("[Weather Bundle] Test run — fetching all capitals...")
    bundle = build_fresh_bundle()
    print(json.dumps({
        'ok_count':   bundle['ok_count'],
        'total':      bundle['total_count'],
        'elapsed_s':  bundle['scan_seconds'],
        'sample':     list(bundle['capitals'].keys())[:3],
    }, indent=2))
