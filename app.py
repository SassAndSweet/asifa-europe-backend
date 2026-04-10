"""
Asifah Analytics — Europe Backend v1.1.0
February 22, 2026

European Conflict Probability Dashboard Backend
Targets: Greenland, Ukraine, Russia, Poland

Architecture modeled on Middle East backend (app.py v2.2.0)
Adapted for European geopolitical monitoring with:
  - European source weights (Meduza, Ukrainska Pravda, Le Monde, etc.)
  - GDELT languages: English, Russian, French, Ukrainian
  - European Reddit subreddits
  - European NOTAM monitoring (FAA NOTAM API)
  - European flight disruption tracking
  - Military posture integration hooks

v1.1.0 — Added in-memory response caching + background refresh thread
  - All threat/NOTAM/flight data cached in memory with 4-hour TTL
  - Background thread refreshes all caches every 4 hours automatically
  - Normal page loads return cached data in <100ms
  - Force fresh scan with ?force=true query parameter
  - /api/europe/dashboard endpoint returns all 4 country scores in one call

© 2026 Asifah Analytics. All rights reserved.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS, cross_origin
import requests
from datetime import datetime, timezone, timedelta
import os
import time
import re
import math
import xml.etree.ElementTree as ET
import threading
import json

try:
    from telegram_signals_europe import fetch_europe_telegram_signals
    TELEGRAM_AVAILABLE = True
    print("[Europe Backend] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Europe Backend] ⚠️ Telegram signals not available")

# Ukraine humanitarian data module (DTM API + ReliefWeb + OCHA)
try:
    from ukraine_humanitarian import register_ukraine_humanitarian_endpoints
    UKRAINE_HUMANITARIAN_AVAILABLE = True
    print("[Europe Backend] ✅ Ukraine humanitarian module loaded")
except ImportError:
    UKRAINE_HUMANITARIAN_AVAILABLE = False
    print("[Europe Backend] ⚠️ Ukraine humanitarian module not available")

# Greenland sovereignty rhetoric tracker
try:
    from rhetoric_tracker_greenland import register_greenland_rhetoric_routes
    GREENLAND_RHETORIC_AVAILABLE = True
    print("[Europe Backend] ✅ Greenland rhetoric tracker loaded")
except ImportError:
    GREENLAND_RHETORIC_AVAILABLE = False
    print("[Europe Backend] ⚠️ Greenland rhetoric tracker not available")

app = Flask(__name__)
# CORS handled by after_request handler

# ========================================
# CONFIGURATION
# ========================================
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY')
GDELT_BASE_URL = "http://api.gdeltproject.org/api/v2/doc/doc"

# Cache TTL in seconds (4 hours)
CACHE_TTL = 12 * 60 * 60

# NOTAM cache TTL (2 hours — NOTAMs change faster than threat scores)
NOTAM_CACHE_TTL = 2 * 60 * 60

# Upstash Redis (persistent cache across Render cold starts)
UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
NOTAM_REDIS_KEY = 'europe_notam_cache'
FLIGHT_REDIS_KEY = 'europe_flight_cache'
FLIGHT_CACHE_TTL = 12 * 60 * 60  # 12 hours
THREAT_REDIS_PREFIX = 'europe_threat_'  # e.g. europe_threat_turkey_7d
THREAT_CACHE_TTL = 4 * 60 * 60  # 4 hours

# Rate limiting
RATE_LIMIT = 100
RATE_LIMIT_WINDOW = 86400
rate_limit_data = {
    'requests': 0,
    'reset_time': time.time() + RATE_LIMIT_WINDOW
}

# ========================================
# IN-MEMORY RESPONSE CACHE
# ========================================
_cache = {}
_cache_lock = threading.Lock()


def cache_get(key):
    """Get a cached response if it exists and is fresh."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        age = time.time() - entry['timestamp']
        if age > CACHE_TTL:
            return None  # Stale
        return entry['data']


def cache_set(key, data):
    """Store a response in the cache."""
    with _cache_lock:
        _cache[key] = {
            'data': data,
            'timestamp': time.time()
        }


def cache_age(key):
    """Return how many seconds old a cache entry is, or None if missing."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        return time.time() - entry['timestamp']


def cache_clear(key=None):
    """Clear one key or entire cache."""
    with _cache_lock:
        if key:
            _cache.pop(key, None)
        else:
            _cache.clear()


# ========================================
# REDIS NOTAM CACHE (persistent across deploys)
# ========================================
def load_notam_cache_redis():
    """Load NOTAM cache from Upstash Redis."""
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{NOTAM_REDIS_KEY}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get("result"):
                cache = json.loads(data["result"])
                print(f"[NOTAM Cache] Loaded from Redis (cached_at: {cache.get('cached_at', 'unknown')})")
                return cache
        except Exception as e:
            print(f"[NOTAM Cache] Redis load error: {e}")
    return None


def save_notam_cache_redis(data):
    """Save NOTAM cache to Upstash Redis."""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            payload = json.dumps(data, default=str)
            resp = requests.post(
                f"{UPSTASH_REDIS_URL}/set/{NOTAM_REDIS_KEY}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"value": payload},
                timeout=10
            )
            if resp.status_code == 200:
                print("[NOTAM Cache] ✅ Saved to Redis")
            else:
                print(f"[NOTAM Cache] Redis save HTTP {resp.status_code}")
        except Exception as e:
            print(f"[NOTAM Cache] Redis save error: {e}")


def is_notam_cache_fresh():
    """Check if NOTAM Redis cache is still valid (2-hour TTL)."""
    cached = load_notam_cache_redis()
    if not cached or 'cached_at' not in cached:
        return False, None
    try:
        cached_at = datetime.fromisoformat(cached['cached_at'])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age < NOTAM_CACHE_TTL:
            print(f"[NOTAM Cache] Fresh ({age/60:.0f}min old)")
            return True, cached
        print(f"[NOTAM Cache] Stale ({age/60:.0f}min old)")
        return False, cached
    except:
        return False, None

# ========================================
# REDIS FLIGHT CACHE (persistent across deploys)
# ========================================
def load_flight_cache_redis():
    """Load flight cache from Upstash Redis."""
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{FLIGHT_REDIS_KEY}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get("result"):
                cache = json.loads(data["result"])
                print(f"[Flight Cache] Loaded from Redis (cached_at: {cache.get('cached_at', 'unknown')})")
                return cache
        except Exception as e:
            print(f"[Flight Cache] Redis load error: {e}")
    return None


def save_flight_cache_redis(data):
    """Save flight cache to Upstash Redis."""
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            payload = json.dumps(data, default=str)
            resp = requests.post(
                f"{UPSTASH_REDIS_URL}/set/{FLIGHT_REDIS_KEY}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"value": payload},
                timeout=10
            )
            if resp.status_code == 200:
                print("[Flight Cache] ✅ Saved to Redis")
            else:
                print(f"[Flight Cache] Redis save HTTP {resp.status_code}")
        except Exception as e:
            print(f"[Flight Cache] Redis save error: {e}")


def is_flight_cache_fresh():
    """Check if flight Redis cache is still valid (12-hour TTL)."""
    cached = load_flight_cache_redis()
    if not cached or 'cached_at' not in cached:
        return False, None
    try:
        cached_at = datetime.fromisoformat(cached['cached_at'])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age < FLIGHT_CACHE_TTL:
            print(f"[Flight Cache] Fresh ({age/60:.0f}min old)")
            return True, cached
        print(f"[Flight Cache] Stale ({age/60:.0f}min old)")
        return False, cached
    except:
        return False, None

# ========================================
# REDIS THREAT SCORE CACHE (persistent across deploys)
# ========================================
def load_threat_cache_redis(target, days=7):
    """Load threat score from Upstash Redis."""
    key = f"{THREAT_REDIS_PREFIX}{target}_{days}d"
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            resp = requests.get(
                f"{UPSTASH_REDIS_URL}/get/{key}",
                headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
                timeout=5
            )
            data = resp.json()
            if data.get("result"):
                cache = json.loads(data["result"])
                print(f"[Threat Cache] Loaded {target} from Redis")
                return cache
        except Exception as e:
            print(f"[Threat Cache] Redis load error for {target}: {e}")
    return None


def save_threat_cache_redis(target, data, days=7):
    """Save threat score to Upstash Redis."""
    key = f"{THREAT_REDIS_PREFIX}{target}_{days}d"
    data['cached_at'] = datetime.now(timezone.utc).isoformat()
    if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
        try:
            payload = json.dumps(data, default=str)
            resp = requests.post(
                f"{UPSTASH_REDIS_URL}/set/{key}",
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={"value": payload},
                timeout=10
            )
            if resp.status_code == 200:
                print(f"[Threat Cache] ✅ Saved {target} to Redis")
        except Exception as e:
            print(f"[Threat Cache] Redis save error for {target}: {e}")


def is_threat_cache_fresh_redis(target, days=7):
    """Check if threat Redis cache is still valid."""
    cached = load_threat_cache_redis(target, days)
    if not cached or 'cached_at' not in cached:
        return False, None
    try:
        cached_at = datetime.fromisoformat(cached['cached_at'])
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age < THREAT_CACHE_TTL:
            print(f"[Threat Cache] {target} fresh ({age/60:.0f}min old)")
            return True, cached
        print(f"[Threat Cache] {target} stale ({age/60:.0f}min old)")
        return False, cached
    except:
        return False, None
      
# ========================================
# BACKGROUND REFRESH THREAD
# ========================================
def _refresh_all_caches():
    """
    Refresh all cached data in the background.
    Runs every CACHE_TTL seconds so no user request ever triggers a cold scan.
    """
    # Let the app fully boot before first refresh cycle
    print("[Background Refresh] Waiting 90s for app to stabilize before first refresh...")
    time.sleep(90)

    targets = list(TARGET_KEYWORDS.keys())

    while True:
        print(f"\n[Background Refresh] Starting full cache refresh at {datetime.now(timezone.utc).isoformat()}")
        start = time.time()

        # Refresh each country threat assessment
        for target in targets:
            try:
                print(f"[Background Refresh] Refreshing {target}...")
                data = _run_threat_scan(target, days=7)
                cache_set(f'threat_{target}_7d', data)
                save_threat_cache_redis(target, data, days=7)
                print(f"[Background Refresh] ✓ {target} cached (probability: {data.get('probability', '?')}%)")
            except Exception as e:
                print(f"[Background Refresh] ✗ {target} failed: {e}")

            # Small delay between targets to avoid hammering APIs
            time.sleep(5)

        # Refresh NOTAMs (uses Redis + in-memory)
        try:
            print("[Background Refresh] Refreshing NOTAMs via FAA...")
            notam_data = _run_notam_scan()
            cache_set('notams', notam_data)
            print(f"[Background Refresh] ✓ NOTAMs cached ({notam_data.get('total_notams', 0)} critical alerts)")
        except Exception as e:
            print(f"[Background Refresh] ✗ NOTAMs failed: {e}")

        time.sleep(5)

        # Refresh flight disruptions (Redis + in-memory)
        try:
            print("[Background Refresh] Refreshing flights...")
            flight_data = _run_flight_scan()
            cache_set('flights', flight_data)
            print(f"[Background Refresh] ✓ Flights cached ({flight_data.get('total_disruptions', 0)} disruptions)")
        except Exception as e:
            print(f"[Background Refresh] ✗ Flights failed: {e}")

        time.sleep(5)

        # Refresh travel advisories
        try:
            print("[Background Refresh] Refreshing travel advisories...")
            ta_data = _run_travel_advisory_scan()
            cache_set('travel_advisories', ta_data)
            print(f"[Background Refresh] ✓ Travel advisories cached ({len(ta_data.get('advisories', {}))} countries)")
        except Exception as e:
            print(f"[Background Refresh] ✗ Travel advisories failed: {e}")

        elapsed = time.time() - start
        print(f"[Background Refresh] Complete in {elapsed:.1f}s. Sleeping {CACHE_TTL}s until next refresh.\n")

        # Sleep until next refresh cycle
        time.sleep(CACHE_TTL)


def start_background_refresh():
    """Start the background refresh thread (daemon so it dies with the app)."""
    thread = threading.Thread(target=_refresh_all_caches, daemon=True)
    thread.start()
    print("[Background Refresh] Thread started — will refresh all caches every 4 hours")

# ========================================
# U.S. STATE DEPT TRAVEL ADVISORIES
# ========================================
TRAVEL_ADVISORY_API = "https://cadataapi.state.gov/api/TravelAdvisories"

TRAVEL_ADVISORY_CODES = {
    'greenland': ['GL', 'DA'],
    'ukraine': ['UP'],
    'russia': ['RS'],
    'poland': ['PL'],
    'turkey': ['TU'],
    'cyprus': ['CY'],
    'azerbaijan': ['AJ'],
    'armenia': ['AM'],
}

TRAVEL_ADVISORY_LEVELS = {
    1: {'label': 'Exercise Normal Precautions', 'short': 'Normal Precautions', 'color': '#10b981'},
    2: {'label': 'Exercise Increased Caution', 'short': 'Increased Caution', 'color': '#f59e0b'},
    3: {'label': 'Reconsider Travel', 'short': 'Reconsider Travel', 'color': '#f97316'},
    4: {'label': 'Do Not Travel', 'short': 'Do Not Travel', 'color': '#ef4444'}
}

# ========================================
# SOURCE WEIGHTS — EUROPEAN EDITION
# ========================================
SOURCE_WEIGHTS = {
    'premium': {
        'sources': [
            'The New York Times', 'The Washington Post', 'Reuters',
            'Associated Press', 'AP News', 'BBC News', 'The Guardian',
            'Financial Times', 'Wall Street Journal', 'The Economist',
            'Le Monde', 'Der Spiegel', 'Frankfurter Allgemeine'
        ],
        'weight': 1.0
    },
    'regional_europe': {
        'sources': [
            'Ukrainska Pravda', 'Kyiv Independent', 'Kyiv Post',
            'Meduza', 'Moscow Times', 'TASS', 'Interfax',
            'Gazeta Wyborcza', 'TVN24', 'Polsat News',
            'Arctic Today', 'Sermitsiaq', 'KNR Greenland',
            'DR (Denmark)', 'Berlingske', 'Politiken',
            'France 24', 'RFI', 'Deutsche Welle',
            'Euronews', 'EUobserver', 'Politico Europe',
            'The Barents Observer', 'High North News',
            'Daily Sabah', 'Hurriyet Daily News', 'TRT World',
            'Cyprus Mail', 'In-Cyprus', 'Kathimerini',
            'Ukrinform', 'Defence24', 'Notes from Poland'
        ],
        'weight': 0.85
    },
    'standard': {
        'sources': [
            'CNN', 'MSNBC', 'Fox News', 'NBC News', 'CBS News',
            'ABC News', 'Bloomberg', 'CNBC', 'Sky News',
            'Al Jazeera', 'RT'
        ],
        'weight': 0.6
    },
    'think_tank': {
        'sources': [
            'War on the Rocks', 'ISW', 'RUSI', 'IISS',
            'Carnegie', 'Chatham House', 'CSIS', 'RAND',
            'Atlantic Council', 'Brookings', 'Council on Foreign Relations'
        ],
        'weight': 0.9
    },
    'gdelt': {
        'sources': ['GDELT'],
        'weight': 0.4
    },
    'social': {
        'sources': ['Reddit', 'r/'],
        'weight': 0.3
    }
}

# ========================================
# KEYWORD SEVERITY
# ========================================
KEYWORD_SEVERITY = {
    'active_war': {
        'keywords': [
            'intercepts ballistic missile', 'intercepts missile',
            'shoots down drone', 'shoots down missile',
            'base hit by missile', 'base struck by missile',
            'base attacked', 'embassy hit', 'embassy struck',
            'embassy attacked', 'port struck', 'port attacked',
            'air defense activated', 'air defense fires',
            'scrambles jets', 'jets scrambled',
            'invokes article 5', 'article 5 invoked',
            'operation epic fury', 'regime change operation',
            'ballistic missile intercepted over',
            'iranian missile hits', 'iranian drone hits',
            'iran strikes', 'iran attacks',
        ],
        'multiplier': 3.0
    },
    'diplomatic_crisis': {
        'keywords': [
            'ordered departure', 'authorized departure',
            'embassy evacuation', 'evacuate embassy',
            'embassy closure', 'embassy closed',
            'drawdown of personnel', 'drawdown of staff',
            'suspend embassy operations',
            'non-emergency personnel ordered',
        ],
        'multiplier': 3.5
    },
    'critical': {
        'keywords': [
            'nuclear strike', 'nuclear attack', 'nuclear threat', 'nuclear escalation',
            'full-scale war', 'declaration of war', 'state of war',
            'mobilization order', 'reserves called up', 'troops deployed',
            'article 5', 'nato article 5', 'collective defense',
            'tactical nuclear', 'nuclear warhead'
        ],
        'multiplier': 2.5
    },
    'high': {
        'keywords': [
            'imminent strike', 'imminent attack', 'preparing to strike',
            'military buildup', 'forces gathering', 'will strike',
            'vowed to attack', 'threatened to strike',
            'invasion', 'incursion', 'annexation',
            'cruise missile', 'ballistic missile', 'hypersonic',
            'drone swarm', 'airspace violation', 'sovereignty violation',
            'territorial violation', 'border breach'
        ],
        'multiplier': 2.0
    },
    'elevated': {
        'keywords': [
            'strike', 'attack', 'airstrike', 'bombing', 'missile',
            'rocket', 'retaliate', 'retaliation', 'response',
            'offensive', 'counteroffensive', 'shelling', 'artillery',
            'drone strike', 'drone attack', 'sabotage',
            'cyber attack', 'hybrid warfare', 'disinformation campaign'
        ],
        'multiplier': 1.5
    },
    'moderate': {
        'keywords': [
            'threatens', 'warned', 'tensions', 'escalation',
            'conflict', 'crisis', 'provocation', 'sanctions',
            'troop movement', 'military exercise', 'naval exercise',
            'reconnaissance', 'surveillance', 'posturing'
        ],
        'multiplier': 1.0
    }
}

# ========================================
# v2.9 TRAVEL ADVISORY FLOOR SYSTEM
# ========================================
DIPLOMATIC_SIGNAL_KEYWORDS = {
    'embassy_closure': {
        'phrases': [
            'embassy closed', 'embassy closure', 'suspend embassy operations',
            'suspended embassy operations', 'shuttered embassy', 'closing the embassy',
        ],
        'floor_schedule': [
            (14, 92),
            (28, 80),
            (45, 65),
        ],
    },
    'ordered_departure': {
        'phrases': [
            'ordered departure', 'authorized departure',
            'drawdown of personnel', 'drawdown of staff',
            'embassy evacuation', 'evacuate embassy', 'evacuating embassy',
            'non-emergency personnel ordered to leave',
            'departure of non-emergency',
            'family members ordered to depart',
        ],
        'floor_schedule': [
            (14, 85),
            (28, 70),
            (45, 55),
        ],
    },
    'level_4_do_not_travel': {
        'phrases': [
            'level 4: do not travel',
            'do not travel',
        ],
        'floor_schedule': [
            (14, 70),
            (28, 55),
            (45, 40),
        ],
    },
    'level_3_reconsider': {
        'phrases': [
            'level 3: reconsider travel',
            'reconsider travel',
        ],
        'floor_schedule': [
            (14, 45),
            (28, 35),
            (45, 30),
        ],
    },
}

# ========================================
# DE-ESCALATION KEYWORDS
# ========================================
DEESCALATION_KEYWORDS = [
    'ceasefire', 'cease-fire', 'truce', 'peace talks', 'peace agreement',
    'diplomatic solution', 'negotiations', 'de-escalation', 'de-escalate',
    'tensions ease', 'tensions cool', 'tensions subside', 'calm',
    'defused', 'avoided', 'no plans to', 'ruled out', 'backs down',
    'restraint', 'diplomatic efforts', 'unlikely to strike',
    'peace summit', 'peace plan', 'peace deal', 'Minsk agreement',
    'withdrawal', 'pullback', 'disengagement', 'humanitarian corridor',
    'prisoner exchange', 'grain deal', 'diplomatic channel'
]

# ========================================
# TARGET-SPECIFIC BASELINES — EUROPE
# ========================================
TARGET_BASELINES = {
    'greenland': {
        'base_adjustment': +3,
        'description': 'US aggressive rhetoric re: Greenland acquisition; Danish sovereignty tensions'
    },
    'ukraine': {
        'base_adjustment': +15,
        'description': 'Active war zone — Russia-Ukraine conflict ongoing since Feb 2022'
    },
    'russia': {
        'base_adjustment': +12,
        'description': 'Active aggressor in Ukraine; elevated NATO tensions; nuclear rhetoric'
    },
    'poland': {
        'base_adjustment': +5,
        'description': 'NATO frontline state; recent Russian drone incursions; Belarus border tensions'
    },
    'turkey': {
        'base_adjustment': +12,
        'description': 'NATO member; Incirlik base targeted; actively intercepting Iranian missiles; Iran border tensions'
    },
    'cyprus': {
        'base_adjustment': +10,
        'description': 'Active Iranian drone strikes on RAF Akrotiri; European reinforcements deploying; US evacuation'
    },
    'azerbaijan': {
        'base_adjustment': +8,
        'description': 'Iranian border tensions; drone supplier to region; Nagorno-Karabakh victor; energy corridor risk'
    },
    'armenia': {
        'base_adjustment': +5,
        'description': 'Post-Karabakh vulnerability; Russian alliance strain; Iranian border proximity'
    }
}

# ========================================
# TARGET KEYWORDS — EUROPE
# ========================================
TARGET_KEYWORDS = {
    'greenland': {
        'keywords': [
            'greenland', 'grønland', 'kalaallit nunaat',
            'greenland sovereignty', 'greenland acquisition', 'greenland trump',
            'greenland nato', 'greenland arctic', 'greenland denmark',
            'thule air base', 'pituffik space base', 'nuuk',
            'greenland independence', 'greenland autonomy',
            'greenland rare earth', 'greenland critical minerals',
            'greenland military base', 'greenland us military',
            'múte egede', 'greenland mineral',
            'arctic sovereignty', 'arctic nato', 'arctic military',
            'canadian arctic dispute', 'trump greenland purchase',
            'greenland referendum', 'greenland self-rule',
            'greenland strategic', 'greenland china', 'greenland mining'
        ],
        'reddit_keywords': [
            'Greenland', 'Denmark', 'Arctic', 'Trump Greenland',
            'sovereignty', 'NATO', 'Thule', 'Pituffik', 'Nuuk',
            'rare earth', 'acquisition'
        ]
    },
    'ukraine': {
        'keywords': [
            'ukraine', 'ukrainian', 'kyiv', 'kiev', 'zelensky', 'zelenskyy',
            'donbas', 'donbass', 'donetsk', 'luhansk', 'zaporizhzhia',
            'kherson', 'crimea', 'mariupol', 'bakhmut', 'avdiivka',
            'ukraine war', 'ukraine offensive', 'ukraine counteroffensive',
            'ukraine frontline', 'ukraine ceasefire', 'ukraine peace',
            'ukraine nato', 'ukraine eu', 'ukraine aid'
        ],
        'reddit_keywords': [
            'Ukraine', 'Kyiv', 'Zelensky', 'frontline', 'war',
            'Donbas', 'offensive', 'missile', 'drone', 'ceasefire',
            'NATO', 'aid', 'sanctions'
        ]
    },
    'russia': {
        'keywords': [
            'russia', 'russian', 'moscow', 'kremlin', 'putin',
            'russian military', 'russian forces', 'russian army',
            'russia nato', 'russia nuclear', 'russia sanctions',
            'russia economy', 'russia mobilization',
            'wagner', 'prigozhin', 'shoigu', 'gerasimov',
            'russia ukraine', 'russia europe', 'russia baltic',
            'russia arctic', 'kaliningrad', 'russia drone',
            'russia poland', 'russia airspace'
        ],
        'reddit_keywords': [
            'Russia', 'Putin', 'Kremlin', 'Moscow', 'sanctions',
            'nuclear', 'NATO', 'Wagner', 'mobilization', 'frontline',
            'Ukraine war', 'Baltic', 'Arctic'
        ]
    },
    'poland': {
        'keywords': [
            'poland', 'polish', 'warsaw', 'poland nato', 'poland military',
            'poland border', 'poland russia', 'poland drone',
            'poland airspace', 'poland ukraine', 'poland belarus',
            'poland missile', 'przewodów', 'poland patriot',
            'poland defense', 'poland troops', 'tusk',
            'poland migration', 'suwalki gap', 'poland f-35',
            'poland air shield', 'poland army modernization'
        ],
        'reddit_keywords': [
            'Poland', 'Warsaw', 'NATO', 'border', 'Russia',
            'drone', 'airspace', 'Belarus', 'Suwalki', 'missile',
            'defense', 'Ukraine'
        ]
    },
    'turkey': {
        'keywords': [
            'turkey', 'turkish', 'ankara', 'istanbul', 'erdogan',
            'turkey military', 'turkish armed forces', 'turkish army',
            'turkey nato', 'turkey article 5', 'nato turkey',
            'incirlik', 'incirlik air base', 'incirlik attack',
            'incirlik strike', 'incirlik base alert',
            'turkish air force', 'turkish navy', 'turkish drone',
            'bayraktar', 'akinci drone', 'turkish f-16',
            'turkey syria', 'turkey syria operation', 'operation claw',
            'turkey pkk', 'turkey northern iraq',
            'turkey iran', 'iran attack turkey', 'iranian missile turkey',
            'turkish airspace', 'turkish airspace violation',
            'turkey intercept', 'turkey air defense',
            'bosphorus military', 'turkish straits',
            'turkey border', 'turkey border alert',
            'turkey war', 'turkey conflict',
            'turkey defense spending', 'turkish military exercise',
            'turkish navy mediterranean', 'turkish naval exercise',
            'turkey earthquake', 'turkey refugees',
            'turkey election', 'turkey economy',
            'turkey greece tensions', 'aegean dispute',
            # Active war keywords (v1.2.0)
            'turkey intercepts missile', 'turkey intercepts ballistic',
            'turkey shoots down drone', 'turkey shoots down missile',
            'turkish intercept iran', 'turkey missile intercept',
            'incirlik high alert', 'incirlik closed', 'incirlik attacked',
            'incirlik strike', 'incirlik hit', 'incirlik drone',
            'iran strikes turkey', 'iran attacks turkey', 'iran missile turkey',
            'iranian missile hits turkey', 'iranian drone turkey',
            'turkey scrambles jets', 'turkish jets scramble',
            'turkey activates air defense', 'turkey air defense alert',
            'turkey nato article 5', 'turkey invokes article 5',
            'article 5 turkey', 'nato defends turkey',
            'debris falls turkey', 'shrapnel turkey', 'fragments turkey',
            'missile intercepted over turkey', 'ballistic missile turkey',
            'ankara shelter', 'istanbul shelter', 'ankara attack',
            'istanbul attack', 'turkey casualties', 'turkey killed',
            'turkish airspace closed', 'turkey flights cancelled',
            'turkey war iran', 'iran war turkey'
        ],
        'reddit_keywords': [
            'Turkey', 'Erdogan', 'Ankara', 'Istanbul', 'NATO',
            'Incirlik', 'Turkish military', 'Syria', 'Iran',
            'Article 5', 'Bayraktar', 'airspace', 'Mediterranean',
            'intercept', 'missile', 'drone', 'attack', 'war'
        ]
    },
    'cyprus': {
        'keywords': [
            'cyprus', 'cypriot', 'nicosia', 'limassol', 'larnaca', 'paphos',
            'cyprus military', 'cyprus defense', 'cyprus defence',
            'akrotiri', 'raf akrotiri', 'akrotiri base',
            'akrotiri attack', 'akrotiri drone', 'akrotiri strike',
            'dhekelia', 'dhekelia base', 'sovereign base areas',
            'british bases cyprus', 'uk bases cyprus', 'uk forces cyprus',
            'cyprus nato', 'cyprus eu',
            'iran attack cyprus', 'iranian drone cyprus',
            'iranian strike cyprus', 'iran missile cyprus',
            'cyprus airspace closed', 'cyprus flights cancelled',
            'cyprus evacuation', 'us evacuate cyprus',
            'cyprus shelter', 'nicosia attack',
            'andreas papandreou air base', 'paphos air base',
            'cyprus intercept', 'cyprus air defense',
            'european forces cyprus', 'france cyprus',
            'greece deploy cyprus', 'greece cyprus military',
            'cyprus reinforcement', 'destroyer cyprus',
            'cyprus war', 'cyprus conflict',
            'cyprus turkey tensions', 'northern cyprus',
            'cyprus division', 'cyprus buffer zone', 'unficyp',
            'cyprus gas', 'cyprus energy', 'east med gas',
            # Active war keywords (v1.2.0)
            'akrotiri hit', 'akrotiri struck', 'akrotiri attacked',
            'akrotiri drone hit', 'akrotiri missile',
            'iran strikes akrotiri', 'iranian drone akrotiri',
            'iranian drone hits cyprus', 'iran attacks cyprus',
            'cyprus airspace closed', 'cyprus flights grounded',
            'cyprus flights cancelled', 'larnaca airport closed',
            'paphos airport closed', 'nicosia shelter',
            'limassol attack', 'larnaca attack',
            'uk reinforces cyprus', 'uk deploys cyprus',
            'british troops cyprus', 'royal air force cyprus',
            'greece reinforces cyprus', 'greek jets cyprus',
            'greek f-16 cyprus', 'greece intercepts drone',
            'debris cyprus', 'shrapnel cyprus', 'fragments cyprus',
            'cyprus casualties', 'cyprus killed',
            'sovereign base areas attack', 'dhekelia attack',
            'cyprus war', 'cyprus conflict iran',
            'eastern mediterranean war', 'east med conflict'
        ],
        'reddit_keywords': [
            'Cyprus', 'Akrotiri', 'RAF', 'UK base', 'Iran drone',
            'evacuation', 'Nicosia', 'Limassol', 'NATO',
            'British forces', 'Mediterranean', 'Turkey Cyprus',
            'intercept', 'drone', 'attack', 'missile', 'Greek F-16'
        ]
    },
    'azerbaijan': {
        'keywords': [
            'azerbaijan', 'azerbaijani', 'baku', 'aliyev',
            'nagorno-karabakh', 'karabakh', 'nakhchivan',
            'azerbaijan military', 'azerbaijan army', 'azerbaijan drone',
            'azerbaijan turkey', 'azerbaijan israel', 'azerbaijan iran',
            'baku tbilisi ceyhan', 'btc pipeline', 'shah deniz',
            'azerbaijan gas', 'azerbaijan oil', 'socar',
            'azerbaijan armenia', 'lachin corridor', 'zangezur corridor',
            'azerbaijan attack', 'azerbaijan mobilization',
            'iran azerbaijan', 'iran baku', 'iran border azerbaijan',
            'Азербайджан', 'Баку',
        ],
        'reddit_keywords': [
            'Azerbaijan', 'Baku', 'Aliyev', 'Karabakh', 'Armenia Azerbaijan',
            'Nagorno', 'drone', 'Turkey Azerbaijan', 'Iran Azerbaijan'
        ]
    },
    'armenia': {
        'keywords': [
            'armenia', 'armenian', 'yerevan', 'pashinyan',
            'armenia military', 'armenian army', 'armenia defense',
            'armenia russia', 'armenia nato', 'armenia eu',
            'armenia azerbaijan', 'armenia border', 'armenia attack',
            'armenia iran', 'armenia turkey', 'syunik',
            'zangezur corridor', 'lachin', 'artsakh',
            'armenia mobilization', 'armenia protest',
            'CSTO', 'armenia peacekeepers', 'armenia genocide',
            'Армения', 'Ереван',
        ],
        'reddit_keywords': [
            'Armenia', 'Yerevan', 'Pashinyan', 'Karabakh', 'Azerbaijan Armenia',
            'CSTO', 'Russia Armenia', 'Turkey Armenia', 'Iran Armenia'
        ]
    }
}

# ========================================
# REDDIT CONFIGURATION — EUROPE
# ========================================
REDDIT_USER_AGENT = "AsifahAnalytics-Europe/1.1.0 (OSINT monitoring tool)"
REDDIT_SUBREDDITS = {
    'greenland': ['Greenland', 'europe', 'geopolitics', 'worldnews', 'Denmark'],
    'ukraine': ['ukraine', 'UkraineWarVideoReport', 'UkrainianConflict', 'europe', 'geopolitics', 'worldnews'],
    'russia': ['russia', 'europe', 'geopolitics', 'worldnews'],
    'poland': ['poland', 'Polska', 'europe', 'geopolitics', 'worldnews'],
    'turkey': ['Turkey', 'turkish', 'europe', 'geopolitics', 'worldnews', 'syriancivilwar'],
    'cyprus': ['cyprus', 'europe', 'geopolitics', 'worldnews', 'unitedkingdom'],
    'azerbaijan': ['azerbaijan', 'europe', 'geopolitics', 'worldnews', 'CredibleDefense'],
    'armenia': ['armenia', 'europe', 'geopolitics', 'worldnews', 'CredibleDefense', 'ArmeniaAzerbaijan']
}

# ========================================
# EUROPEAN ESCALATION KEYWORDS
# ========================================
ESCALATION_KEYWORDS = [
    'strike', 'attack', 'bombing', 'airstrike', 'missile', 'rocket',
    'military operation', 'offensive', 'retaliate', 'retaliation',
    'response', 'counterattack', 'invasion', 'incursion',
    'shelling', 'artillery', 'drone strike', 'drone attack',
    'threatens', 'warned', 'vowed', 'promised to strike',
    'will respond', 'severe response', 'consequences',
    'mobilization', 'troops deployed', 'forces gathering',
    'military buildup', 'reserves called up',
    'killed', 'dead', 'casualties', 'wounded', 'injured',
    'death toll', 'fatalities',
    'article 5', 'collective defense', 'nato response',
    'nuclear threat', 'nuclear posture', 'tactical nuclear',
    'airspace violation', 'airspace closed', 'no-fly zone',
    'sovereignty violation', 'territorial integrity',
    'flight cancellations', 'cancelled flights', 'suspend flights',
    'suspended flights', 'airline suspends', 'halted flights',
    'grounded flights', 'travel advisory',
    'do not travel', 'avoid all travel', 'reconsider travel',
    'lufthansa suspend', 'lufthansa cancel',
    'air france suspend', 'air france cancel',
    'british airways suspend', 'british airways cancel',
    'klm suspend', 'klm cancel',
    'ryanair suspend', 'ryanair cancel',
    'wizz air suspend', 'wizz air cancel',
    'lot polish suspend', 'lot polish cancel',
    'sas suspend', 'sas cancel',
    'finnair suspend', 'finnair cancel',
    'norwegian air suspend', 'norwegian air cancel',
    'border incident', 'border violation', 'hybrid attack',
    'cyber attack', 'sabotage', 'disinformation',
    # Active war escalation (v1.2.0)
    'intercepts missile', 'intercepts ballistic missile',
    'intercepts drone', 'shoots down drone', 'shoots down missile',
    'air defense activated', 'air defense fires',
    'base attacked', 'base hit', 'base struck',
    'embassy hit', 'embassy attacked', 'embassy struck',
    'port attacked', 'port struck', 'oil facility attacked',
    'invokes article 5', 'article 5 invoked',
    'scrambles jets', 'jets scrambled',
    'airspace closed war', 'flights grounded war',
    'fragments fell', 'debris fell', 'shrapnel hit',
    'ballistic missile intercepted', 'cruise missile intercepted',
    'regime change', 'operation epic fury'
]

# ========================================
# EUROPEAN NOTAM MONITORING
# ========================================
NOTAM_REGIONS = {
    'ukraine': {
        'fir_codes': ['UKBV', 'UKDV', 'UKLV', 'UKFV', 'UKOV'],
        'icao_codes': ['UKBB', 'UKKK', 'UKLL', 'UKOO', 'UKDD', 'UKFF'],
        'display_name': 'Ukraine',
        'flag': '🇺🇦'
    },
    'poland': {
        'fir_codes': ['EPWW'],
        'icao_codes': ['EPWA', 'EPKK', 'EPGD', 'EPWR', 'EPKT', 'EPPO'],
        'display_name': 'Poland',
        'flag': '🇵🇱'
    },
    'russia_west': {
        'fir_codes': ['UUWV', 'ULLL', 'UMKK'],
        'icao_codes': ['UUEE', 'UUDD', 'ULLI', 'UMKK'],
        'display_name': 'Western Russia',
        'flag': '🇷🇺'
    },
    'baltic': {
        'fir_codes': ['EYVL', 'EVRR', 'EETT'],
        'icao_codes': ['EYVI', 'EVRA', 'EETN'],
        'display_name': 'Baltic States',
        'flag': '🇪🇺'
    },
    'greenland': {
        'fir_codes': ['BGGL'],
        'icao_codes': ['BGBW', 'BGSF', 'BGKK'],
        'display_name': 'Greenland',
        'flag': '🇬🇱'
    },
    'denmark': {
        'fir_codes': ['EKDK'],
        'icao_codes': ['EKCH', 'EKBI', 'EKAH'],
        'display_name': 'Denmark',
        'flag': '🇩🇰'
    },
    'romania': {
        'fir_codes': ['LRBB'],
        'icao_codes': ['LROP', 'LRCL'],
        'display_name': 'Romania',
        'flag': '🇷🇴'
    },
    'moldova': {
        'fir_codes': ['LUUU'],
        'icao_codes': ['LUKK'],
        'display_name': 'Moldova',
        'flag': '🇲🇩'
    },
    'turkey': {
        'fir_codes': ['LTAA', 'LTBB'],
        'icao_codes': ['LTBA', 'LTAC', 'LTAI', 'LTBJ', 'LTFE'],
        'display_name': 'Turkey',
        'flag': '🇹🇷'
    },
    'cyprus': {
        'fir_codes': ['LCCC'],
        'icao_codes': ['LCLK', 'LCPH', 'LCRA'],
        'display_name': 'Cyprus',
        'flag': '🇨🇾'
    }
}

NOTAM_CRITICAL_PATTERNS = [
    r'AIRSPACE\s+CLOSED',
    r'PROHIBITED\s+AREA',
    r'RESTRICTED\s+AREA',
    r'DANGER\s+AREA',
    r'NO[-\s]?FLY\s+ZONE',
    r'MIL(?:ITARY)?\s+(?:EXERCISE|OPS|OPERATIONS)',
    r'LIVE\s+FIRING',
    r'MISSILE\s+(?:LAUNCH|TEST|FIRING)',
    r'UAV|UAS|DRONE|UNMANNED',
    r'GPS\s+(?:JAMMING|INTERFERENCE|SPOOFING)',
    r'NAVIGATION\s+(?:WARNING|UNRELIABLE)',
    r'CONFLICT\s+ZONE',
    r'HOSTILE\s+(?:ACTIVITY|ENVIRONMENT)',
    r'ANTI[-\s]?AIRCRAFT',
    r'SAM\s+(?:SITE|ACTIVITY)',
    r'NOTAM\s+(?:IMMEDIATE|URGENT)',
    r'TRIGGER\s+NOTAM'
]


# ========================================
# SCORING ALGORITHM HELPER FUNCTIONS
# ========================================
def calculate_time_decay(published_date, current_time, half_life_days=2.0):
    """Calculate exponential time decay for article relevance"""
    try:
        if isinstance(published_date, str):
            pub_dt = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
        else:
            pub_dt = published_date

        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)

        age_hours = (current_time - pub_dt).total_seconds() / 3600
        age_days = age_hours / 24

        decay_factor = math.exp(-math.log(2) * age_days / half_life_days)
        return decay_factor
    except Exception:
        return 0.1


def get_source_weight(source_name):
    """Get credibility weight for a source"""
    if not source_name:
        return 0.3

    source_lower = source_name.lower()

    for tier_data in SOURCE_WEIGHTS.values():
        for source in tier_data['sources']:
            if source.lower() in source_lower or source_lower in source.lower():
                return tier_data['weight']

    return 0.5


def detect_keyword_severity(text):
    """Detect highest severity keywords in text"""
    if not text:
        return 1.0

    text_lower = text.lower()

    for severity_level in ['active_war', 'diplomatic_crisis', 'critical', 'high', 'elevated', 'moderate']:
        for keyword in KEYWORD_SEVERITY[severity_level]['keywords']:
            if keyword in text_lower:
                return KEYWORD_SEVERITY[severity_level]['multiplier']

    return 1.0


def detect_deescalation(text):
    """Check if article indicates de-escalation"""
    if not text:
        return False

    text_lower = text.lower()

    for keyword in DEESCALATION_KEYWORDS:
        if keyword in text_lower:
            return True

    return False


def detect_diplomatic_signals(articles):
    """
    Scan articles for official diplomatic action signals (OD, embassy closure, etc.).
    Returns the highest-severity signal found and when it was first detected.
    """
    best_signal = {
        'signal_type': None,
        'signal_detected_at': None,
        'signal_phrase': None,
        'signal_source': None,
        'signal_url': None,
    }

    signal_priority = ['embassy_closure', 'ordered_departure', 'level_4_do_not_travel', 'level_3_reconsider']
    best_priority_index = len(signal_priority)

    for article in articles:
        title = (article.get('title') or '').lower()
        description = (article.get('description') or '').lower()
        content = (article.get('content') or '').lower()
        full_text = f"{title} {description} {content}"

        source_name = article.get('source', {}).get('name', 'Unknown')
        published_date = article.get('publishedAt', '')

        for signal_type in signal_priority:
            signal_config = DIPLOMATIC_SIGNAL_KEYWORDS[signal_type]
            priority_index = signal_priority.index(signal_type)

            for phrase in signal_config['phrases']:
                if phrase in full_text:
                    try:
                        if isinstance(published_date, str):
                            pub_dt = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
                        else:
                            pub_dt = published_date
                        if pub_dt.tzinfo is None:
                            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        pub_dt = datetime.now(timezone.utc)

                    if (priority_index < best_priority_index or
                        (priority_index == best_priority_index and
                         best_signal['signal_detected_at'] is not None and
                         pub_dt > best_signal['signal_detected_at'])):

                        best_priority_index = priority_index
                        best_signal = {
                            'signal_type': signal_type,
                            'signal_detected_at': pub_dt,
                            'signal_phrase': phrase,
                            'signal_source': source_name,
                            'signal_url': article.get('url', ''),
                        }
                    break

    if best_signal['signal_type']:
        print(f"[Europe v1.1] DIPLOMATIC SIGNAL: {best_signal['signal_type']}")
        print(f"  Phrase: \"{best_signal['signal_phrase']}\"")
        print(f"  Source: {best_signal['signal_source']}")
        print(f"  Date: {best_signal['signal_detected_at']}")

    return best_signal


def calculate_advisory_floor(signal_type, signal_detected_at):
    """
    Calculate the current probability floor based on signal type and time decay.
    Returns int floor percentage, or 0 if no floor applies.
    """
    if not signal_type or not signal_detected_at:
        return 0

    signal_config = DIPLOMATIC_SIGNAL_KEYWORDS.get(signal_type)
    if not signal_config:
        return 0

    now = datetime.now(timezone.utc)

    if signal_detected_at.tzinfo is None:
        signal_detected_at = signal_detected_at.replace(tzinfo=timezone.utc)

    days_since = (now - signal_detected_at).total_seconds() / 86400

    for max_days, floor_pct in signal_config['floor_schedule']:
        if days_since <= max_days:
            print(f"[Europe v1.1] Advisory floor: {floor_pct}% ({signal_type}, {days_since:.1f}d since detection)")
            return floor_pct

    print(f"[Europe v1.1] Advisory floor: 0% (signal expired, {days_since:.1f}d old)")
    return 0


# ============================================
# RHETORIC + MILITARY POSTURE BOOST HELPERS
# v1.2.0 — April 2026
# Reads Greenland rhetoric tracker from Redis and
# military posture alert level to apply calibrated
# boosts to calculate_threat_probability().
# Same pattern as ME backend Lebanon/Yemen wiring.
# ============================================

# Rhetoric level → probability boost (Greenland inverted model:
# US pressure = primary threat signal, not classic outbound strike actor)
RHETORIC_BOOST_TABLE = {
    0: 0,    # Baseline — no boost
    1: 2,    # Rhetoric — minor signal
    2: 6,    # Pressure — active coercion detected
    3: 10,   # Crisis — formal protests, NATO consultations
    4: 14,   # Confrontation — unilateral actions, military deployment
    5: 20,   # Rupture — military incident, annexation attempt
}

# Military posture alert_level → probability boost
MILITARY_POSTURE_BOOST_TABLE = {
    'normal':   0,
    'elevated': 4,
    'high':     9,
    'surge':    15,
}


def _get_military_posture_level(target):
    """
    Placeholder for Russia, Ukraine, Poland military posture boost.
    Returns ('normal', 0) until dedicated rhetoric trackers are live
    and writing Redis fingerprints for these targets.
    Will be replaced with Redis reads matching _get_greenland_military_boost()
    pattern once rhetoric_tracker_russia.py and rhetoric_tracker_ukraine.py
    are deployed.
    """
    return 'normal', 0


def _get_greenland_rhetoric_level():
    """
    Read Greenland rhetoric tracker composite level from Redis.
    Returns (theatre_level, us_pressure_level) tuple.
    Falls back to (0, 0) gracefully if unavailable.
    """
    try:
        if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
            return 0, 0
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/rhetoric:greenland:latest',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=4
        )
        result = resp.json().get('result')
        if not result:
            return 0, 0
        data = json.loads(result)
        theatre_level  = data.get('theatre_level', 0)
        us_level       = data.get('us_pressure_level', 0)
        print(f'[Europe v1.2] Greenland rhetoric: theatre L{theatre_level}, US pressure L{us_level}')
        return theatre_level, us_level
    except Exception as e:
        print(f'[Europe v1.2] Rhetoric Redis read error: {str(e)[:80]}')
        return 0, 0


def _get_greenland_military_boost():
    """
    Arctic-specific military boost for Greenland conflict probability.

    Problem this solves: the NATO theatre alert level runs HIGH/SURGE due to
    Turkey/Cyprus/Israel posture from the Iran conflict. Reading NATO or even
    the EUCOM theatre-level bleeds that into Greenland inappropriately.

    Solution: read Denmark and Greenland actor signals directly from Redis,
    then filter to only count signals that are genuinely Arctic/sovereignty-
    related (Arktisk Kommando, Pituffik, Danish frigate, Sirius patrol).
    A Danish frigate deployment to Nuuk = real Greenland signal.
    Incirlik on alert = not a Greenland signal.

    Returns (posture_label, boost_int) tuple.
    """
    ARCTIC_KEYWORDS = [
        'arktisk', 'arctic', 'greenland', 'grønland', 'pituffik', 'thule',
        'nuuk', 'sirius', 'danish frigate', 'danish navy', 'danish patrol',
        'p-8 greenland', 'danish armed forces greenland', 'danish defence',
        'baffin', 'giuk', 'kola', 'northern fleet', 'svalbard',
    ]

    try:
        if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
            return 'normal', 0

        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/military_cache',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=4
        )
        result = resp.json().get('result')
        if not result:
            return 'normal', 0

        data = json.loads(result)
        actors = data.get('actors', {})

        # Only look at Denmark and Greenland actors — never NATO aggregate
        arctic_actors = ['denmark', 'greenland']
        arctic_signal_count = 0
        max_actor_level = 'normal'
        level_order = ['normal', 'elevated', 'high', 'surge']

        for actor_id in arctic_actors:
            actor = actors.get(actor_id, {})
            if not actor:
                continue

            alert_level = actor.get('alert_level', 'normal')
            top_signals = actor.get('top_signals', [])

            # Count only signals that contain Arctic-specific keywords
            for sig in top_signals:
                sig_text = (
                    sig.get('article_title', '') + ' ' +
                    sig.get('hotspot_location', '') + ' ' +
                    sig.get('query', '')
                ).lower()

                if any(kw in sig_text for kw in ARCTIC_KEYWORDS):
                    arctic_signal_count += 1

            # Only elevate if this actor has Arctic-specific signals
            if arctic_signal_count > 0:
                if level_order.index(alert_level) > level_order.index(max_actor_level):
                    max_actor_level = alert_level

        # Apply a dampened boost table for Greenland military —
        # Danish military activity is sovereignty DEFENSE, not offense.
        # Cap at +6 (elevated equivalent) unless we have strong Arctic signals.
        GREENLAND_MIL_BOOST = {
            'normal':   0,
            'elevated': 3,   # Dampened vs standard +4
            'high':     6,   # Dampened vs standard +9
            'surge':    10,  # Dampened vs standard +15
        }

        # Further dampen if we have few specific Arctic signals
        boost = GREENLAND_MIL_BOOST.get(max_actor_level, 0)
        if arctic_signal_count == 0:
            boost = 0
            max_actor_level = 'normal'
            print(f'[Europe v1.2] Greenland mil: no Arctic-specific signals found — boost suppressed')
        elif arctic_signal_count < 3 and boost > 3:
            boost = 3
            print(f'[Europe v1.2] Greenland mil: only {arctic_signal_count} Arctic signals — boost dampened to +{boost}')

        print(f'[Europe v1.2] Greenland mil: {arctic_signal_count} Arctic signals, actor level {max_actor_level}, boost +{boost}')
        return max_actor_level, boost

    except Exception as e:
        print(f'[Europe v1.2] Greenland mil boost error: {str(e)[:80]}')
        return 'normal', 0
    """
    Read military tracker alert level for a target from Redis.
    Returns alert_level string ('normal','elevated','high','surge').
    Falls back to 'normal' gracefully.
    """
    try:
        if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
            return 'normal'
        # Military tracker writes to 'military_cache' key
        resp = requests.get(
            f'{UPSTASH_REDIS_URL}/get/military_cache',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=4
        )
        result = resp.json().get('result')
        if not result:
            return 'normal'
        data = json.loads(result)
        actors = data.get('actors', {})
        # Find the target actor — try exact match then partial
        actor_data = actors.get(target, {})
        if not actor_data:
            for k, v in actors.items():
                if target in k or k in target:
                    actor_data = v
                    break
        level = actor_data.get('alert_level', 'normal')
        print(f'[Europe v1.2] Military posture {target}: {level}')
        return level
    except Exception as e:
        print(f'[Europe v1.2] Military posture Redis read error: {str(e)[:80]}')
        return 'normal'


def calculate_threat_probability(articles, days_analyzed=7, target='ukraine'):
    """
    Calculate sophisticated threat probability score.
    Same v2.1 algorithm as Middle East backend.
    """

    if not articles:
        baseline_adjustment = TARGET_BASELINES.get(target, {}).get('base_adjustment', 0)
        return {
            'probability': min(25 + baseline_adjustment, 99),
            'momentum': 'stable',
            'breakdown': {
                'base_score': 25,
                'baseline_adjustment': baseline_adjustment,
                'article_count': 0,
                'weighted_score': 0,
                'time_decay_applied': True,
                'deescalation_detected': False
            }
        }

    current_time = datetime.now(timezone.utc)

    weighted_score = 0
    deescalation_count = 0
    recent_articles = 0
    older_articles = 0

    article_details = []

    for article in articles:
        title = article.get('title', '')
        description = article.get('description', '')
        content = article.get('content', '')
        full_text = f"{title} {description} {content}"

        source_name = article.get('source', {}).get('name', 'Unknown')
        published_date = article.get('publishedAt', '')

        time_decay = calculate_time_decay(published_date, current_time)
        source_weight = get_source_weight(source_name)
        severity_multiplier = detect_keyword_severity(full_text)
        is_deescalation = detect_deescalation(full_text)

        if is_deescalation:
            article_contribution = -3 * time_decay * source_weight
            deescalation_count += 1
        else:
            article_contribution = time_decay * source_weight * severity_multiplier

        weighted_score += article_contribution

        try:
            pub_dt = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
            age_hours = (current_time - pub_dt).total_seconds() / 3600

            if age_hours <= 48:
                recent_articles += 1
            else:
                older_articles += 1
        except Exception:
            older_articles += 1

        article_details.append({
            'source': source_name,
            'source_weight': source_weight,
            'time_decay': round(time_decay, 3),
            'severity': severity_multiplier,
            'deescalation': is_deescalation,
            'contribution': round(article_contribution, 2)
        })

    # Calculate momentum
    if recent_articles > 0 and older_articles > 0:
        recent_density = recent_articles / 2.0
        older_density = older_articles / (days_analyzed - 2) if days_analyzed > 2 else older_articles
        momentum_ratio = recent_density / older_density if older_density > 0 else 2.0

        if momentum_ratio > 1.5:
            momentum = 'increasing'
            momentum_multiplier = 1.2
        elif momentum_ratio < 0.7:
            momentum = 'decreasing'
            momentum_multiplier = 0.8
        else:
            momentum = 'stable'
            momentum_multiplier = 1.0
    else:
        momentum = 'stable'
        momentum_multiplier = 1.0

    weighted_score *= momentum_multiplier

    base_score = 25
    baseline_adjustment = TARGET_BASELINES.get(target, {}).get('base_adjustment', 0)

    if weighted_score < 0:
        probability = max(10, base_score + baseline_adjustment + weighted_score)
    else:
        probability = base_score + baseline_adjustment + (weighted_score * 0.8)

    probability = int(probability)
    probability = max(10, min(probability, 95))

    # ========================================
    # v2.9.0: TRAVEL ADVISORY FLOOR SYSTEM
    # Highest number wins: OSINT score vs advisory floor
    # ========================================
    diplomatic_signal = detect_diplomatic_signals(articles)
    advisory_floor = 0

    if diplomatic_signal['signal_type']:
        advisory_floor = calculate_advisory_floor(
            diplomatic_signal['signal_type'],
            diplomatic_signal['signal_detected_at']
        )

    if advisory_floor > 0 and advisory_floor > probability:
        print(f"[Europe v1.1] FLOOR OVERRIDE: OSINT={probability}% -> Advisory floor={advisory_floor}%")
        probability = advisory_floor

    # Final cap (advisory floor can push to 95% max, never 100%)
    probability = min(probability, 95)

    # ============================================
    # v1.2.0: RHETORIC + MILITARY POSTURE BOOSTS
    # Applied after advisory floor — highest signal wins.
    # Greenland only for now (only live rhetoric tracker).
    # Ukraine/Russia/Poland wired when trackers go live.
    # ============================================
    rhetoric_boost    = 0
    mil_boost         = 0
    rhetoric_level    = 0
    us_pressure_level = 0
    mil_posture       = 'normal'

    if target == 'greenland':
        # Read rhetoric tracker — theatre level drives primary boost.
        # US pressure level adds secondary signal (it's the threat actor here).
        rhetoric_level, us_pressure_level = _get_greenland_rhetoric_level()
        rhetoric_boost = RHETORIC_BOOST_TABLE.get(rhetoric_level, 0)

        # US pressure amplifier: if US pressure level yields a higher boost,
        # use that instead (more conservative = higher probability)
        us_boost = RHETORIC_BOOST_TABLE.get(us_pressure_level, 0)
        if us_boost > rhetoric_boost:
            rhetoric_boost = us_boost
            print(f'[Europe v1.2] Greenland: US pressure L{us_pressure_level} overrides theatre L{rhetoric_level} boost')

        # Military posture — only count Arctic-specific signals from Denmark/Greenland
        # actors. Explicitly excludes NATO aggregate to prevent Iran-conflict
        # theatre elevation (Turkey/Cyprus/Israel) from bleeding into Greenland score.
        mil_posture, mil_boost = _get_greenland_military_boost()

    elif target in ('ukraine', 'russia'):
        # Wire rhetoric boost when Ukraine/Russia trackers go live
        mil_posture = _get_military_posture_level(target)
        mil_boost   = MILITARY_POSTURE_BOOST_TABLE.get(mil_posture, 0)

    elif target == 'poland':
        mil_posture = _get_military_posture_level('poland')
        mil_boost   = MILITARY_POSTURE_BOOST_TABLE.get(mil_posture, 0)

    total_boost = rhetoric_boost + mil_boost

    if total_boost > 0:
        pre_boost   = probability
        probability = min(95, probability + total_boost)
        print(f'[Europe v1.2] {target} boost: rhetoric +{rhetoric_boost} (L{rhetoric_level}) + mil +{mil_boost} ({mil_posture}) = +{total_boost} | {pre_boost}% → {probability}%')

    print(f"[Europe v1.1] {target} scoring:")
    print(f"  Base score: {base_score}")
    print(f"  Baseline adjustment: {baseline_adjustment}")
    print(f"  Total articles: {len(articles)}")
    print(f"  Recent (48h): {recent_articles}")
    print(f"  Weighted score: {weighted_score:.2f}")
    print(f"  Momentum: {momentum} ({momentum_multiplier}x)")
    print(f"  De-escalation articles: {deescalation_count}")
    print(f"  Advisory floor: {advisory_floor}% ({diplomatic_signal.get('signal_type', 'none')})")
    print(f"  Final probability: {probability}%")

    return {
        'probability': probability,
        'momentum': momentum,
        'breakdown': {
            'base_score': base_score,
            'baseline_adjustment': baseline_adjustment,
            'article_count': len(articles),
            'recent_articles_48h': recent_articles,
            'older_articles': older_articles,
            'weighted_score': round(weighted_score, 2),
            'momentum_multiplier': momentum_multiplier,
            'deescalation_count': deescalation_count,
            'advisory_floor': advisory_floor,
            'advisory_signal_type': diplomatic_signal.get('signal_type'),
            'advisory_signal_phrase': diplomatic_signal.get('signal_phrase'),
            'advisory_signal_source': diplomatic_signal.get('signal_source'),
            'rhetoric_boost':         rhetoric_boost,
            'rhetoric_level':         rhetoric_level,
            'us_pressure_level':      us_pressure_level,
            'military_posture':       mil_posture,
            'military_boost':         mil_boost,
            'time_decay_applied': True,
            'source_weighting_applied': True,
            'formula': 'max(base(25) + adjustment + (weighted_score * 0.8), advisory_floor)'
        },
        'top_contributors': sorted(article_details,
                                   key=lambda x: abs(x['contribution']),
                                   reverse=True)[:15]
    }


# ========================================
# RATE LIMITING
# ========================================
def check_rate_limit():
    """Check if rate limit has been exceeded"""
    global rate_limit_data

    current_time = time.time()

    if current_time >= rate_limit_data['reset_time']:
        rate_limit_data['requests'] = 0
        rate_limit_data['reset_time'] = current_time + RATE_LIMIT_WINDOW

    if rate_limit_data['requests'] >= RATE_LIMIT:
        return False

    rate_limit_data['requests'] += 1
    return True


def get_rate_limit_info():
    """Get current rate limit status"""
    current_time = time.time()
    remaining = RATE_LIMIT - rate_limit_data['requests']
    resets_in = int(rate_limit_data['reset_time'] - current_time)

    return {
        'requests_used': rate_limit_data['requests'],
        'requests_remaining': max(0, remaining),
        'requests_limit': RATE_LIMIT,
        'resets_in_seconds': max(0, resets_in)
    }


# ========================================
# NEWS API FUNCTIONS
# ========================================
def fetch_newsapi_articles(query, days=7):
    """Fetch articles from NewsAPI"""
    if not NEWSAPI_KEY:
        print("[Europe v1.1] NewsAPI: No API key configured")
        return []

    from_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    url = "https://newsapi.org/v2/everything"
    params = {
        'q': query,
        'from': from_date,
        'sortBy': 'publishedAt',
        'language': 'en',
        'apiKey': NEWSAPI_KEY,
        'pageSize': 100
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])
            for article in articles:
                article['language'] = 'en'

            print(f"[Europe v1.1] NewsAPI: Fetched {len(articles)} articles")
            return articles
        print(f"[Europe v1.1] NewsAPI: HTTP {response.status_code}")
        return []
    except Exception as e:
        print(f"[Europe v1.1] NewsAPI error: {e}")
        return []


def fetch_gdelt_articles(query, days=7, language='eng'):
    """Fetch articles from GDELT"""
    try:
        wrapped_query = f"({query})" if ' OR ' in query else query

        params = {
            'query': wrapped_query,
            'mode': 'artlist',
            'maxrecords': 75,
            'timespan': f'{days}d',
            'format': 'json',
            'sourcelang': language
        }

        response = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 15))

        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])

            standardized = []
            lang_map = {
                'eng': 'en', 'rus': 'ru', 'fra': 'fr',
                'ukr': 'uk', 'pol': 'pl', 'dan': 'da',
                'deu': 'de', 'ara': 'ar'
            }
            lang_code = lang_map.get(language, 'en')

            for article in articles:
                standardized.append({
                    'title': article.get('title', ''),
                    'description': article.get('title', ''),
                    'url': article.get('url', ''),
                    'publishedAt': article.get('seendate', ''),
                    'source': {'name': article.get('domain', 'GDELT')},
                    'content': article.get('title', ''),
                    'language': lang_code
                })

            print(f"[Europe v1.1] GDELT {language}: Fetched {len(standardized)} articles")
            return standardized

        print(f"[Europe v1.1] GDELT {language}: HTTP {response.status_code}")
        return []
    except Exception as e:
        print(f"[Europe v1.1] GDELT {language} error: {e}")
        return []


def fetch_reddit_posts(target, keywords, days=7):
    """Fetch Reddit posts from relevant subreddits"""
    print(f"[Europe v1.1] Reddit: Starting fetch for {target}")

    subreddits = REDDIT_SUBREDDITS.get(target, [])
    if not subreddits:
        return []

    all_posts = []

    if days <= 1:
        time_filter = "day"
    elif days <= 7:
        time_filter = "week"
    elif days <= 30:
        time_filter = "month"
    else:
        time_filter = "year"

    for subreddit in subreddits:
        try:
            query = " OR ".join(keywords[:3])

            url = f"https://www.reddit.com/r/{subreddit}/search.json"
            params = {
                "q": query,
                "restrict_sr": "true",
                "sort": "new",
                "t": time_filter,
                "limit": 25
            }

            headers = {
                "User-Agent": REDDIT_USER_AGENT
            }

            time.sleep(2)

            response = requests.get(url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()

                if "data" in data and "children" in data["data"]:
                    posts = data["data"]["children"]

                    for post in posts:
                        post_data = post.get("data", {})

                        normalized_post = {
                            "title": post_data.get("title", "")[:200],
                            "description": post_data.get("selftext", "")[:300],
                            "url": f"https://www.reddit.com{post_data.get('permalink', '')}",
                            "publishedAt": datetime.fromtimestamp(
                                post_data.get("created_utc", 0),
                                tz=timezone.utc
                            ).isoformat(),
                            "source": {"name": f"r/{subreddit}"},
                            "content": post_data.get("selftext", ""),
                            "language": "en"
                        }

                        all_posts.append(normalized_post)

                    print(f"[Europe v1.1] Reddit r/{subreddit}: Found {len(posts)} posts")

        except Exception as e:
            print(f"[Europe v1.1] Reddit r/{subreddit} error: {str(e)}")
            continue

    print(f"[Europe v1.1] Reddit: Total {len(all_posts)} posts")
    return all_posts


# ========================================
# EUROPEAN RSS FEEDS
# ========================================
def fetch_kyiv_independent_rss():
    """Fetch articles from Kyiv Independent RSS"""
    articles = []
    feed_url = 'https://kyivindependent.com/feed/'

    try:
        print("[Europe v1.1] Kyiv Independent: Fetching RSS...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Europe v1.1] Kyiv Independent: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:20]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            description_elem = item.find('description')

            if title_elem is not None and link_elem is not None:
                pub_date = pubDate_elem.text if pubDate_elem is not None else datetime.now(timezone.utc).isoformat()
                description = ''
                if description_elem is not None and description_elem.text:
                    description = description_elem.text[:500]

                articles.append({
                    'title': title_elem.text or '',
                    'description': description,
                    'url': link_elem.text or '',
                    'publishedAt': pub_date,
                    'source': {'name': 'Kyiv Independent'},
                    'content': description,
                    'language': 'en'
                })

        print(f"[Europe v1.1] Kyiv Independent: ✓ Fetched {len(articles)} articles")

    except Exception as e:
        print(f"[Europe v1.1] Kyiv Independent error: {str(e)[:100]}")

    return articles


def fetch_meduza_rss():
    """Fetch articles from Meduza (independent Russian media, English edition)"""
    articles = []
    feed_url = 'https://meduza.io/rss/en/all'

    try:
        print("[Europe v1.1] Meduza: Fetching RSS...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Europe v1.1] Meduza: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:20]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            description_elem = item.find('description')

            if title_elem is not None and link_elem is not None:
                pub_date = pubDate_elem.text if pubDate_elem is not None else datetime.now(timezone.utc).isoformat()
                description = ''
                if description_elem is not None and description_elem.text:
                    description = description_elem.text[:500]

                articles.append({
                    'title': title_elem.text or '',
                    'description': description,
                    'url': link_elem.text or '',
                    'publishedAt': pub_date,
                    'source': {'name': 'Meduza'},
                    'content': description,
                    'language': 'en'
                })

        print(f"[Europe v1.1] Meduza: ✓ Fetched {len(articles)} articles")

    except Exception as e:
        print(f"[Europe v1.1] Meduza error: {str(e)[:100]}")

    return articles


def fetch_isw_rss():
    """Fetch articles from Institute for the Study of War (ISW)"""
    articles = []
    feed_url = 'https://www.understandingwar.org/rss.xml'

    try:
        print("[Europe v1.1] ISW: Fetching RSS...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Europe v1.1] ISW: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:15]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            description_elem = item.find('description')

            if title_elem is not None and link_elem is not None:
                pub_date = pubDate_elem.text if pubDate_elem is not None else datetime.now(timezone.utc).isoformat()
                description = ''
                if description_elem is not None and description_elem.text:
                    description = description_elem.text[:500]

                articles.append({
                    'title': title_elem.text or '',
                    'description': description,
                    'url': link_elem.text or '',
                    'publishedAt': pub_date,
                    'source': {'name': 'ISW'},
                    'content': description,
                    'language': 'en'
                })

        print(f"[Europe v1.1] ISW: ✓ Fetched {len(articles)} articles")

    except Exception as e:
        print(f"[Europe v1.1] ISW error: {str(e)[:100]}")

    return articles


def fetch_arctic_today_rss():
    """Fetch articles from Arctic Today"""
    articles = []
    feed_url = 'https://www.arctictoday.com/feed/'

    try:
        print("[Europe v1.1] Arctic Today: Fetching RSS...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Europe v1.1] Arctic Today: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:15]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            description_elem = item.find('description')

            if title_elem is not None and link_elem is not None:
                pub_date = pubDate_elem.text if pubDate_elem is not None else datetime.now(timezone.utc).isoformat()
                description = ''
                if description_elem is not None and description_elem.text:
                    description = description_elem.text[:500]

                articles.append({
                    'title': title_elem.text or '',
                    'description': description,
                    'url': link_elem.text or '',
                    'publishedAt': pub_date,
                    'source': {'name': 'Arctic Today'},
                    'content': description,
                    'language': 'en'
                })

        print(f"[Europe v1.1] Arctic Today: ✓ Fetched {len(articles)} articles")

    except Exception as e:
        print(f"[Europe v1.1] Arctic Today error: {str(e)[:100]}")

    return articles

# ========================================
# ADDITIONAL RSS FEEDS (v1.3.0 — resilience)
# ========================================

def fetch_google_news_rss(query, source_label='Google News', max_articles=15):
    """Generic Google News RSS fetcher — works for any country/topic."""
    articles = []
    feed_url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en&gl=US&ceid=US:en"

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[{source_label}] HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:max_articles]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')

            if title_elem is not None and link_elem is not None:
                pub_date = pubDate_elem.text if pubDate_elem is not None else datetime.now(timezone.utc).isoformat()
                articles.append({
                    'title': title_elem.text or '',
                    'description': title_elem.text or '',
                    'url': link_elem.text or '',
                    'publishedAt': pub_date,
                    'source': {'name': source_label},
                    'content': title_elem.text or '',
                    'language': 'en'
                })

        print(f"[{source_label}] ✓ {len(articles)} articles")

    except ET.ParseError as e:
        print(f"[{source_label}] XML parse error: {str(e)[:100]}")
    except Exception as e:
        print(f"[{source_label}] Error: {str(e)[:100]}")

    return articles


def fetch_daily_sabah_rss():
    """Fetch articles from Daily Sabah (Turkish English-language newspaper)."""
    articles = []
    feed_url = 'https://www.dailysabah.com/rssFeed/defense'

    try:
        print("[Europe v1.3] Daily Sabah: Fetching RSS...")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Europe v1.3] Daily Sabah: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:15]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            description_elem = item.find('description')

            if title_elem is not None and link_elem is not None:
                pub_date = pubDate_elem.text if pubDate_elem is not None else datetime.now(timezone.utc).isoformat()
                description = description_elem.text[:500] if description_elem is not None and description_elem.text else ''

                articles.append({
                    'title': title_elem.text or '',
                    'description': description,
                    'url': link_elem.text or '',
                    'publishedAt': pub_date,
                    'source': {'name': 'Daily Sabah'},
                    'content': description,
                    'language': 'en'
                })

        print(f"[Europe v1.3] Daily Sabah: ✓ {len(articles)} articles")

    except Exception as e:
        print(f"[Europe v1.3] Daily Sabah error: {str(e)[:100]}")

    return articles


def fetch_ukrinform_rss():
    """Fetch articles from Ukrinform (Ukrainian state news agency, English)."""
    articles = []
    feed_url = 'https://www.ukrinform.net/rss/block-lastnews'

    try:
        print("[Europe v1.3] Ukrinform: Fetching RSS...")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Europe v1.3] Ukrinform: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:20]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            description_elem = item.find('description')

            if title_elem is not None and link_elem is not None:
                pub_date = pubDate_elem.text if pubDate_elem is not None else datetime.now(timezone.utc).isoformat()
                description = description_elem.text[:500] if description_elem is not None and description_elem.text else ''

                articles.append({
                    'title': title_elem.text or '',
                    'description': description,
                    'url': link_elem.text or '',
                    'publishedAt': pub_date,
                    'source': {'name': 'Ukrinform'},
                    'content': description,
                    'language': 'en'
                })

        print(f"[Europe v1.3] Ukrinform: ✓ {len(articles)} articles")

    except Exception as e:
        print(f"[Europe v1.3] Ukrinform error: {str(e)[:100]}")

    return articles


def fetch_moscow_times_rss():
    """Fetch articles from Moscow Times (independent Russian media, English)."""
    articles = []
    feed_url = 'https://www.themoscowtimes.com/rss/news'

    try:
        print("[Europe v1.3] Moscow Times: Fetching RSS...")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(feed_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Europe v1.3] Moscow Times: HTTP {response.status_code}")
            return []

        root = ET.fromstring(response.content)
        items = root.findall('.//item')

        for item in items[:20]:
            title_elem = item.find('title')
            link_elem = item.find('link')
            pubDate_elem = item.find('pubDate')
            description_elem = item.find('description')

            if title_elem is not None and link_elem is not None:
                pub_date = pubDate_elem.text if pubDate_elem is not None else datetime.now(timezone.utc).isoformat()
                description = description_elem.text[:500] if description_elem is not None and description_elem.text else ''

                articles.append({
                    'title': title_elem.text or '',
                    'description': description,
                    'url': link_elem.text or '',
                    'publishedAt': pub_date,
                    'source': {'name': 'Moscow Times'},
                    'content': description,
                    'language': 'en'
                })

        print(f"[Europe v1.3] Moscow Times: ✓ {len(articles)} articles")

    except Exception as e:
        print(f"[Europe v1.3] Moscow Times error: {str(e)[:100]}")

    return articles
  
# ========================================
# CASUALTY TRACKING (for Ukraine/Russia)
# ========================================
CASUALTY_KEYWORDS = {
    'deaths': [
        'killed', 'dead', 'died', 'death toll', 'fatalities', 'deaths',
        'shot dead', 'killed by', 'killed in',
        'people have died', 'people have been killed',
        'убит', 'погиб', 'смерть',
        'загинув', 'загиблі', 'смерть'
    ],
    'injuries': [
        'injured', 'wounded', 'hurt', 'injuries', 'casualties',
        'hospitalized', 'critical condition', 'serious injuries',
        'ранен', 'поранен'
    ],
    'arrests': [
        'arrested', 'detained', 'detention', 'arrest', 'arrests',
        'taken into custody', 'custody', 'apprehended',
        'imprisoned', 'prisoner of war', 'POW',
        'задержан', 'арестован'
    ]
}


def parse_number_word(num_str):
    """Convert number words to integers"""
    num_str = num_str.lower().strip()

    try:
        return int(num_str)
    except ValueError:
        pass

    if ',' in num_str:
        try:
            return int(num_str.replace(',', ''))
        except ValueError:
            pass

    if 'hundred' in num_str or 'hundreds' in num_str:
        if any(word in num_str for word in ['several', 'few', 'many']):
            return 200
        return 100
    elif 'thousand' in num_str or 'thousands' in num_str:
        match = re.search(r'(\d+)\s*thousand', num_str)
        if match:
            return int(match.group(1)) * 1000
        return 1000
    elif 'dozen' in num_str or 'dozens' in num_str:
        return 12

    return 0


def extract_casualty_data(articles):
    """Extract casualty numbers from articles"""
    casualties = {
        'deaths': 0,
        'injuries': 0,
        'arrests': 0,
        'sources': set(),
        'details': [],
        'articles_without_numbers': []
    }

    number_patterns = [
        r'(\d+(?:,\d{3})*)\s+(?:people\s+)?.{0,20}?',
        r'(?:more than|over|at least)\s+(\d+(?:,\d{3})*)\s+(?:people\s+)?.{0,30}?',
        r'(\d+(?:,\d{3})*)\s+people\s+(?:have been|had been|have)\s+.{0,20}?',
        r'(hundreds?|thousands?|dozens?|several\s+(?:hundred|thousand|dozen)|many)\s+(?:people\s+)?.{0,20}?',
    ]

    for article in articles:
        title = article.get('title') or ''
        description = article.get('description') or ''
        content = article.get('content') or ''
        text = (title + ' ' + description + ' ' + content).lower()

        source = article.get('source', {}).get('name', 'Unknown')
        url = article.get('url', '')

        sentences = re.split(r'[.!?]\s+', text)

        for sentence in sentences:
            for casualty_type, keywords in CASUALTY_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in sentence:
                        casualties['sources'].add(source)
                        for pattern in number_patterns:
                            match = re.search(pattern + re.escape(keyword), sentence, re.IGNORECASE)
                            if match:
                                num = parse_number_word(match.group(1))
                                if num > casualties[casualty_type]:
                                    casualties[casualty_type] = num
                                    casualties['details'].append({
                                        'type': casualty_type,
                                        'count': num,
                                        'source': source,
                                        'url': url
                                    })
                                break
                        break

    casualties['sources'] = list(casualties['sources'])

    print(f"[Europe v1.1] ✓ Deaths: {casualties['deaths']} detected")
    print(f"[Europe v1.1] ✓ Injuries: {casualties['injuries']} detected")
    print(f"[Europe v1.1] ✓ Arrests/POWs: {casualties['arrests']} detected")

    return casualties


# ========================================
# NITTER — Executive & Government Statement Monitor (v1.5.0)
# Primary-source Twitter/X accounts via Nitter RSS mirrors.
# No API key required. Mirror fallback for resilience.
# Scope: heads of state, foreign ministers, defense ministers,
#        NATO/EU/State Dept, military commands.
# Focus: Greenland, Ukraine, European security broadly.
# ========================================

NITTER_MIRRORS = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

# (username, weight, targets[], description)
# targets: list of Europe backend target keys this account is relevant to.
#          Use ['*'] for all targets.
# weight: 1.2 = head of state / direct govt statement
#         1.1 = minister / senior official
#         1.0 = institutional / military command
#         0.9 = multilateral / monitoring
NITTER_ACCOUNTS_EUROPE = [
    # ── US pressure / NATO leadership ──────────────────────────
    ('realDonaldTrump',  1.2, ['greenland', 'ukraine', 'russia', 'poland'], 'Trump — Greenland/Ukraine/NATO statements'),
    ('SecRubio',         1.1, ['greenland', 'ukraine', 'russia', 'poland'], 'US SecState — Europe/Arctic policy'),
    ('StateDept',        1.0, ['*'],                                         'State Dept official — travel warnings, diplomatic signals'),
    ('POTUS',            1.0, ['greenland', 'ukraine'],                      'White House — executive statements'),
    # ── NATO / EU institutions ──────────────────────────────────
    ('NATO',             1.0, ['*'],                                         'NATO official — posture, Article 5, deployments'),
    ('SecGen_NATO',      1.1, ['*'],                                         'NATO Secretary General — direct statements'),
    ('eucouncil',        0.9, ['ukraine', 'russia', 'poland'],              'EU Council — sanctions, policy decisions'),
    ('EUvsDisinfo',      0.9, ['russia', 'ukraine'],                        'EU disinformation monitor — narrative signals'),
    # ── Greenland / Denmark / Arctic ───────────────────────────
    ('Statsmin',         1.2, ['greenland'],                                 'Danish Prime Minister'),
    ('DanishMFA',        1.1, ['greenland'],                                 'Danish Ministry of Foreign Affairs'),
    ('DanishDefence',    1.1, ['greenland'],                                 'Danish Defence Command — Arctic posture'),
    ('NaalakMut',        1.2, ['greenland'],                                 'Naalakkersuisut — Greenland government'),
    ('ArcticCouncil',    0.9, ['greenland'],                                 'Arctic Council — multilateral Arctic signals'),
    # ── Ukraine ─────────────────────────────────────────────────
    ('ZelenskyyUa',      1.2, ['ukraine'],                                   'Zelensky — direct statements'),
    ('MFA_Ukraine',      1.1, ['ukraine'],                                   'Ukraine MFA — diplomatic signals'),
    ('DefenceU',         1.1, ['ukraine'],                                   'Ukrainian Defence Ministry'),
    ('KyivIndependent',  0.9, ['ukraine'],                                   'Kyiv Independent — frontline reporting'),
    # ── Russia ──────────────────────────────────────────────────
    ('mod_russia',       1.1, ['russia', 'ukraine'],                        'Russian MoD — official claims/posture'),
    ('mfa_russia',       1.0, ['russia', 'ukraine'],                        'Russian MFA — diplomatic signaling'),
    # ── Poland / Baltics / Eastern flank ────────────────────────
    ('prezydentpl',      1.1, ['poland'],                                    'Polish President'),
    ('BalticDefCol',     0.9, ['poland'],                                    'Baltic Defence College — regional security'),
    # ── France / UK / Germany ───────────────────────────────────
    ('francediplo',      1.0, ['ukraine', 'greenland'],                     'French MFA — diplomatic signaling'),
    ('foreignoffice',    1.0, ['ukraine', 'greenland'],                     'UK Foreign Office'),
    # ── Military commands ────────────────────────────────────────
    ('EUCOM',            1.0, ['ukraine', 'russia', 'poland'],              'US European Command — force posture'),
    ('USArmyEurope',     0.9, ['ukraine', 'poland'],                        'US Army Europe — deployment signals'),
]


def fetch_nitter_account(username, weight=1.0, timeout=8):
    """
    Fetch RSS for one Twitter/X account via Nitter mirror fallback.
    Returns list of article dicts in Europe backend format.
    Tries each mirror in order — stops on first success.
    """
    import re as _re
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; AsifahAnalytics/1.0)'}

    for mirror in NITTER_MIRRORS:
        url = f'https://{mirror}/{username}/rss'
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            articles = []
            for item in root.findall('.//item')[:20]:
                title_el   = item.find('title')
                link_el    = item.find('link')
                pubdate_el = item.find('pubDate')
                desc_el    = item.find('description')
                if title_el is None:
                    continue
                title = title_el.text or ''
                link  = link_el.text if link_el is not None else ''
                pub   = datetime.now(timezone.utc).isoformat()
                if pubdate_el is not None and pubdate_el.text:
                    try:
                        from email.utils import parsedate_to_datetime as _pdt
                        pub = _pdt(pubdate_el.text).isoformat()
                    except Exception:
                        pub = pubdate_el.text
                desc = ''
                if desc_el is not None and desc_el.text:
                    desc = _re.sub(r'<[^>]+>', '', desc_el.text)[:400]
                articles.append({
                    'title':       title,
                    'description': desc,
                    'url':         link,
                    'publishedAt': pub,
                    'source':      {'name': f'Nitter @{username}'},
                    'content':     f'{title} {desc}',
                    'language':    'en',
                    '_nitter_weight': weight,
                })
            if articles:
                print(f'[Europe Nitter] @{username}: {len(articles)} posts via {mirror}')
                return articles
        except Exception as e:
            print(f'[Europe Nitter] @{username} {mirror} failed: {str(e)[:60]}')
            continue

    print(f'[Europe Nitter] @{username}: all mirrors failed')
    return []


def fetch_nitter_for_target(target, days=7):
    """
    Fetch Nitter posts relevant to a specific Europe target.
    Filters by target key and recency window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen_urls = set()

    for username, weight, targets, desc in NITTER_ACCOUNTS_EUROPE:
        if '*' not in targets and target not in targets:
            continue
        posts = fetch_nitter_account(username, weight=weight)
        for p in posts:
            if p['url'] in seen_urls:
                continue
            # Recency filter
            try:
                pub = datetime.fromisoformat(p['publishedAt'].replace('Z', '+00:00'))
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
            except Exception:
                pass
            seen_urls.add(p['url'])
            all_posts.append(p)
        time.sleep(0.3)

    print(f'[Europe Nitter] {target}: {len(all_posts)} posts from {sum(1 for _,_,t,_ in NITTER_ACCOUNTS_EUROPE if "*" in t or target in t)} accounts')
    return all_posts


# ========================================
# NOTAM SCANNING — FAA NOTAM Search (v1.4.0)
# Worldwide coverage, free, no API key required
# Replaces Autorouter (HTTP 401 — requires paid Eurocontrol license)
# ========================================

FAA_NOTAM_URL = "https://notams.aim.faa.gov/notamSearch/search"


def fetch_notams_for_region(region_key):
    """Fetch real NOTAMs from FAA NOTAM Search for a region."""
    region = NOTAM_REGIONS.get(region_key)
    if not region:
        return []

    notams = []
    icao_codes = region.get('icao_codes', [])[:3]  # Limit to 3 airports per region

    for code in icao_codes:
        try:
            payload = {
                'searchType': 0,
                'designatorsForLocation': code,
                'notamType': 'N',
                'formatType': 1
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            }

            print(f"[NOTAM API] Fetching {region_key}/{code} from FAA...")
            response = requests.post(FAA_NOTAM_URL, data=payload, headers=headers, timeout=15)

            if response.status_code != 200:
                print(f"[NOTAM API] {code}: HTTP {response.status_code}")
                continue

            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError):
                print(f"[NOTAM API] {code}: Non-JSON response, skipping")
                continue

            items = data.get('notamList', [])
            print(f"[NOTAM API] {code}: {len(items)} raw NOTAMs returned")

            for item in items:
                notam_text = item.get('icaoMessage', '') or item.get('traditionalMessage', '') or ''
                if not notam_text:
                    continue

                classification = classify_notam(notam_text.upper())
                if not classification:
                    continue  # Skip non-critical NOTAMs

                notams.append({
                    'region': region_key,
                    'country': region['display_name'],
                    'flag': region['flag'],
                    'type': classification['type'],
                    'type_color': classification['color'],
                    'summary': notam_text[:250],
                    'raw_text': notam_text[:500],
                    'icao_location': code,
                    'valid_from': item.get('effectiveStart', ''),
                    'valid_to': item.get('effectiveEnd', ''),
                    'icao_codes': region['icao_codes'],
                    'fir_codes': region['fir_codes'],
                    'source': 'FAA NOTAM Search',
                    'source_url': f"https://notams.aim.faa.gov/notamSearch/nsapp.html#/details/{item.get('notamNumber', '')}"
                })

            time.sleep(1)  # Rate limit courtesy

        except requests.Timeout:
            print(f"[NOTAM API] {code}: Timeout")
        except Exception as e:
            print(f"[NOTAM API] {code}: Error: {str(e)[:150]}")

    print(f"[NOTAM API] {region_key}: {len(notams)} critical NOTAMs found via FAA")
    return notams


def classify_notam(text):
    """Classify a NOTAM by severity type using pattern matching."""
    if not text:
        return None

    text_upper = text.upper()

    # Check against our critical patterns first
    for pattern in NOTAM_CRITICAL_PATTERNS:
        if re.search(pattern, text_upper):
            # Determine specific type
            if any(kw in text_upper for kw in ['CONFLICT ZONE', 'WAR ZONE', 'HOSTILE', 'ANTI-AIRCRAFT', 'SAM ']):
                return {'type': 'Conflict Zone', 'color': 'red'}
            if any(kw in text_upper for kw in ['AIRSPACE CLOSED', 'NO-FLY', 'NO FLY', 'PROHIBITED', 'CLSD']):
                return {'type': 'Airspace Closure', 'color': 'red'}
            if any(kw in text_upper for kw in ['MISSILE LAUNCH', 'MISSILE TEST', 'MISSILE FIRING', 'LIVE FIRING']):
                return {'type': 'Missile/Live Firing', 'color': 'red'}
            if any(kw in text_upper for kw in ['MIL EXERCISE', 'MILITARY EXERCISE', 'MIL OPS', 'MILITARY OPS', 'MILITARY OPERATIONS']):
                return {'type': 'Military Exercise', 'color': 'orange'}
            if any(kw in text_upper for kw in ['GPS JAMMING', 'GPS INTERFERENCE', 'GPS SPOOFING', 'NAV WARNING', 'NAVIGATION UNRELIABLE']):
                return {'type': 'GPS Interference', 'color': 'yellow'}
            if any(kw in text_upper for kw in ['DRONE', 'UAV', 'UAS', 'UNMANNED']):
                return {'type': 'Drone Activity', 'color': 'orange'}
            if any(kw in text_upper for kw in ['RESTRICTED', 'DANGER AREA', 'TEMPORARY RESTRICTION']):
                return {'type': 'Restricted Area', 'color': 'yellow'}
            if any(kw in text_upper for kw in ['TRIGGER', 'URGENT', 'IMMEDIATE']):
                return {'type': 'Urgent Notice', 'color': 'orange'}

            # Generic match
            return {'type': 'Airspace Notice', 'color': 'blue'}

    # Additional keyword checks not in the regex patterns
    if any(kw in text_upper for kw in ['AIRSPACE CLOSED', 'CLSD', 'CLOSED TO ALL']):
        return {'type': 'Airspace Closure', 'color': 'red'}
    if any(kw in text_upper for kw in ['MIL', 'MILITARY']) and any(kw in text_upper for kw in ['EXERCISE', 'OPS', 'OPERATIONS', 'ACTIVITY']):
        return {'type': 'Military Exercise', 'color': 'orange'}
    if 'DANGER AREA' in text_upper or 'RESTRICTED AREA' in text_upper:
        return {'type': 'Restricted Area', 'color': 'yellow'}

    return None


def scan_all_europe_notams():
    """Scan NOTAMs for all European regions using real API data."""
    all_notams = []

    for region_key in NOTAM_REGIONS:
        try:
            notams = fetch_notams_for_region(region_key)
            all_notams.extend(notams)
            time.sleep(1)  # Rate limit courtesy
        except Exception as e:
            print(f"[NOTAM API] Scan failed for {region_key}: {e}")

    # Sort by severity
    severity_order = {'red': 0, 'orange': 1, 'yellow': 2, 'purple': 3, 'blue': 4, 'gray': 5}
    all_notams.sort(key=lambda x: severity_order.get(x.get('type_color', 'gray'), 5))

    print(f"[NOTAM API] Total critical NOTAMs across all regions: {len(all_notams)}")
    return all_notams


# ========================================
# FLIGHT DISRUPTION MONITORING — EUROPE
# ========================================
def scan_european_flight_disruptions(all_articles):
    """Extract European flight disruptions from aggregated articles"""
    disruptions = []

    european_airlines = [
        'Lufthansa', 'Air France', 'British Airways', 'KLM', 'Ryanair',
        'Wizz Air', 'EasyJet', 'LOT Polish', 'SAS', 'Finnair',
        'Norwegian Air', 'Aeroflot', 'Turkish Airlines', 'Swiss Air',
        'Austrian Airlines', 'Brussels Airlines', 'TAP Portugal',
        'Icelandair', 'Air Baltic', 'Condor', 'Pegasus Airlines',
        'Ukraine International', 'Belavia', 'Nordica', 'airBaltic',
        'Eurowings', 'Transavia', 'Volotea', 'Air Europa',
        'Cyprus Airways', 'Cobalt Air', 'TUS Airways',
        'SunExpress', 'AnadoluJet', 'Corendon Airlines'
    ]

    flight_keywords = [
        'cancel', 'cancelled', 'cancellation', 'cancellations',
        'suspend', 'suspended', 'suspension',
        'halt', 'halted', 'ground', 'grounded',
        'divert', 'diverted', 'diversion',
        'disruption', 'disrupted', 'disruptions',
        'delay', 'delayed', 'delays',
        'reroute', 'rerouted',
        'avoid airspace', 'avoiding airspace',
        'close airspace', 'closed airspace', 'airspace closed', 'airspace closure',
        'banned from', 'restricted', 'restriction',
        'no-fly zone', 'no fly zone',
        'flight ban', 'overflight ban',
        'stranded passengers', 'travel chaos',
        'flights affected', 'routes affected'
    ]

    generic_flight_patterns = [
        'flights to', 'flights from', 'flights over',
        'all flights', 'commercial flights', 'civilian flights',
        'international flights', 'domestic flights',
        'air traffic', 'air travel', 'aviation',
        'flight operations', 'airport closed', 'airport closure',
        'runway closed', 'terminal closed'
    ]

    for article in all_articles:
        title = (article.get('title') or '').lower()
        description = (article.get('description') or '').lower()
        text = f"{title} {description}"

        matched_airline = None
        matched_keyword = None

        for airline in european_airlines:
            if airline.lower() in text:
                for keyword in flight_keywords:
                    if keyword in text:
                        matched_airline = airline
                        matched_keyword = keyword
                        break
                if matched_airline:
                    break

        if not matched_airline:
            has_flight_context = any(pattern in text for pattern in generic_flight_patterns)
            has_disruption = any(keyword in text for keyword in flight_keywords)
            has_europe_context = any(loc.lower() in text for loc in [
                'ukraine', 'russia', 'poland', 'baltic', 'europe', 'european',
                'greenland', 'denmark', 'moldova', 'romania', 'belarus',
                'kaliningrad', 'crimea', 'kyiv', 'moscow', 'warsaw',
                'nato', 'arctic',
                'turkey', 'istanbul', 'ankara', 'incirlik',
                'cyprus', 'nicosia', 'larnaca', 'akrotiri', 'paphos'
            ])

            if has_flight_context and has_disruption and has_europe_context:
                matched_airline = 'Multiple/Unspecified'
                matched_keyword = next((k for k in flight_keywords if k in text), 'disruption')

        if matched_airline and matched_keyword:
            status = 'suspended' if any(k in text for k in ['suspend', 'halt', 'cancel', 'ground', 'ban', 'closed']) else 'disrupted'
            disruptions.append({
                'airline': matched_airline,
                'status': status,
                'destination': extract_destination(text),
                'reason': extract_disruption_reason(text),
                'date': article.get('publishedAt', ''),
                'source': article.get('source', {}).get('name', 'Unknown'),
                'source_url': article.get('url', ''),
                'title': article.get('title', '')
            })

    seen = set()
    unique = []
    for d in disruptions:
        key = f"{d['airline']}_{d.get('destination', '')}"
        if key not in seen:
            seen.add(key)
            unique.append(d)

    print(f"[Europe v1.1] Flight disruptions detected: {len(unique)}")
    return unique


def extract_destination(text):
    """Extract destination from flight disruption text"""
    european_destinations = [
        'Ukraine', 'Russia', 'Moscow', 'Kyiv', 'Kiev', 'Warsaw',
        'Minsk', 'Belarus', 'Crimea', 'Moldova', 'Chisinau',
        'Kaliningrad', 'Greenland', 'Iceland', 'Arctic',
        'Baltic', 'Estonia', 'Latvia', 'Lithuania',
        'Romania', 'Bucharest', 'Poland', 'Helsinki',
        'St. Petersburg', 'Saint Petersburg',
        'Turkey', 'Istanbul', 'Ankara', 'Antalya', 'Izmir',
        'Cyprus', 'Nicosia', 'Larnaca', 'Paphos', 'Limassol'
    ]

    for dest in european_destinations:
        if dest.lower() in text:
            return dest

    return 'Unspecified European route'


def extract_disruption_reason(text):
    """Extract reason for flight disruption"""
    if any(kw in text for kw in ['war', 'conflict', 'military', 'combat']):
        return 'Active conflict zone'
    elif any(kw in text for kw in ['airspace closed', 'airspace closure', 'no-fly']):
        return 'Airspace closure'
    elif any(kw in text for kw in ['drone', 'uav', 'unmanned']):
        return 'Drone activity'
    elif any(kw in text for kw in ['sanction', 'banned', 'restriction']):
        return 'Sanctions/restrictions'
    elif any(kw in text for kw in ['gps', 'jamming', 'interference']):
        return 'GPS interference'
    elif any(kw in text for kw in ['security', 'threat', 'safety']):
        return 'Security concerns'
    return 'Unspecified disruption'

# ========================================
# TRAVEL ADVISORY SCAN FUNCTION
# ========================================
def _run_travel_advisory_scan():
    """Fetch all travel advisories from State Dept and extract our targets."""
    print("[Europe v1.1] Travel Advisories: Fetching from State Dept API...")
    results = {}

    try:
        response = requests.get(TRAVEL_ADVISORY_API, timeout=20)
        if response.status_code != 200:
            print(f"[Europe v1.1] Travel Advisories: HTTP {response.status_code}")
            return {'success': False, 'error': f'HTTP {response.status_code}', 'advisories': {}}

        all_advisories = response.json()
        print(f"[Europe v1.1] Travel Advisories: Got {len(all_advisories)} total advisories")

        for target, codes in TRAVEL_ADVISORY_CODES.items():
            for advisory in all_advisories:
                cats = advisory.get('Category', [])
                if any(code in cats for code in codes):
                    title = advisory.get('Title', '')
                    level_match = re.search(r'Level\s+(\d)', title)
                    level = int(level_match.group(1)) if level_match else None
                    published = advisory.get('Published', '')
                    updated = advisory.get('Updated', '')
                    link = advisory.get('Link', '')
                    summary_html = advisory.get('Summary', '')

                    # Extract first paragraph as short summary
                    short_summary = ''
                    summary_match = re.search(r'<p[^>]*>(.*?)</p>', summary_html, re.DOTALL)
                    if summary_match:
                        short_summary = re.sub(r'<[^>]+>', '', summary_match.group(1)).strip()

                    # Detect if recently changed (within last 30 days)
                    recently_changed = False
                    change_description = ''
                    try:
                        updated_dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                        age_days = (datetime.now(timezone.utc) - updated_dt).days
                        recently_changed = age_days <= 30

                        change_match = re.search(
                            r'(advisory level was (?:increased|decreased|raised|lowered|changed).*?\.)',
                            summary_html, re.IGNORECASE
                        )
                        if change_match:
                            change_description = re.sub(r'<[^>]+>', '', change_match.group(1)).strip()
                        elif recently_changed:
                            if 'no change' in summary_html.lower() or 'no changes to the advisory level' in summary_html.lower():
                                change_description = 'Updated (level unchanged)'
                            else:
                                change_description = f'Updated {age_days} day{"s" if age_days != 1 else ""} ago'
                    except Exception:
                        pass

                    level_info = TRAVEL_ADVISORY_LEVELS.get(level, {})

                    results[target] = {
                        'country_code': cats[0] if cats else '',
                        'title': title,
                        'level': level,
                        'level_label': level_info.get('label', 'Unknown'),
                        'level_short': level_info.get('short', 'Unknown'),
                        'level_color': level_info.get('color', '#6b7280'),
                        'published': published,
                        'updated': updated,
                        'recently_changed': recently_changed,
                        'change_description': change_description,
                        'short_summary': short_summary,
                        'link': link
                    }
                    print(f"[Europe v1.1] Travel Advisory: {target} -> Level {level} ({level_info.get('short', '?')})")
                    break

    except Exception as e:
        print(f"[Europe v1.1] Travel Advisories error: {e}")
        return {'success': False, 'error': str(e), 'advisories': {}}

    return {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'advisories': results,
        'version': '1.1.0-europe'
    }

# ========================================
# INTERNAL SCAN FUNCTIONS (used by both
# API endpoints and background refresh)
# ========================================
def _run_threat_scan(target, days=7):
    """
    Run a full threat scan for a target. Returns the complete response dict.
    Used by both the API endpoint and the background refresh thread.
    """
    query = ' OR '.join(TARGET_KEYWORDS[target]['keywords'][:8])

    # Fetch from all sources
    articles_en = fetch_newsapi_articles(query, days)
    articles_gdelt_en = fetch_gdelt_articles(query, days, 'eng')
    articles_gdelt_ru = fetch_gdelt_articles(query, days, 'rus')
    articles_gdelt_fr = fetch_gdelt_articles(query, days, 'fra')
    articles_gdelt_uk = []

    if target in ('ukraine', 'russia'):
        articles_gdelt_uk = fetch_gdelt_articles(query, days, 'ukr')

    articles_reddit = fetch_reddit_posts(
        target,
        TARGET_KEYWORDS[target]['reddit_keywords'],
        days
    )

    # Fetch target-specific RSS
    rss_articles = []
    if target in ('ukraine', 'russia'):
        try:
            rss_articles.extend(fetch_kyiv_independent_rss())
        except Exception as e:
            print(f"Kyiv Independent RSS error: {e}")
        try:
            rss_articles.extend(fetch_meduza_rss())
        except Exception as e:
            print(f"Meduza RSS error: {e}")
        try:
            rss_articles.extend(fetch_isw_rss())
        except Exception as e:
            print(f"ISW RSS error: {e}")
        try:
            rss_articles.extend(fetch_ukrinform_rss())
        except Exception as e:
            print(f"Ukrinform RSS error: {e}")
        try:
            rss_articles.extend(fetch_moscow_times_rss())
        except Exception as e:
            print(f"Moscow Times RSS error: {e}")

    if target == 'ukraine':
        try:
            rss_articles.extend(fetch_google_news_rss('Ukraine war OR missile OR drone OR frontline OR offensive', 'Ukraine War News'))
        except Exception as e:
            print(f"Ukraine Google News error: {e}")

    if target == 'russia':
        try:
            rss_articles.extend(fetch_google_news_rss('Russia military OR Ukraine OR nuclear OR mobilization OR sanctions', 'Russia News'))
        except Exception as e:
            print(f"Russia Google News error: {e}")

    if target == 'greenland':
        try:
            rss_articles.extend(fetch_arctic_today_rss())
        except Exception as e:
            print(f"Arctic Today RSS error: {e}")
        try:
            rss_articles.extend(fetch_google_news_rss('Greenland sovereignty OR arctic OR military OR NATO', 'Greenland News'))
        except Exception as e:
            print(f"Greenland Google News error: {e}")

    if target == 'poland':
        try:
            rss_articles.extend(fetch_google_news_rss('Poland military OR NATO OR border OR drone OR airspace', 'Poland News'))
        except Exception as e:
            print(f"Poland Google News error: {e}")

    if target == 'turkey':
        # Turkey RSS feeds (v1.3.0)
        try:
            rss_articles.extend(fetch_daily_sabah_rss())
        except Exception as e:
            print(f"Daily Sabah RSS error: {e}")
        try:
            rss_articles.extend(fetch_google_news_rss('Turkey military OR Incirlik OR Erdogan OR missile OR intercept', 'Turkey News'))
        except Exception as e:
            print(f"Turkey Google News error: {e}")

        # Fetch Turkey-specific war GDELT queries
        turkey_war_queries = [
            ('Turkey intercept missile Iran', 'eng'),
            ('Incirlik base attack Iran', 'eng'),
            ('Turkey air defense Iran missile', 'eng'),
            ('Turkey NATO article 5 Iran', 'eng'),
            ('Turkey scramble jets intercept', 'eng'),
            ('türkiye askeri OR savaş OR İncirlik OR hava savunma', 'tur'),
            ('İncirlik üssü saldırı OR füze', 'tur'),
            ('Türkiye hava savunma İran', 'tur'),
        ]
        for query, lang in turkey_war_queries:
            try:
                articles = fetch_gdelt_articles(query, days, lang)
                rss_articles.extend(articles)
            except Exception as e:
                print(f"Turkey GDELT ({lang}) error: {e}")

    if target == 'cyprus':
        # Cyprus RSS feeds (v1.3.0)
        try:
            rss_articles.extend(fetch_google_news_rss('Cyprus military OR Akrotiri OR drone OR attack OR evacuation', 'Cyprus News'))
        except Exception as e:
            print(f"Cyprus Google News error: {e}")

        # Fetch Cyprus-specific war GDELT queries
        cyprus_war_queries = [
            ('Cyprus Akrotiri drone attack Iran', 'eng'),
            ('Cyprus airspace closed war', 'eng'),
            ('RAF Akrotiri strike Iran drone', 'eng'),
            ('Cyprus evacuation UK forces', 'eng'),
            ('Greek F-16 intercept drone Cyprus', 'eng'),
            ('Cyprus UK base Iranian attack', 'eng'),
        ]
        for query, lang in cyprus_war_queries:
            try:
                articles = fetch_gdelt_articles(query, days, lang)
                rss_articles.extend(articles)
            except Exception as e:
                print(f"Cyprus GDELT error: {e}")

    telegram_articles = []
    if TELEGRAM_AVAILABLE:
        try:
            telegram_msgs = fetch_europe_telegram_signals(hours_back=days*24, include_extended=True)
            if telegram_msgs:
                target_kws = [kw.lower() for kw in TARGET_KEYWORDS.get(target, {}).get('keywords', [])]
                target_name = target.replace('_', ' ').lower()
                skipped = 0
                for msg in telegram_msgs:
                    msg_text = (msg.get('title', '') or '').lower()
                    relevant = target_name in msg_text or any(kw in msg_text for kw in target_kws[:15])
                    if relevant:
                        telegram_articles.append({
                            'title': msg.get('title', '')[:200],
                            'description': msg.get('title', '')[:500],
                            'url': msg.get('url', ''),
                            'publishedAt': msg.get('published', ''),
                            'source': {'name': msg.get('source', 'Telegram')},
                            'content': msg.get('title', '')[:500],
                            'language': 'multi'
                        })
                    else:
                        skipped += 1
                print(f"[Europe Scan] Telegram: {len(telegram_articles)} relevant / {skipped} skipped for {target}")
        except Exception as e:
            print(f"[Europe Scan] Telegram error: {str(e)[:100]}")


    # Nitter — executive & government statement monitor (v1.5.0)
    nitter_articles = []
    try:
        nitter_articles = fetch_nitter_for_target(target, days=days)
    except Exception as e:
        print(f"[Europe Scan] Nitter error: {str(e)[:100]}")

    all_articles = (articles_en + articles_gdelt_en + articles_gdelt_ru +
                   articles_gdelt_fr + articles_gdelt_uk + articles_reddit +
                   rss_articles + telegram_articles + nitter_articles)

    # Score
    scoring_result = calculate_threat_probability(all_articles, days, target)
    probability = scoring_result['probability']
    momentum = scoring_result['momentum']
    breakdown = scoring_result['breakdown']

    # Timeline
    if probability < 30:
        timeline = "180+ Days (Low priority)"
    elif probability < 50:
        timeline = "91-180 Days"
    elif probability < 70:
        timeline = "31-90 Days"
    else:
        timeline = "0-30 Days (Elevated threat)"

    if momentum == 'increasing' and probability > 50:
        timeline = "0-30 Days (Elevated threat)"

    # Confidence
    unique_sources = len(set(a.get('source', {}).get('name', 'Unknown') for a in all_articles))
    if len(all_articles) >= 20 and unique_sources >= 8:
        confidence = "High"
    elif len(all_articles) >= 10 and unique_sources >= 5:
        confidence = "Medium"
    else:
        confidence = "Low"

    # Top articles
    top_articles = []
    top_contributors = scoring_result.get('top_contributors', [])

    for contributor in top_contributors:
        matching_article = None
        for article in all_articles:
            if article.get('source', {}).get('name', '') == contributor['source']:
                matching_article = article
                break

        if matching_article:
            top_articles.append({
                'title': matching_article.get('title', 'No title'),
                'source': contributor['source'],
                'url': matching_article.get('url', ''),
                'publishedAt': matching_article.get('publishedAt', ''),
                'contribution': contributor['contribution'],
                'contribution_percent': abs(contributor['contribution']) / max(abs(breakdown['weighted_score']), 1) * 100,
                'severity': contributor['severity'],
                'source_weight': contributor['source_weight'],
                'time_decay': contributor['time_decay'],
                'deescalation': contributor['deescalation']
            })

    # Casualty data for Ukraine/Russia
    casualties = None
    if target in ('ukraine', 'russia'):
        try:
            casualties = extract_casualty_data(all_articles)
        except Exception as e:
            print(f"Casualty extraction error: {e}")

    # Flight disruptions
    flight_disruptions = []
    try:
        flight_disruptions = scan_european_flight_disruptions(all_articles)
    except Exception as e:
        print(f"Flight disruption scan error: {e}")

    response_data = {
        'success': True,
        'target': target,
        'region': 'europe',
        'probability': probability,
        'timeline': timeline,
        'confidence': confidence,
        'momentum': momentum,
        'total_articles': len(all_articles),
        'recent_articles_48h': breakdown.get('recent_articles_48h', 0),
        'older_articles': breakdown.get('older_articles', 0),
        'deescalation_count': breakdown.get('deescalation_count', 0),
        'scoring_breakdown': breakdown,
        'top_scoring_articles': top_articles,
        'escalation_keywords': ESCALATION_KEYWORDS,
        'target_keywords': TARGET_KEYWORDS[target]['keywords'],
        'flight_disruptions': flight_disruptions,
        'articles_en': [a for a in all_articles if a.get('language') == 'en'][:20],
        'articles_ru': [a for a in all_articles if a.get('language') == 'ru'][:20],
        'articles_fr': [a for a in all_articles if a.get('language') == 'fr'][:20],
        'articles_uk': [a for a in all_articles if a.get('language') == 'uk'][:20],
        'articles_reddit': [a for a in all_articles if a.get('source', {}).get('name', '').startswith('r/')][:20],
        'days_analyzed': days,
        'version': '1.1.0-europe'
    }

    if casualties:
        response_data['casualties'] = {
            'deaths': casualties['deaths'],
            'injuries': casualties['injuries'],
            'arrests_pows': casualties['arrests'],
            'verified_sources': casualties['sources'],
            'details': casualties.get('details', [])
        }

    return response_data


def _run_notam_scan():
    """Run a full NOTAM scan with Redis caching. Returns the complete response dict."""

    # Check Redis cache first
    is_fresh, cached = is_notam_cache_fresh()
    if is_fresh and cached:
        cached['cached'] = True
        cached['cache_source'] = 'redis'
        return cached

    # Run fresh scan
    print("[NOTAM Scan] Running fresh NOTAM scan from FAA...")
    notams = scan_all_europe_notams()

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_notams': len(notams),
        'notams': notams,
        'regions_scanned': list(NOTAM_REGIONS.keys()),
        'data_source': 'Autorouter / Eurocontrol EAD',
        'version': '1.2.0-europe',
        'cached': False
    }

    # Save to Redis
    save_notam_cache_redis(result)

    # Also save to in-memory cache
    cache_set('notams', result)

    return result


def _run_flight_scan():
    """Run a full flight disruption scan with Redis caching."""

    # Check Redis cache first
    is_fresh, cached = is_flight_cache_fresh()
    if is_fresh and cached:
        cached['cached'] = True
        cached['cache_source'] = 'redis'
        return cached

    print("[Flight Scan] Running fresh flight disruption scan...")

    flight_queries = [
        'Europe flight cancelled OR suspended OR grounded OR diverted',
        'airline cancel flights Ukraine OR Russia OR Poland OR Baltic',
        'airspace closed Europe OR Ukraine OR Russia OR Poland OR Baltic',
        'NOTAM airspace restriction Europe',
        'Ryanair OR Lufthansa OR Wizz Air cancel OR suspend flights',
        'flight disruption war zone Europe',
        'aviation safety Europe conflict',
        'Turkey Istanbul Ankara flights cancelled OR suspended',
        'Cyprus Larnaca Paphos flights cancelled OR closed',
    ]

    all_articles = []
    for fq in flight_queries:
        try:
            all_articles.extend(fetch_newsapi_articles(fq, days=3))
        except Exception as e:
            print(f"[Europe v1.1] Flight query error: {e}")
        try:
            all_articles.extend(fetch_gdelt_articles(fq, days=3, language='eng'))
        except Exception as e:
            print(f"[Europe v1.1] Flight GDELT query error: {e}")

    # Deduplicate by URL
    seen_urls = set()
    unique_articles = []
    for a in all_articles:
        url = a.get('url', '')
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_articles.append(a)

    disruptions = scan_european_flight_disruptions(unique_articles)

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_disruptions': len(disruptions),
        'disruptions': disruptions,
        'cancellations': disruptions,
        'version': '1.2.0-europe',
        'cached': False
    }

    # Save to Redis + in-memory
    save_flight_cache_redis(result)
    cache_set('flights', result)

    return result


# ========================================
# API ENDPOINTS
# ========================================

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,OPTIONS'
    return response


@app.route('/api/europe/threat/<target>', methods=['GET'])
def api_europe_threat(target):
    """
    Main threat assessment endpoint for European targets.
    Returns cached data by default. Pass ?force=true to trigger a fresh OSINT scan.
    """
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        days = int(request.args.get('days', 7))
        if target not in TARGET_KEYWORDS:
            return jsonify({
                'success': False,
                'error': f"Invalid target. Must be one of: {', '.join(TARGET_KEYWORDS.keys())}"
            }), 400
        cache_key = f'threat_{target}_{days}d'
        # Return cached data if available and not forced
        if not force:
            # Check in-memory first (fastest)
            cached = cache_get(cache_key)
            if cached:
                cached['cached'] = True
                cached['cache_source'] = 'memory'
                age = cache_age(cache_key)
                cached['cache_age_seconds'] = int(age) if age else 0
                cached['cache_age_human'] = f"{int(age / 60)}m ago" if age else 'unknown'
                return jsonify(cached)

            # Check Redis (survives deploys)
            is_fresh, redis_cached = is_threat_cache_fresh_redis(target, days)
            if is_fresh and redis_cached:
                redis_cached['cached'] = True
                redis_cached['cache_source'] = 'redis'
                redis_cached['cache_age_human'] = 'from redis'
                cache_set(cache_key, redis_cached)  # Warm in-memory
                return jsonify(redis_cached)
        # Fresh scan required — check rate limit
        if not check_rate_limit():
            return jsonify({
                'success': False,
                'error': 'Hourly limit reached. Try again later.',
                'probability': 0,
                'timeline': 'Rate limited',
                'confidence': 'Low',
                'rate_limited': True
            }), 200
        # Run fresh scan
        response_data = _run_threat_scan(target, days)
        response_data['cached'] = False
        response_data['cache_age_seconds'] = 0
        response_data['cache_age_human'] = 'fresh scan'
        # Store in cache (memory + Redis)
        cache_set(cache_key, response_data)
        save_threat_cache_redis(target, response_data, days)
        return jsonify(response_data)
    except Exception as e:
        print(f"Error in /api/europe/threat/{target}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'probability': 0,
            'timeline': 'Unknown',
            'confidence': 'Low'
        }), 500

@app.route('/api/europe/dashboard', methods=['GET'])
def api_europe_dashboard():
    """
    Single batch endpoint — returns all 4 country scores in one response.
    Dramatically reduces frontend round trips from 4 to 1.
    Returns cached data by default. Pass ?force=true to trigger fresh scans.
    """
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        days = int(request.args.get('days', 7))
        targets = list(TARGET_KEYWORDS.keys())

        dashboard = {
            'success': True,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version': '1.1.0-europe',
            'countries': {}
        }

        all_cached = True

        for target in targets:
            cache_key = f'threat_{target}_{days}d'

            if not force:
                cached = cache_get(cache_key)
                if cached:
                    # Return collapsed summary for dashboard
                    dashboard['countries'][target] = {
                        'probability': cached.get('probability', 0),
                        'momentum': cached.get('momentum', 'stable'),
                        'timeline': cached.get('timeline', 'Unknown'),
                        'confidence': cached.get('confidence', 'Low'),
                        'total_articles': cached.get('total_articles', 0),
                        'flight_disruptions': len(cached.get('flight_disruptions', [])),
                        'cached': True,
                        'cache_age_seconds': int(cache_age(cache_key) or 0)
                    }
                    continue

            # Cache miss — run fresh scan
            all_cached = False
            if not check_rate_limit():
                dashboard['countries'][target] = {
                    'probability': 0,
                    'error': 'Rate limited',
                    'cached': False
                }
                continue

            data = _run_threat_scan(target, days=days)
            cache_set(cache_key, data)

            dashboard['countries'][target] = {
                'probability': data.get('probability', 0),
                'momentum': data.get('momentum', 'stable'),
                'timeline': data.get('timeline', 'Unknown'),
                'confidence': data.get('confidence', 'Low'),
                'total_articles': data.get('total_articles', 0),
                'flight_disruptions': len(data.get('flight_disruptions', [])),
                'cached': False,
                'cache_age_seconds': 0
            }

        dashboard['all_cached'] = all_cached

        return jsonify(dashboard)

    except Exception as e:
        print(f"Error in /api/europe/dashboard: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/europe/notams', methods=['GET'])
def api_europe_notams():
    """European NOTAMs endpoint. Redis-cached with ?force=true override."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'

        if not force:
            # Check in-memory first
            cached = cache_get('notams')
            if cached:
                cached['cached'] = True
                cached['cache_source'] = 'memory'
                cached['cache_age_seconds'] = int(cache_age('notams') or 0)
                return jsonify(cached)

            # Check Redis (survives deploys)
            is_fresh, redis_cached = is_notam_cache_fresh()
            if is_fresh and redis_cached:
                redis_cached['cached'] = True
                redis_cached['cache_source'] = 'redis'
                cache_set('notams', redis_cached)  # Warm in-memory
                return jsonify(redis_cached)

        if not check_rate_limit():
            return jsonify({
                'error': 'Rate limit exceeded',
                'rate_limit': get_rate_limit_info()
            }), 429

        data = _run_notam_scan()
        return jsonify(data)

    except Exception as e:
        print(f"Error in /api/europe/notams: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'notams': [],
            'total_notams': 0
        }), 500


@app.route('/api/europe/flights', methods=['GET'])
def api_europe_flights():
    """European flight disruptions endpoint. Redis-cached with ?force=true override."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'

        if not force:
            # Check in-memory first
            cached = cache_get('flights')
            if cached:
                cached['cached'] = True
                cached['cache_source'] = 'memory'
                cached['cache_age_seconds'] = int(cache_age('flights') or 0)
                return jsonify(cached)

            # Check Redis (survives deploys)
            is_fresh, redis_cached = is_flight_cache_fresh()
            if is_fresh and redis_cached:
                redis_cached['cached'] = True
                redis_cached['cache_source'] = 'redis'
                cache_set('flights', redis_cached)  # Warm in-memory
                return jsonify(redis_cached)

        if not check_rate_limit():
            return jsonify({
                'error': 'Rate limit exceeded',
                'rate_limit': get_rate_limit_info()
            }), 429

        data = _run_flight_scan()
        return jsonify(data)

    except Exception as e:
        print(f"Error in /api/europe/flights: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'disruptions': [],
            'cancellations': []
        }), 500

@app.route('/api/europe/travel-advisories', methods=['GET'])
def api_europe_travel_advisories():
    """U.S. State Dept Travel Advisories for European targets. Cached 24h."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'

        if not force:
            cached = cache_get('travel_advisories')
            if cached:
                cached['cached'] = True
                cached['cache_age_seconds'] = int(cache_age('travel_advisories') or 0)
                return jsonify(cached)
            # Redis fallback — survives cold starts
            redis_cached = load_threat_cache_redis('travel_advisories', days=1)
            if redis_cached:
                redis_cached['cached'] = True
                redis_cached['cache_source'] = 'redis'
                cache_set('travel_advisories', redis_cached)
                return jsonify(redis_cached)

        data = _run_travel_advisory_scan()
        data['cached'] = False
        cache_set('travel_advisories', data)

        return jsonify(data)

    except Exception as e:
        print(f"Error in /api/europe/travel-advisories: {e}")
        return jsonify({'success': False, 'error': str(e), 'advisories': {}}), 500

@app.route('/api/europe/cache-status', methods=['GET'])
def api_cache_status():
    """
    Diagnostic endpoint — shows what's in cache and how old it is.
    Useful for debugging and monitoring.
    """
    status = {}
    targets = list(TARGET_KEYWORDS.keys())

    for target in targets:
        age = cache_age(f'threat_{target}')
        status[target] = {
            'cached': age is not None,
            'age_seconds': int(age) if age else None,
            'age_human': f"{int(age / 60)}m ago" if age else 'empty',
            'fresh': age is not None and age < CACHE_TTL
        }

    for key in ['notams', 'flights']:
        age = cache_age(key)
        status[key] = {
            'cached': age is not None,
            'age_seconds': int(age) if age else None,
            'age_human': f"{int(age / 60)}m ago" if age else 'empty',
            'fresh': age is not None and age < CACHE_TTL
        }

    status['cache_ttl_seconds'] = CACHE_TTL
    status['cache_ttl_human'] = f"{CACHE_TTL / 3600:.0f} hours"

    return jsonify(status)


@app.route('/rate-limit', methods=['GET'])
def rate_limit_status():
    """Rate limit status endpoint"""
    return jsonify(get_rate_limit_info())


@app.route('/robots.txt')
def robots():
    """Block all bots from crawling API endpoints."""
    return "User-agent: *\nDisallow: /\n", 200, {'Content-Type': 'text/plain'}


@app.route('/', methods=['GET'])
def home():
    """Root endpoint"""
    return jsonify({
        'status': 'Backend is running',
        'message': 'Asifah Analytics — Europe API v1.1.0',
        'version': '1.1.0',
        'region': 'europe',
        'features': [
            'In-memory response caching (4-hour TTL)',
            'Background refresh thread (auto-refreshes all caches)',
            'Single dashboard endpoint (/api/europe/dashboard)',
            'Force fresh scan with ?force=true'
        ],
        'targets': list(TARGET_KEYWORDS.keys()),
        'endpoints': {
            '/api/europe/threat/<target>': 'Get threat assessment (cached, ?force=true for fresh)',
            '/api/europe/dashboard': 'Get all 4 country scores in one call (cached)',
            '/api/europe/notams': 'Get European NOTAMs (cached, ?force=true for fresh)',
            '/api/europe/flights': 'Get European flight disruptions (cached, ?force=true for fresh)',
            '/api/europe/cache-status': 'See cache freshness for all endpoints',
            '/rate-limit': 'Get rate limit status',
            '/health': 'Health check'
        }
    })


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'version': '1.1.0-europe',
        'region': 'europe',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'cache_entries': len(_cache)
    })

# Register Ukraine humanitarian endpoints
if UKRAINE_HUMANITARIAN_AVAILABLE:
    register_ukraine_humanitarian_endpoints(app)

# Register Greenland rhetoric tracker
if GREENLAND_RHETORIC_AVAILABLE:
    register_greenland_rhetoric_routes(app)
    print("[Europe Backend] ✅ Greenland rhetoric routes registered")
  
# ========================================
# START BACKGROUND REFRESH ON BOOT
# ========================================
# Start the background thread when the app boots.
# On Render with gunicorn, this runs once per worker.
start_background_refresh()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
