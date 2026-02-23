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

app = Flask(__name__)
CORS(app)

# ========================================
# CONFIGURATION
# ========================================
NEWSAPI_KEY = os.environ.get('NEWSAPI_KEY')
GDELT_BASE_URL = "http://api.gdeltproject.org/api/v2/doc/doc"

# Cache TTL in seconds (4 hours)
CACHE_TTL = 4 * 60 * 60

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
# BACKGROUND REFRESH THREAD
# ========================================
def _refresh_all_caches():
    """
    Refresh all cached data in the background.
    Runs every CACHE_TTL seconds so no user request ever triggers a cold scan.
    """
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
                print(f"[Background Refresh] ✓ {target} cached (probability: {data.get('probability', '?')}%)")
            except Exception as e:
                print(f"[Background Refresh] ✗ {target} failed: {e}")

            # Small delay between targets to avoid hammering APIs
            time.sleep(5)

        # Refresh NOTAMs
        try:
            print("[Background Refresh] Refreshing NOTAMs...")
            notam_data = _run_notam_scan()
            cache_set('notams', notam_data)
            print(f"[Background Refresh] ✓ NOTAMs cached ({notam_data.get('total_notams', 0)} alerts)")
        except Exception as e:
            print(f"[Background Refresh] ✗ NOTAMs failed: {e}")

        time.sleep(5)

        # Refresh flight disruptions
        try:
            print("[Background Refresh] Refreshing flights...")
            flight_data = _run_flight_scan()
            cache_set('flights', flight_data)
            print(f"[Background Refresh] ✓ Flights cached ({flight_data.get('total_disruptions', 0)} disruptions)")
        except Exception as e:
            print(f"[Background Refresh] ✗ Flights failed: {e}")

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
            'The Barents Observer', 'High North News'
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
    'poland': ['poland', 'Polska', 'europe', 'geopolitics', 'worldnews']
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
    'cyber attack', 'sabotage', 'disinformation'
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

    for severity_level in ['critical', 'high', 'elevated', 'moderate']:
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

    print(f"[Europe v1.1] {target} scoring:")
    print(f"  Base score: {base_score}")
    print(f"  Baseline adjustment: {baseline_adjustment}")
    print(f"  Total articles: {len(articles)}")
    print(f"  Recent (48h): {recent_articles}")
    print(f"  Weighted score: {weighted_score:.2f}")
    print(f"  Momentum: {momentum} ({momentum_multiplier}x)")
    print(f"  De-escalation articles: {deescalation_count}")
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
            'time_decay_applied': True,
            'source_weighting_applied': True,
            'formula': 'base(25) + adjustment + (weighted_score * 0.8)'
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

        response = requests.get(GDELT_BASE_URL, params=params, timeout=15)

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
# NOTAM SCANNING
# ========================================
def fetch_notams_for_region(region_key):
    """Fetch NOTAMs for a European region using news-based NOTAM detection."""
    region = NOTAM_REGIONS.get(region_key)
    if not region:
        return []

    notams = []

    icao_query = ' OR '.join(region['icao_codes'][:3])
    display_name = region['display_name']

    try:
        notam_query = (
            f"({display_name} NOTAM) OR ({display_name} airspace) OR ({icao_query} airspace) OR "
            f"({display_name} airspace closed) OR ({display_name} airspace restriction) OR "
            f"({display_name} no-fly zone) OR ({display_name} GPS jamming) OR "
            f"({display_name} military exercise airspace) OR ({display_name} drone airspace) OR "
            f"({display_name} flight restriction) OR ({display_name} aviation warning)"
        )
        params = {
            'query': notam_query,
            'mode': 'artlist',
            'maxrecords': 25,
            'timespan': '7d',
            'format': 'json',
            'sourcelang': 'eng'
        }

        response = requests.get(GDELT_BASE_URL, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            articles = data.get('articles', [])

            for article in articles:
                title = (article.get('title', '') or '').upper()
                url = article.get('url', '')
                seen_date = article.get('seendate', '')

                notam_type = classify_notam(title)
                if notam_type:
                    notams.append({
                        'region': region_key,
                        'country': display_name,
                        'flag': region['flag'],
                        'type': notam_type['type'],
                        'type_color': notam_type['color'],
                        'summary': title[:200],
                        'source': article.get('domain', 'GDELT'),
                        'source_url': url,
                        'issued': seen_date,
                        'icao_codes': region['icao_codes'],
                        'fir_codes': region['fir_codes']
                    })

    except Exception as e:
        print(f"[Europe v1.1] NOTAM scan error for {region_key}: {e}")

    print(f"[Europe v1.1] NOTAMs for {display_name}: Found {len(notams)} alerts")
    return notams


def classify_notam(text):
    """Classify a NOTAM by severity type"""
    text_upper = text.upper() if text else ''

    if any(kw in text_upper for kw in ['CONFLICT ZONE', 'WAR ZONE', 'HOSTILE', 'ANTI-AIRCRAFT', 'SAM ']):
        return {'type': 'Conflict Zone', 'color': 'red'}
    if any(kw in text_upper for kw in ['AIRSPACE CLOSED', 'NO-FLY', 'NO FLY', 'PROHIBITED']):
        return {'type': 'Airspace Closure', 'color': 'red'}
    if any(kw in text_upper for kw in ['MILITARY EXERCISE', 'MIL EXERCISE', 'LIVE FIRING', 'MISSILE LAUNCH', 'MISSILE TEST']):
        return {'type': 'Military Exercise', 'color': 'orange'}
    if any(kw in text_upper for kw in ['GPS JAMMING', 'GPS INTERFERENCE', 'GPS SPOOFING', 'NAVIGATION WARNING', 'NAVIGATION UNRELIABLE']):
        return {'type': 'GPS Interference', 'color': 'yellow'}
    if any(kw in text_upper for kw in ['DRONE', 'UAV', 'UAS', 'UNMANNED']):
        return {'type': 'Drone Activity', 'color': 'orange'}
    if any(kw in text_upper for kw in ['RESTRICTED', 'DANGER AREA', 'TEMPORARY RESTRICTION']):
        return {'type': 'Restricted Area', 'color': 'yellow'}
    if 'NOTAM' in text_upper or 'AIRSPACE' in text_upper:
        return {'type': 'Airspace Notice', 'color': 'blue'}

    return None


def scan_all_europe_notams():
    """Scan NOTAMs for all European regions"""
    all_notams = []

    for region_key in NOTAM_REGIONS:
        try:
            notams = fetch_notams_for_region(region_key)
            all_notams.extend(notams)
        except Exception as e:
            print(f"[Europe v1.1] NOTAM scan failed for {region_key}: {e}")

    severity_order = {'red': 0, 'orange': 1, 'yellow': 2, 'purple': 3, 'blue': 4, 'gray': 5}
    all_notams.sort(key=lambda x: severity_order.get(x.get('type_color', 'gray'), 5))

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
        'Eurowings', 'Transavia', 'Volotea', 'Air Europa'
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
                'nato', 'arctic'
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
        'St. Petersburg', 'Saint Petersburg'
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

    if target == 'greenland':
        try:
            rss_articles.extend(fetch_arctic_today_rss())
        except Exception as e:
            print(f"Arctic Today RSS error: {e}")

    all_articles = (articles_en + articles_gdelt_en + articles_gdelt_ru +
                   articles_gdelt_fr + articles_gdelt_uk + articles_reddit +
                   rss_articles)

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
    """Run a full NOTAM scan. Returns the complete response dict."""
    notams = scan_all_europe_notams()

    return {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_notams': len(notams),
        'notams': notams,
        'regions_scanned': list(NOTAM_REGIONS.keys()),
        'version': '1.1.0-europe'
    }


def _run_flight_scan():
    """Run a full flight disruption scan. Returns the complete response dict."""
    flight_queries = [
        'Europe flight cancelled OR suspended OR grounded OR diverted',
        'airline cancel flights Ukraine OR Russia OR Poland OR Baltic',
        'airspace closed Europe OR Ukraine OR Russia OR Poland OR Baltic',
        'NOTAM airspace restriction Europe',
        'Ryanair OR Lufthansa OR Wizz Air cancel OR suspend flights',
        'flight disruption war zone Europe',
        'aviation safety Europe conflict'
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

    return {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_disruptions': len(disruptions),
        'disruptions': disruptions,
        'cancellations': disruptions,
        'version': '1.1.0-europe'
    }


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
@cross_origin()
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
            cached = cache_get(cache_key)
            if cached:
                cached['cached'] = True
                age = cache_age(cache_key)
                cached['cache_age_seconds'] = int(age) if age else 0
                cached['cache_age_human'] = f"{int(age / 60)}m ago" if age else 'unknown'
                return jsonify(cached)
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
        # Store in cache
        cache_set(cache_key, response_data)
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
    """European NOTAMs endpoint. Cached with ?force=true override."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'

        if not force:
            cached = cache_get('notams')
            if cached:
                cached['cached'] = True
                cached['cache_age_seconds'] = int(cache_age('notams') or 0)
                return jsonify(cached)

        if not check_rate_limit():
            return jsonify({
                'error': 'Rate limit exceeded',
                'rate_limit': get_rate_limit_info()
            }), 429

        data = _run_notam_scan()
        data['cached'] = False
        cache_set('notams', data)

        return jsonify(data)

    except Exception as e:
        print(f"Error in /api/europe/notams: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'notams': []
        }), 500


@app.route('/api/europe/flights', methods=['GET'])
@cross_origin()
def api_europe_flights():
    """European flight disruptions endpoint. Cached with ?force=true override."""
    try:
        force = request.args.get('force', 'false').lower() == 'true'

        if not force:
            cached = cache_get('flights')
            if cached:
                cached['cached'] = True
                cached['cache_age_seconds'] = int(cache_age('flights') or 0)
                return jsonify(cached)

        if not check_rate_limit():
            return jsonify({
                'error': 'Rate limit exceeded',
                'rate_limit': get_rate_limit_info()
            }), 429

        data = _run_flight_scan()
        data['cached'] = False
        cache_set('flights', data)

        return jsonify(data)

    except Exception as e:
        print(f"Error in /api/europe/flights: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'disruptions': [],
            'cancellations': []
        }), 500


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


# ========================================
# START BACKGROUND REFRESH ON BOOT
# ========================================
# Start the background thread when the app boots.
# On Render with gunicorn, this runs once per worker.
start_background_refresh()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
