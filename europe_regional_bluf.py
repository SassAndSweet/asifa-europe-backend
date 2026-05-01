"""
europe_regional_bluf.py
Asifah Analytics -- Europe Backend Module
v1.0.0 -- April 2026

Europe Regional BLUF (Bottom Line Up Front) Engine.

Reads from Europe rhetoric tracker Redis caches and synthesizes a single
analyst-prose BLUF paragraph + top-5 structured top-line signals.

Architecture mirrors me_regional_bluf.py v2.0 + asia_regional_bluf.py v2.1
+ wha_regional_bluf.py v1.0 (proven canonical pattern).

Currently active trackers:
  - Russia    (rhetoric:russia:latest)    -- 5-vector model + green/diplomatic
  - Greenland (rhetoric:greenland:latest) -- inverted-rhetoric arctic tracker

Roadmap (slot in via TRACKER_KEYS as they come online):
  - Ukraine
  - Hungary
  - Poland
  - Baltic states (LT/LV/EE composite or separate)

v1.0.0 design choices:
- Trackers use ME pattern: result['interpretation'] wraps so_what / red_lines.
  Compatibility shim normalizes that AND v2.0+ self-emitted top_signals[].
- Output emits canonical fields (top_signals, max_level, theatre_summary,
  region: 'europe') for direct GPI consumption.
- Top 5 signals per region (matches ME, Asia, WHA).
- Europe-specific cross-tracker signal: arctic_convergence (Russia arctic_level
  + Greenland sovereignty crisis simultaneously) + nuclear_signaling alert.
- Score derivation hierarchy: theatre_score → rhetoric_score → overall_score
  → threat_level × 20 fallback.

Author: RCGG / Asifah Analytics
"""

import os
import json
import traceback
from datetime import datetime, timezone
import requests


# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL', '')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN', '')

# Source caches (written by respective trackers)
TRACKER_KEYS = {
    'russia':    'rhetoric:russia:latest',
    'greenland': 'rhetoric:greenland:latest',
    'ukraine':   'rhetoric:ukraine:latest',
    'belarus':   'rhetoric:belarus:latest',
    # Future Europe trackers slot in here:
    # 'hungary':  'rhetoric:hungary:latest',
    # 'poland':   'rhetoric:poland:latest',
    # 'baltics':  'rhetoric:baltics:latest',
}

THEATRE_FLAGS = {
    'russia':    '\U0001f1f7\U0001f1fa',  # 🇷🇺
    'greenland': '\U0001f1ec\U0001f1f1',  # 🇬🇱
    'ukraine':   '\U0001f1fa\U0001f1e6',  # 🇺🇦
    'belarus':   '\U0001f1e7\U0001f1fe',  # 🇧🇾
    'hungary':   '\U0001f1ed\U0001f1fa',  # 🇭🇺
    'poland':    '\U0001f1f5\U0001f1f1',  # 🇵🇱
    'baltics':   '\U0001f1ea\U0001f1fa',  # 🇪🇺 fallback
}

THEATRE_DISPLAY = {
    'russia':    'RUSSIA',
    'greenland': 'GREENLAND',
    'ukraine':   'UKRAINE',
    'belarus':   'BELARUS',
    'hungary':   'HUNGARY',
    'poland':    'POLAND',
    'baltics':   'BALTICS',
}

# Top-N signals emitted to GPI
TOP_SIGNALS_COUNT = 5

# Synthesis cache
BLUF_CACHE_KEY    = 'rhetoric:europe:regional_bluf'
BLUF_CACHE_TTL    = 14 * 3600    # 14h


# ============================================================
# ESCALATION + INFLUENCE LABELS (canonical)
# ============================================================
ESCALATION_LABELS = {
    0: 'Monitoring',
    1: 'Rhetoric',
    2: 'Warning',
    3: 'Direct Threat',
    4: 'Incident',
    5: 'Active Conflict',
}

ESCALATION_COLORS = {
    0: '#6b7280',
    1: '#3b82f6',
    2: '#f59e0b',
    3: '#f97316',
    4: '#ef4444',
    5: '#dc2626',
}

INFLUENCE_LABELS = {
    0: 'Standby',
    1: 'Engaged',
    2: 'Active',
    3: 'Mediation Engaged',
    4: 'High-Stakes Mediation',
    5: 'Crisis Mediation',
}

INFLUENCE_COLORS = {
    0: '#6b7280',
    1: '#a78bfa',
    2: '#8b5cf6',
    3: '#7c3aed',
    4: '#6d28d9',
    5: '#5b21b6',
}


# ============================================================
# REDIS HELPERS
# ============================================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
        result = resp.json().get('result')
        return json.loads(result) if result else None
    except Exception as e:
        print(f'[Europe BLUF] Redis GET error ({key}): {e}')
        return None


def _redis_set(key, value, ttl=BLUF_CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str)
        params = {'EX': ttl} if ttl else {}
        resp = requests.post(
            f'{UPSTASH_REDIS_URL}/set/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json'
            },
            data=payload,
            params=params,
            timeout=5
        )
        return resp.json().get('result') == 'OK'
    except Exception as e:
        print(f'[Europe BLUF] Redis SET error ({key}): {e}')
        return False


# ============================================================
# SAFE-ACCESS HELPERS
# ============================================================
def _safe_dict(val):
    return val if isinstance(val, dict) else {}

def _safe_list(val):
    return val if isinstance(val, list) else []

def _safe_int(val, default=0):
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default

def _safe_str(val, default=''):
    return str(val) if val is not None else default


# ============================================================
# COMPATIBILITY SHIM -- v1.0
# ============================================================
def _normalize_tracker_data(theatre, raw_data):
    """
    Convert raw Europe tracker cache into canonical shape.
    Russia + Greenland use ME-pattern: result['interpretation'] wraps the
    interpreter output. Both also store top-level theatre_level / theatre_score.
    """
    if not raw_data:
        return None

    flag = THEATRE_FLAGS.get(theatre, '')
    interp = _safe_dict(raw_data.get('interpretation'))
    so_what    = _safe_dict(interp.get('so_what'))
    red_lines  = _safe_dict(interp.get('red_lines'))
    green_lines = _safe_dict(interp.get('green_lines'))
    diplomatic = _safe_dict(interp.get('diplomatic_track'))

    # ---- THREAT LEVEL ----
    threat = _safe_int(raw_data.get('theatre_level',
                       raw_data.get('overall_level',
                       raw_data.get('threat_level', 0))))

    # ---- SCORE ----
    # Russia emits theatre_score natively; Greenland emits theatre_score natively.
    # Fallback: level × 20 if none present.
    score = _safe_int(raw_data.get('theatre_score',
                      raw_data.get('rhetoric_score',
                      raw_data.get('overall_score', 0))))
    if score == 0 and threat:
        score = int(threat) * 20

    # ---- INFLUENCE LEVEL (forward-ready) ----
    influence = raw_data.get('influence_level')

    # ---- DOMINANT AXIS ----
    threat_int    = int(threat or 0)
    influence_int = int(influence or 0)
    dominant_level = max(threat_int, influence_int)
    dominant_axis  = 'influence' if influence_int > threat_int else 'threat'

    # ---- TOP SIGNALS (v2.0+ self-emitted if present; else synthesize) ----
    if 'top_signals' in raw_data and isinstance(raw_data['top_signals'], list):
        top_signals = raw_data['top_signals']
    else:
        top_signals = _synthesize_top_signals_legacy(
            theatre, raw_data, threat_int, score, so_what, red_lines, green_lines
        )

    return {
        'theatre':      theatre,
        'flag':         flag,
        'levels': {
            'threat':         threat_int,
            'influence':      influence_int if influence is not None else None,
            'green':          None,
            'dominant_axis':  dominant_axis,
            'dominant_level': dominant_level,
        },
        'score':        score,
        'so_what':      so_what,
        'red_lines':    red_lines,
        'green_lines':  green_lines,
        'diplomatic_track': diplomatic,
        'top_signals':  top_signals,
        'scanned_at':   _safe_str(raw_data.get('scanned_at') or raw_data.get('timestamp', '')),
        'raw':          raw_data,
    }


def _synthesize_top_signals_legacy(theatre, raw_data, threat_int, score, so_what, red_lines, green_lines):
    """
    Synthesize top_signals[] for trackers not yet upgraded to v2.0+ self-emit.
    """
    flag    = THEATRE_FLAGS.get(theatre, '')
    display = THEATRE_DISPLAY.get(theatre, theatre.upper())
    signals = []

    # Red lines breached (ME pattern: red_lines is a dict with 'triggered' key)
    rl_triggered = _safe_list(red_lines.get('triggered'))
    breached = [r for r in rl_triggered if isinstance(r, dict) and r.get('status') == 'BREACHED']

    for rl in breached[:2]:
        label = _safe_str(rl.get('label', 'Red line'))
        signals.append({
            'priority':   12,
            'category':   'red_line_breached',
            'theatre':    theatre,
            'level':      max(threat_int, 4),
            'icon':       rl.get('icon', '🚨'),
            'color':      '#dc2626',
            'short_text': f'{flag} {display}: BREACH — {label[:55]}',
            'long_text':  f'{flag} {display} red line breached at L{threat_int}: {label}',
        })

    # Theatre-high
    if threat_int >= 4:
        signals.append({
            'priority':   9 + threat_int,
            'category':   'theatre_high',
            'theatre':    theatre,
            'level':      threat_int,
            'icon':       '🔴',
            'color':      ESCALATION_COLORS.get(threat_int, '#6b7280'),
            'short_text': f'{flag} {display} L{threat_int} — {ESCALATION_LABELS.get(threat_int, "")}',
            'long_text':  f'{flag} {display} at L{threat_int} {ESCALATION_LABELS.get(threat_int, "")} (score {score}/100)',
        })

    # Russia-specific legacy fallbacks
    if theatre == 'russia':
        nuclear = _safe_int(raw_data.get('nuclear_level'))
        if nuclear >= 3:
            signals.append({
                'priority':   10 + (nuclear - 3),
                'category':   'nuclear_signaling',
                'theatre':    'russia',
                'level':      nuclear,
                'icon':       '☢️',
                'color':      '#dc2626' if nuclear >= 4 else '#ef4444',
                'short_text': f'{flag} RUSSIA: Nuclear signaling L{nuclear}',
                'long_text':  f'RUSSIA nuclear signaling L{nuclear} — coercion threshold elevated.',
            })

    # Greenland-specific legacy fallbacks
    if theatre == 'greenland':
        us_level = _safe_int(raw_data.get('us_pressure_level'))
        if us_level >= 3:
            signals.append({
                'priority':   8,
                'category':   'us_pressure_high',
                'theatre':    'greenland',
                'level':      us_level,
                'icon':       '🦅',
                'color':      '#f97316' if us_level < 4 else '#dc2626',
                'short_text': f'{flag} GREENLAND: US pressure L{us_level}',
                'long_text':  f'GREENLAND inbound US sovereignty pressure L{us_level}.',
            })

    signals.sort(key=lambda s: s['priority'], reverse=True)
    return signals


# ============================================================
# TRACKER READERS
# ============================================================
def _read_all_trackers():
    """Read all Europe tracker caches and normalize via shim."""
    trackers = {}
    for theatre, redis_key in TRACKER_KEYS.items():
        raw = _redis_get(redis_key)
        if raw:
            normalized = _normalize_tracker_data(theatre, raw)
            if normalized:
                trackers[theatre] = normalized
                lvls = normalized['levels']
                axis_str = (f"T{lvls['threat']}" +
                            (f"/I{lvls['influence']}" if lvls['influence'] is not None else ''))
                print(f'[Europe BLUF] {theatre}: loaded ({axis_str}, score={normalized["score"]})')
        else:
            print(f'[Europe BLUF] {theatre}: no cache available')
    return trackers


# ============================================================
# REGIONAL POSTURE
# ============================================================
def _determine_regional_posture(trackers):
    """Roll up posture across all Europe trackers."""
    if not trackers:
        return {
            'label':              'BASELINE',
            'color':              '#6b7280',
            'peak_level':         0,
            'breached_count':     0,
            'theatres_at_l3plus': 0,
            'nuclear_elevated':   False,
            'arctic_elevated':    False,
        }

    levels = [t['levels']['threat'] for t in trackers.values()]
    max_level = max(levels) if levels else 0

    # Count breached red lines (ME pattern: red_lines is dict with triggered list)
    total_breached = 0
    for data in trackers.values():
        rl = data.get('red_lines', {}) or {}
        for r in rl.get('triggered', []) or []:
            if isinstance(r, dict) and r.get('status') == 'BREACHED':
                total_breached += 1

    theatres_at_l3plus = sum(1 for l in levels if l >= 3)

    # Russia-specific elevated flags
    russia_data = trackers.get('russia', {})
    russia_so_what = russia_data.get('so_what', {}) or {}
    nuclear_elevated = bool(russia_so_what.get('nuclear_elevated', False))
    arctic_elevated  = bool(russia_so_what.get('arctic_elevated', False))

    # Posture ladder
    if total_breached >= 2 or max_level >= 5 or nuclear_elevated:
        label, color = 'CRITICAL -- MULTI-BREACH OR NUCLEAR SIGNALING', '#dc2626'
    elif total_breached >= 1 or max_level >= 4:
        label, color = 'ELEVATED -- INCIDENT OR RED LINE', '#ef4444'
    elif theatres_at_l3plus >= 2:
        label, color = 'ELEVATED -- MULTI-COUNTRY WARNING', '#f97316'
    elif max_level >= 3:
        label, color = 'WARNING -- DIRECT THREAT', '#f59e0b'
    elif max_level >= 2:
        label, color = 'MONITORING -- WARNING', '#fbbf24'
    elif max_level >= 1:
        label, color = 'MONITORING -- RHETORIC', '#3b82f6'
    else:
        label, color = 'BASELINE', '#6b7280'

    return {
        'label':              label,
        'color':              color,
        'peak_level':         max_level,
        'breached_count':     total_breached,
        'theatres_at_l3plus': theatres_at_l3plus,
        'nuclear_elevated':   nuclear_elevated,
        'arctic_elevated':    arctic_elevated,
    }


# ============================================================
# BLUF PROSE
# ============================================================
def _build_bluf_prose(posture, trackers):
    """Generate regional prose paragraph. 2-4 sentences."""
    date_str = datetime.now(timezone.utc).strftime('%b %d, %Y')
    parts = [f"Europe Rhetoric Monitor ({date_str}):"]

    n_live = len(trackers)
    parts.append(
        f"Regional posture at {posture['label']} -- peak escalation L{posture['peak_level']} "
        f"across {n_live} live tracker{'s' if n_live != 1 else ''}."
    )

    russia_data = trackers.get('russia')
    greenland_data = trackers.get('greenland')

    # Russia callout
    if russia_data:
        threat = russia_data['levels']['threat']
        score  = russia_data.get('score', 0)
        raw    = russia_data.get('raw', {})
        nuclear = _safe_int(raw.get('nuclear_level'))
        ground  = _safe_int(raw.get('ground_ops_level'))
        nato    = _safe_int(raw.get('nato_flank_level'))
        arctic  = _safe_int(raw.get('arctic_level'))
        if threat >= 2 or nuclear >= 3 or nato >= 3:
            russia_desc = f"Russia composite L{threat} (score {score}/100)"
            vector_phrases = []
            if nuclear >= 3:
                vector_phrases.append(f"nuclear signaling L{nuclear}")
            if ground >= 3:
                vector_phrases.append(f"ground ops L{ground}")
            if nato >= 3:
                vector_phrases.append(f"NATO flank L{nato}")
            if arctic >= 3:
                vector_phrases.append(f"arctic L{arctic}")
            if vector_phrases:
                russia_desc += " — " + ", ".join(vector_phrases) + "."
            else:
                russia_desc += " — multi-vector pressure elevated."
            parts.append(russia_desc)

    # Greenland callout
    if greenland_data:
        threat = greenland_data['levels']['threat']
        raw    = greenland_data.get('raw', {})
        us_lvl = _safe_int(raw.get('us_pressure_level'))
        if threat >= 2 or us_lvl >= 3:
            green_desc = f"Greenland sovereignty L{threat}"
            if us_lvl >= 3:
                green_desc += f" — inbound US pressure L{us_lvl}; alliance cohesion under stress."
            else:
                green_desc += " — sovereignty signals elevated."
            parts.append(green_desc)

    # Cross-theater convergence (Russia arctic + Greenland sovereignty crisis)
    if russia_data and greenland_data:
        russia_arctic = _safe_int(russia_data.get('raw', {}).get('arctic_level'))
        greenland_threat = greenland_data['levels']['threat']
        if russia_arctic >= 3 and greenland_threat >= 3:
            parts.append(
                f"⚠️ Arctic convergence: Russia arctic L{russia_arctic} simultaneous with "
                f"Greenland sovereignty L{greenland_threat} -- Russia exploiting US-Denmark friction."
            )

    if posture['nuclear_elevated']:
        parts.append(
            "☢️ Russian nuclear signaling at coercion threshold -- highest-stakes signal in theater. "
            "Watch for doctrinal language shifts."
        )

    return ' '.join(parts)


# ============================================================
# TOP SIGNALS COLLECTOR
# ============================================================
def _build_signals(posture, trackers):
    """Collect, dedupe, and rank top_signals across Europe trackers."""
    all_signals = []
    for theatre, data in trackers.items():
        for sig in data.get('top_signals', []) or []:
            sig.setdefault('priority', 5)
            sig.setdefault('category', 'unknown')
            sig.setdefault('theatre', theatre)
            sig.setdefault('icon', '•')
            sig.setdefault('color', '#6b7280')
            sig.setdefault('short_text', '')
            sig.setdefault('long_text', sig.get('short_text', ''))
            all_signals.append(sig)

    # Cross-tracker: Arctic convergence (Russia arctic + Greenland sovereignty crisis)
    russia_data = trackers.get('russia')
    greenland_data = trackers.get('greenland')
    if russia_data and greenland_data:
        russia_arctic = _safe_int(russia_data.get('raw', {}).get('arctic_level'))
        greenland_threat = greenland_data['levels']['threat']
        if russia_arctic >= 3 and greenland_threat >= 3:
            all_signals.append({
                'priority':   13,
                'category':   'arctic_convergence',
                'theatre':    'regional',
                'level':      max(russia_arctic, greenland_threat),
                'icon':       '🧊',
                'color':      '#dc2626',
                'short_text': f'EUROPE: Arctic convergence (RU L{russia_arctic} + GL L{greenland_threat})',
                'long_text':  f'EUROPE Arctic convergence — Russia Northern Fleet posture L{russia_arctic} '
                              f'simultaneous with Greenland sovereignty crisis L{greenland_threat}. '
                              f'Russia exploiting US-Denmark friction; classic GIUK pressure window.',
            })

    # Sort + dedupe
    all_signals.sort(key=lambda x: x.get('priority', 0), reverse=True)
    seen = set()
    deduped = []
    for s in all_signals:
        key = f'{s.get("theatre", "")}:{s.get("category", "")}'
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    if not deduped:
        deduped.append({
            'priority':   1,
            'category':   'baseline',
            'theatre':    'regional',
            'level':      0,
            'icon':       '🌍',
            'color':      '#6b7280',
            'short_text': 'Europe at baseline',
            'long_text':  'All Europe theaters at baseline — monitoring for escalation.',
        })

    return deduped[:TOP_SIGNALS_COUNT]


# ============================================================
# MAIN BUILD FUNCTION
# ============================================================
def build_regional_bluf(force=False):
    """Build the Europe regional BLUF."""
    if not force:
        cached = _redis_get(BLUF_CACHE_KEY)
        if cached and cached.get('generated_at'):
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(cached['generated_at'])).total_seconds()
                if age < BLUF_CACHE_TTL:
                    cached['from_cache'] = True
                    return cached
            except Exception:
                pass

    print('[Europe BLUF v1.0] Building regional BLUF from all Europe tracker caches...')

    try:
        trackers = _read_all_trackers()

        if not trackers:
            return {
                'success': False,
                'error':   'No tracker data available',
                'bluf':    'BLUF unavailable -- no Europe tracker caches loaded.',
                'signals': [],
                'top_signals': [],
                'posture_label': 'UNAVAILABLE',
                'posture_color': '#6b7280',
            }

        posture     = _determine_regional_posture(trackers)
        bluf        = _build_bluf_prose(posture, trackers)
        top_signals = _build_signals(posture, trackers)

        trackers_live = len(trackers)

        # Per-theatre summary
        theatre_summary = {}
        for t, data in trackers.items():
            lvls       = data.get('levels', {}) or {}
            threat_lvl = lvls.get('threat', 0)
            infl_lvl   = lvls.get('influence')
            theatre_summary[t] = {
                'level':            threat_lvl,
                'label':            ESCALATION_LABELS.get(threat_lvl, 'Unknown'),
                'color':            ESCALATION_COLORS.get(threat_lvl, '#6b7280'),
                'score':            data.get('score', 0),
                'flag':             data.get('flag', THEATRE_FLAGS.get(t, '')),
                'timestamp':        data.get('scanned_at', ''),
                'threat_level':     threat_lvl,
                'influence_level':  infl_lvl,
                'green_level':      lvls.get('green'),
                'dominant_axis':    lvls.get('dominant_axis', 'threat'),
                'dominant_level':   lvls.get('dominant_level', threat_lvl),
                'is_dual_axis':     infl_lvl is not None,
                'influence_label':  INFLUENCE_LABELS.get(infl_lvl, '') if infl_lvl is not None else None,
                'influence_color':  INFLUENCE_COLORS.get(infl_lvl, '#6b7280') if infl_lvl is not None else None,
            }

        scores = [t.get('score', 0) for t in theatre_summary.values()]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        result = {
            'success':            True,
            'from_cache':         False,
            'bluf':               bluf,
            'signals':            top_signals,                # legacy alias
            'top_signals':        top_signals,                # canonical
            'posture_label':      posture['label'],
            'posture_color':      posture['color'],
            'peak_level':         posture['peak_level'],      # legacy alias
            'max_level':          posture['peak_level'],      # canonical
            'avg_score':          avg_score,
            'red_lines_breached': posture['breached_count'],
            'nuclear_elevated':   posture['nuclear_elevated'],
            'arctic_elevated':    posture['arctic_elevated'],
            'trackers_live':      trackers_live,
            'theatres_live':      trackers_live,
            'theatres_at_l3plus': posture['theatres_at_l3plus'],
            'trackers_total':     len(TRACKER_KEYS),
            'theatre_summary':    theatre_summary,
            'generated_at':       datetime.now(timezone.utc).isoformat(),
            'version':            '1.0.0',
            'region':             'europe',
            'top_signals_count':  len(top_signals),
        }

        _redis_set(BLUF_CACHE_KEY, result)
        print(f"[Europe BLUF v1.0] Built: posture={posture['label']}, "
              f"max_level=L{posture['peak_level']}, "
              f"breached={posture['breached_count']}, "
              f"signals={len(top_signals)}, "
              f"theaters_live={trackers_live}, "
              f"nuclear={posture['nuclear_elevated']}")
        return result

    except Exception as e:
        print(f"[Europe BLUF] SYNTHESIS EXCEPTION: {e}")
        print(f"[Europe BLUF] Traceback follows:")
        print(traceback.format_exc())
        return {
            'success': False,
            'error':   f'{type(e).__name__}: {str(e)[:300]}',
            'bluf':    'BLUF synthesis failed -- check backend logs for traceback.',
            'signals': [],
            'top_signals': [],
            'posture_label': 'ERROR',
            'posture_color': '#6b7280',
        }


# ============================================================
# ROUTE REGISTRATION
# ============================================================
def register_europe_bluf_routes(app):
    """Register Europe BLUF endpoints on the given Flask app."""
    from flask import jsonify, request as flask_request

    @app.route('/api/rhetoric/europe/bluf', methods=['GET'])
    def get_europe_bluf():
        force = flask_request.args.get('force', 'false').lower() == 'true'
        result = build_regional_bluf(force=force)
        return jsonify(result)

    @app.route('/api/rhetoric/europe/bluf/debug', methods=['GET'])
    def get_europe_bluf_debug():
        cached = _redis_get(BLUF_CACHE_KEY)
        return jsonify({
            'cache_present': cached is not None,
            'cache_data':    cached,
        })

    print('[Europe BLUF] Routes registered: /api/rhetoric/europe/bluf, /bluf/debug')


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    print("Europe Regional BLUF Engine -- standalone test")
    print("(Requires Redis env vars to actually read tracker caches)")
    print()
    result = build_regional_bluf(force=True)
    print('BLUF:')
    print(result.get('bluf', '(no BLUF)'))
    print()
    print('TOP SIGNALS:')
    for s in result.get('top_signals', []):
        print(f'  {s.get("icon", "•")} {s.get("short_text", "")}')
    print()
    print(f'POSTURE: {result.get("posture_label", "")}')
    print(f'MAX LEVEL: L{result.get("max_level", 0)}')
    print(f'TRACKERS LIVE: {result.get("trackers_live", 0)}/{result.get("trackers_total", 0)}')
