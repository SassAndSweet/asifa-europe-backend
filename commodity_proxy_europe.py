"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — EUROPE BACKEND COMMODITY PROXY
  v1.0.0 (Apr 30 2026)
═══════════════════════════════════════════════════════════════════════

Thin proxy layer that fetches commodity-pressure data from the ME
backend (where commodity_tracker.py lives), caches it in Europe's
Upstash Redis with a 12-hour TTL, and exposes Europe-native endpoints
for stability page consumption.

ARCHITECTURE:
  Frontend (belarus-stability.html, ukraine-stability.html, etc.)
    └─→ Europe backend /api/europe/commodity/<target>
          └─→ Europe Redis cache (12hr TTL)
                └─[on miss]─→ ME backend /api/commodity-pressure/<target>
                                └─→ Europe Redis (write-through)

WHY 12 HOURS:
  - Commodity exposure data (production rank, role, weight) is structural —
    doesn't change daily.
  - News signal counts inside the commodity_summaries[] update slowly enough
    that 12h freshness is fine for stability-page context.
  - Reduces ME backend load to 2 calls/day per supported target.

TARGETS SUPPORTED:
  Whatever ME backend's COUNTRY_COMMODITY_EXPOSURE has registered.
  Phase 1: belarus, russia, china, israel, ukraine.
  When ME backend extends the dict, this proxy automatically supports
  the new countries (no Europe code change required).

ENDPOINTS REGISTERED:
  GET /api/europe/commodity/<target>            — single country, cached
  GET /api/europe/commodity/<target>?force=true — bypass Europe cache
  GET /api/europe/commodity-debug               — proxy status diagnostic

USAGE FROM app.py:
    from commodity_proxy_europe import register_commodity_proxy
    register_commodity_proxy(app)
"""

import os
import json
import time
import threading
import requests
from datetime import datetime, timezone
from flask import jsonify, request

# ────────────────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────────────────

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

# ME backend lives at this address (per project memory).
# Override with env var if needed for staging environments.
ME_BACKEND_URL = os.environ.get(
    'ME_BACKEND_URL',
    'https://asifah-backend.onrender.com'
)

# 12-hour TTL per project requirement (commodity exposure is structural).
COMMODITY_CACHE_TTL_SECONDS = 12 * 3600

# Per-target Redis key namespace.
def _redis_key(target):
    return f"europe:commodity:{target.lower()}"


# ────────────────────────────────────────────────────────────
# REDIS CACHE HELPERS
# ────────────────────────────────────────────────────────────

def _load_from_redis(target):
    """Load cached commodity data for a target from Upstash Redis."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{_redis_key(target)}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5
        )
        data = resp.json()
        if data.get("result"):
            return json.loads(data["result"])
    except Exception as e:
        print(f"[Commodity Proxy] Redis load error for {target}: {e}")
    return None


def _save_to_redis(target, payload):
    """Save commodity data to Upstash Redis."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        payload = dict(payload)
        payload['proxy_cached_at'] = datetime.now(timezone.utc).isoformat()
        body = json.dumps(payload, default=str)
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/set/{_redis_key(target)}",
            headers={
                "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                "Content-Type":  "application/json"
            },
            json={"value": body},
            timeout=10
        )
        if resp.status_code == 200:
            print(f"[Commodity Proxy] ✅ Cached {target} in Europe Redis")
            return True
        else:
            print(f"[Commodity Proxy] Redis save HTTP {resp.status_code} for {target}")
    except Exception as e:
        print(f"[Commodity Proxy] Redis save error for {target}: {e}")
    return False


def _is_cache_fresh(cached):
    """Check if cached entry is still within TTL."""
    if not cached or 'proxy_cached_at' not in cached:
        return False
    try:
        cached_at = datetime.fromisoformat(cached['proxy_cached_at'])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        return age < COMMODITY_CACHE_TTL_SECONDS
    except Exception:
        return False


# ────────────────────────────────────────────────────────────
# UPSTREAM FETCH (ME BACKEND)
# ────────────────────────────────────────────────────────────

def _fetch_from_me_backend(target):
    """Fetch fresh commodity-pressure data from the ME backend."""
    try:
        url = f"{ME_BACKEND_URL}/api/commodity-pressure/{target.lower()}"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"[Commodity Proxy] ME backend returned HTTP {resp.status_code} for {target}")
            return None
        return resp.json()
    except Exception as e:
        print(f"[Commodity Proxy] ME backend fetch error for {target}: {e}")
        return None


# ────────────────────────────────────────────────────────────
# CORE PROXY FUNCTION
# ────────────────────────────────────────────────────────────

def get_commodity_data(target, force=False):
    """
    Three-layer cascade:
      1. Europe Redis cache fresh? → return it.
      2. Otherwise → fetch from ME backend, write-through cache, return.
      3. ME backend unavailable AND we have stale cache? → return stale with flag.
      4. Nothing available → return placeholder.
    """
    target = (target or '').lower().strip()
    if not target:
        return {
            'success':            False,
            'error':              'Target required',
            'commodity_pressure': 0,
            'commodity_summaries': [],
        }

    # Layer 1: cache check (unless forced)
    if not force:
        cached = _load_from_redis(target)
        if cached and _is_cache_fresh(cached):
            cached['cache_status'] = 'hit'
            return cached

    # Layer 2: live fetch from ME backend
    fresh = _fetch_from_me_backend(target)
    if fresh and fresh.get('success', True) is not False:
        # Write-through cache (with proxy_cached_at stamp)
        _save_to_redis(target, fresh)
        fresh['cache_status'] = 'miss-fetched'
        return fresh

    # Layer 3: ME backend unavailable — fall back to stale cache if any
    stale = _load_from_redis(target) if not force else None
    if stale:
        stale['cache_status'] = 'stale-fallback'
        stale['warning']      = 'ME backend unavailable; serving stale cache'
        return stale

    # Layer 4: nothing available — empty placeholder
    return {
        'success':              True,
        'country':              target,
        'commodity_pressure':   0,
        'alert_level':          'normal',
        'commodity_summaries':  [],
        'top_signals':          [],
        'message':              'Commodity data not yet available. First scan pending.',
        'cache_status':         'empty',
    }


# ────────────────────────────────────────────────────────────
# BACKGROUND REFRESH WORKER
# ────────────────────────────────────────────────────────────

# List of targets to proactively refresh in the background. Anything in
# this list gets a fresh pull from ME every 12h so users never see a
# slow first-load. Add new countries here as their stability pages ship.
PROACTIVE_REFRESH_TARGETS = ['belarus', 'kazakhstan', 'russia', 'turkmenistan', 'ukraine']

_refresh_lock = threading.Lock()
_last_refresh = {}  # target -> unix timestamp


def _background_refresh_loop():
    """
    Background daemon: every hour, check if any cached target is older
    than 12h and refresh it from ME backend if so. Spreads load across
    targets so we don't hit ME backend with a thundering herd.
    """
    # Initial delay so backend boot completes first
    time.sleep(120)  # 2 minute warm-up

    while True:
        try:
            for target in PROACTIVE_REFRESH_TARGETS:
                with _refresh_lock:
                    last = _last_refresh.get(target, 0)
                    age  = time.time() - last
                # If we've never refreshed OR it's been > 12h, do it now
                if age > COMMODITY_CACHE_TTL_SECONDS:
                    print(f"[Commodity Proxy] Background refresh: {target}")
                    fresh = _fetch_from_me_backend(target)
                    if fresh:
                        _save_to_redis(target, fresh)
                        with _refresh_lock:
                            _last_refresh[target] = time.time()
                    # Brief pause between targets so we don't hammer ME
                    time.sleep(3)
            # Check every hour
            time.sleep(3600)
        except Exception as e:
            print(f"[Commodity Proxy] Background loop error: {e}")
            time.sleep(600)  # back off 10 min on error


def _start_background_worker():
    t = threading.Thread(target=_background_refresh_loop, daemon=True)
    t.start()
    print("[Commodity Proxy] ✅ Background refresh worker started (12h cadence)")


# ────────────────────────────────────────────────────────────
# FLASK ENDPOINT REGISTRATION
# ────────────────────────────────────────────────────────────

def register_commodity_proxy(app, start_background=True):
    """
    Register commodity proxy endpoints on the given Flask app.
    Call from app.py: register_commodity_proxy(app)
    """

    @app.route('/api/europe/commodity/<target>', methods=['GET', 'OPTIONS'])
    def api_europe_commodity_target(target):
        """Single-country commodity exposure for stability pages."""
        if request.method == 'OPTIONS':
            return '', 200
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            data  = get_commodity_data(target, force=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   str(e)[:200],
                'country': target,
            }), 500

    @app.route('/api/europe/commodity-debug', methods=['GET'])
    def api_europe_commodity_debug():
        """Diagnostic — what's cached, how old, ME backend reachability."""
        debug = {
            'version':                  '1.0.0',
            'me_backend_url':           ME_BACKEND_URL,
            'cache_ttl_hours':          COMMODITY_CACHE_TTL_SECONDS / 3600,
            'proactive_targets':        PROACTIVE_REFRESH_TARGETS,
            'redis_configured':         bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN),
            'cached_targets':           {},
        }
        for tgt in PROACTIVE_REFRESH_TARGETS:
            cached = _load_from_redis(tgt)
            if cached:
                debug['cached_targets'][tgt] = {
                    'cached_at':       cached.get('proxy_cached_at'),
                    'fresh':           _is_cache_fresh(cached),
                    'commodity_count': len(cached.get('commodity_summaries', [])),
                    'pressure_score':  cached.get('commodity_pressure'),
                }
            else:
                debug['cached_targets'][tgt] = None
        # ME reachability ping
        try:
            r = requests.get(f"{ME_BACKEND_URL}/api/commodity-debug", timeout=5)
            debug['me_backend_reachable'] = (r.status_code == 200)
        except Exception:
            debug['me_backend_reachable'] = False
        return jsonify(debug)

    if start_background:
        _start_background_worker()

    print("[Commodity Proxy] ✅ Endpoints registered: /api/europe/commodity/<target>, /api/europe/commodity-debug")
