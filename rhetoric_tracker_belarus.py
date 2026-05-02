"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — BELARUS RHETORIC TRACKER
  v1.0.0 (Apr 30 2026)
═══════════════════════════════════════════════════════════════════════

Multi-actor rhetoric tracker for Belarus. Aggregates signals across:
  - RSS (NEXTA, Meduza, RFE/RL Belarus, Viasna, BelTA, Reuters)
  - GDELT multi-language queries (English + Russian Cyrillic)
  - NewsAPI fallback
  - Brave Search tertiary fallback
  - Telegram channels (BELARUS_CHANNELS from telegram_signals_europe)
  - Bluesky (Tsikhanouskaya, NEXTA, opposition figures)
  - Reddit (/r/belarus, /r/europe, /r/credibledefense)

Calls belarus_signal_interpreter.interpret_signals() for analytical layer
(red lines, green lines, So What, top_signals, fingerprints).

Writes Redis cache key 'rhetoric:belarus:latest' for consumption by
europe_regional_bluf.py and the rhetoric-belarus.html frontend.

ENDPOINTS:
  GET /api/rhetoric/belarus          — full scan result
  GET /api/rhetoric/belarus/summary  — short-form for hub pages
  GET /api/rhetoric/belarus/history  — recent scans (paginated)

BACKGROUND REFRESH:
  Runs every 6 hours in a daemon thread (canonical pattern).
"""

import os
import json
import time
import threading
import requests
import feedparser
from datetime import datetime, timezone
from flask import jsonify, request

# Optional: telegram + bluesky integration (graceful if unavailable)
try:
    from telegram_signals_europe import fetch_belarus_telegram_signals
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print('[Belarus Rhetoric] Telegram signals not available')

try:
    from bluesky_signals_europe import fetch_belarus_bluesky_signals
    BLUESKY_AVAILABLE = True
except ImportError:
    BLUESKY_AVAILABLE = False
    print('[Belarus Rhetoric] Bluesky signals not available')

from belarus_signal_interpreter import interpret_signals

# ============================================================
# CONFIGURATION
# ============================================================

UPSTASH_REDIS_URL    = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN  = os.environ.get('UPSTASH_REDIS_TOKEN')
NEWSAPI_KEY          = os.environ.get('NEWSAPI_KEY')
BRAVE_API_KEY        = os.environ.get('BRAVE_API_KEY')

GDELT_BASE_URL       = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI_BASE_URL     = 'https://newsapi.org/v2/everything'
BRAVE_BASE_URL       = 'https://api.search.brave.com/res/v1/news/search'

REDIS_KEY_LATEST     = 'rhetoric:belarus:latest'
REDIS_KEY_HISTORY    = 'rhetoric:belarus:history'
REFRESH_INTERVAL_SEC = 6 * 3600   # 6h

_scan_lock = threading.Lock()


# ============================================================
# RSS FEEDS
# ============================================================
RSS_FEEDS = [
    # Independent / opposition
    {'name': 'NEXTA',                     'url': 'https://nexta.tv/en/rss',                                'weight': 0.95},
    {'name': 'Meduza (English)',          'url': 'https://meduza.io/rss/en/all',                           'weight': 0.90},
    {'name': 'RFE/RL Belarus Service',    'url': 'https://www.rferl.org/api/zypppgmm-en',                  'weight': 0.95},
    {'name': 'Viasna Human Rights',       'url': 'https://spring96.org/en/rss',                            'weight': 0.95},
    # International coverage
    {'name': 'Reuters Europe',            'url': 'https://www.reutersagency.com/feed/?best-regions=europe&post_type=best',  'weight': 0.90},
    {'name': 'Politico Europe',           'url': 'https://www.politico.eu/feed/',                          'weight': 0.85},
    {'name': 'Euractiv',                  'url': 'https://www.euractiv.com/feed/',                         'weight': 0.80},
    # State / regime (counter-narrative)
    {'name': 'BelTA (state media)',       'url': 'https://eng.belta.by/rss',                               'weight': 0.65},
]


# ============================================================
# ACTORS (7-actor framework per analytical plan)
# ============================================================
ACTORS = {
    'lukashenko_regime': {
        'name': 'Lukashenko Regime',
        'flag': '🇧🇾',
        'icon': '👤',
        'color': '#dc2626',
        'role': 'Domestic regime apparatus, KGB, propaganda, succession',
        'description': (
            'Lukashenko personally + presidential administration + KGB + '
            'security services. Watch for: succession signals, health '
            'language, opposition crackdown intensity, Article 130 cases, '
            'rhetoric tone shifts, propaganda lines.'
        ),
        'keywords': [
            'lukashenko', 'aleksandr lukashenko', 'alexander lukashenko',
            'belarusian president', 'pul_1', 'presidential administration belarus',
            'belarusian kgb', 'kgb belarus', 'belarusian security service',
            'minsk regime', 'belarusian propaganda',
            'лукашенко', 'президент беларуси',
            'health concerns', 'absent from public', 'medical leave',
            'transitional council', 'succession belarus',
        ],
    },
    'russian_forces_in_belarus': {
        'name': 'Russian Forces in Belarus',
        'flag': '🇷🇺',
        'icon': '⚔️',
        'color': '#7f1d1d',
        'role': 'Russian military deployments, nuclear systems, Ukraine staging',
        'description': (
            'Russian forces stationed in or operating from Belarusian '
            'territory. Watch for: Iskander movements, Asipovichy nuclear '
            'storage, joint exercises (Zapad), staging for Ukraine '
            'operations, S-400 deployments.'
        ),
        'keywords': [
            'russian forces belarus', 'russian troops belarus',
            'iskander belarus', 'asipovichy', 'nuclear storage belarus',
            'tactical nuclear belarus', 'warhead belarus',
            'zapad exercise', 'russian-belarusian exercise',
            's-400 belarus', 'air defense belarus', 'russian instructors belarus',
            'российские войска беларусь', 'искандер беларусь',
            'тактическое ядерное', 'учения запад',
        ],
    },
    'belarusian_opposition': {
        'name': 'Belarusian Opposition',
        'flag': '✊',
        'icon': '🟥⬜🟥',
        'color': '#16a34a',
        'role': 'Tsikhanouskaya, Coordination Council, Kalinouski Regiment, exiles',
        'description': (
            'Democratic opposition operating primarily from Vilnius/Warsaw/'
            'Berlin. Watch for: Tsikhanouskaya statements, United Transitional '
            'Cabinet decisions, prisoner releases, Kalinouski Regiment '
            'developments, NEXTA reporting.'
        ),
        'keywords': [
            'tsikhanouskaya', 'sviatlana tsikhanouskaya', 'svetlana tikhanovskaya',
            'united transitional cabinet', 'coordination council belarus',
            'kalinouski regiment', 'kalinouski battalion',
            'nexta', 'belsat', 'viasna', 'bialiatski', 'ales bialiatski',
            'belarusian opposition', 'belarusian dissidents',
            'political prisoners belarus', 'belarusian exiles',
            'тихановская', 'координационный совет',
        ],
    },
    'nato_border_states': {
        'name': 'NATO Border States',
        'flag': '🇵🇱🇱🇹🇱🇻',
        'icon': '🛡️',
        'color': '#3b82f6',
        'role': 'Poland + Lithuania + Latvia coordinated response',
        'description': (
            'NATO neighbors\' coordinated response — border closures, '
            'troop deployments, migrant pushback, EU/NATO advocacy. '
            'Treated as one actor because they coordinate so closely '
            '(joint declarations, EU sanction packages, NATO statements).'
        ),
        'keywords': [
            'poland border belarus', 'lithuania border belarus',
            'latvia border belarus', 'frontex', 'polish border guard',
            'lithuanian border', 'latvian border guard',
            'suwalki gap', 'suwałki', 'baltic land bridge',
            'nato eastern flank', 'nato forward presence',
            'polish-belarusian border', 'bialystok',
            'migrant pushback', 'border barrier belarus', 'border wall',
            'польша беларусь граница', 'литва беларусь',
        ],
    },
    'iran_belarus_axis': {
        'name': 'Iran-Belarus Axis',
        'flag': '🇮🇷🇧🇾',
        'icon': '🤝',
        'color': '#a16207',
        'role': 'SCO trilateral, defense cooperation, Apr 27 trilateral',
        'description': (
            'Defense and political cooperation between Tehran and Minsk, '
            'particularly via SCO framework. Watch for: Khrenin–Talaei-Nik '
            'meetings, drone technology transfer, joint exercise language, '
            'SCO trilateral signals.'
        ),
        'keywords': [
            'khrenin talaei', 'khrenin tehran', 'minsk tehran',
            'belarus iran cooperation', 'iran belarus defense',
            'iran belarus military', 'sco belarus iran',
            'shanghai cooperation belarus iran',
            'iranian defense minister belarus', 'belarus defense iran',
            'shahed belarus', 'iran drone belarus',
            'трехсторонний иран беларусь', 'иран беларусь оборона',
        ],
    },
    'china_belarus_axis': {
        'name': 'China-Belarus Axis',
        'flag': '🇨🇳🇧🇾',
        'icon': '🏗️',
        'color': '#7c3aed',
        'role': 'SCO membership, BRI rail, Great Stone industrial park',
        'description': (
            'Strategic anchor relationship — SCO full membership 2024, '
            'Great Stone industrial park, BRI rail (sanctions bypass for '
            'Belarusian potash/petroleum), PLA military cooperation MoUs.'
        ),
        'keywords': [
            'china belarus', 'beijing minsk', 'great stone industrial park',
            'belt and road belarus', 'bri rail belarus',
            'china-belarus military', 'pla belarus', 'plaaf belarus',
            'sco belarus full member', 'shanghai cooperation belarus china',
            'chinese investment belarus', 'china belarus partnership',
            'китай беларусь', 'великий камень',
        ],
    },
    'ukraine_border_signals': {
        'name': 'Ukraine Border Signals',
        'flag': '🇺🇦',
        'icon': '🚀',
        'color': '#0891b2',
        'role': 'Ukraine border drone attacks, missile staging visibility',
        'description': (
            'Activity along the 1,084 km Belarus–Ukraine border. Watch for: '
            'Ukrainian drone strikes on Belarusian airfields, Russian '
            'missile launches from Belarusian territory, Belarusian border '
            'troop movements, refugee/border crossing dynamics.'
        ),
        'keywords': [
            'belarus ukraine border', 'belarusian-ukrainian border',
            'machulishchy', 'baranavichy airbase', 'lida airbase',
            'ukrainian drone belarus', 'kyiv strike belarus airfield',
            'russian missile from belarus', 'cruise missile belarus',
            'ukrainian partisan belarus', 'belarus-ukraine frontier',
            'граница беларусь украина', 'удар беспилотник беларусь',
        ],
    },
}


# ============================================================
# GDELT QUERIES
# ============================================================
GDELT_QUERIES = {
    'eng': [
        '"belarus" AND ("lukashenko" OR "minsk")',
        '"belarus" AND ("nato" OR "poland" OR "lithuania")',
        '"belarus" AND ("iran" OR "sco" OR "khrenin")',
        '"belarus" AND ("nuclear" OR "iskander" OR "asipovichy")',
        '"belarus" AND ("opposition" OR "tsikhanouskaya" OR "viasna")',
        '"belarus" AND ("china" OR "great stone" OR "bri")',
        '"belarus border" AND ("ukraine" OR "drone" OR "strike")',
    ],
    'rus': [
        '"беларусь" AND ("лукашенко" OR "минск")',
        '"беларусь" AND ("нато" OR "польша" OR "литва")',
        '"беларусь" AND ("иран" OR "шос")',
        '"беларусь" AND ("ядерное" OR "искандер")',
    ],
}


# ============================================================
# KEYWORDS FOR REDDIT / GENERAL FILTERING
# ============================================================
BELARUS_TOPIC_KEYWORDS = [
    'belarus', 'belarusian', 'lukashenko', 'minsk', 'nexta',
    'tsikhanouskaya', 'tikhanovskaya', 'belaruskali', 'asipovichy',
    'viasna', 'bialiatski', 'kalinouski', 'pul_1',
    'беларусь', 'белоруссия', 'лукашенко', 'минск',
]


# ============================================================
# REDIS HELPERS
# ============================================================

def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(
            f'{UPSTASH_REDIS_URL}/get/{key}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
        d = r.json()
        if d.get('result'):
            return json.loads(d['result'])
    except Exception as e:
        print(f'[Belarus Rhetoric] Redis get error: {str(e)[:120]}')
    return None


def _redis_set(key, value):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(
            UPSTASH_REDIS_URL,
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json',
            },
            json=['SET', key, json.dumps(value, default=str)],
            timeout=10
        )
        return r.status_code == 200
    except Exception as e:
        print(f'[Belarus Rhetoric] Redis set error: {str(e)[:120]}')
        return False


def _redis_lpush_trim(key, value, max_len=120):
    """Push to list head; trim to max_len. Used for history."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        body = json.dumps(value, default=str)
        requests.post(
            f'{UPSTASH_REDIS_URL}/lpush/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json',
            },
            json={'value': body},
            timeout=10
        )
        requests.post(
            f'{UPSTASH_REDIS_URL}/ltrim/{key}/0/{max_len-1}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
        return True
    except Exception as e:
        print(f'[Belarus Rhetoric] Redis lpush error: {str(e)[:120]}')
        return False


# ============================================================
# FETCHERS
# ============================================================

def _parse_pub_date(pub_str):
    if not pub_str:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_str).isoformat()
    except Exception:
        return pub_str


def _fetch_rss(url, source_name, weight=0.85, max_items=20):
    out = []
    try:
        feed = feedparser.parse(url)
        for entry in (feed.entries or [])[:max_items]:
            out.append({
                'title':       entry.get('title', '')[:300],
                'description': (entry.get('summary') or entry.get('description') or '')[:600],
                'url':         entry.get('link', ''),
                'published':   _parse_pub_date(entry.get('published') or entry.get('updated')),
                'source':      source_name,
                'source_type': 'rss',
                'weight':      weight,
            })
    except Exception as e:
        print(f'[Belarus RSS] {source_name}: {str(e)[:120]}')
    return out


def _fetch_gdelt(query, language='eng', days=7, max_records=25):
    """Single GDELT query."""
    params = {
        'query':        query,
        'mode':         'artlist',
        'maxrecords':   max_records,
        'format':       'json',
        'sort':         'datedesc',
        'timespan':     f'{days*24}h',
        'sourcelang':   language,
    }
    try:
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 15))
        if resp.status_code == 429:
            print(f'[Belarus GDELT] Rate limited (429) — backing off')
            return []
        if resp.status_code != 200:
            return []
        articles = resp.json().get('articles', []) or []
        out = []
        for a in articles:
            out.append({
                'title':       (a.get('title') or '')[:300],
                'description': '',
                'url':         a.get('url', ''),
                'published':   a.get('seendate'),
                'source':      a.get('domain', 'gdelt'),
                'source_type': 'gdelt',
                'language':    language,
                'weight':      0.7,
            })
        return out
    except Exception as e:
        print(f'[Belarus GDELT] Query error: {str(e)[:120]}')
        return []


def _fetch_newsapi(query='belarus', max_records=40):
    if not NEWSAPI_KEY:
        return []
    params = {
        'q':          query,
        'pageSize':   max_records,
        'language':   'en',
        'sortBy':     'publishedAt',
        'apiKey':     NEWSAPI_KEY,
    }
    try:
        r = requests.get(NEWSAPI_BASE_URL, params=params, timeout=10)
        if r.status_code != 200:
            print(f'[Belarus NewsAPI] HTTP {r.status_code}')
            return []
        out = []
        for a in (r.json().get('articles') or []):
            out.append({
                'title':       (a.get('title') or '')[:300],
                'description': (a.get('description') or '')[:600],
                'url':         a.get('url', ''),
                'published':   a.get('publishedAt'),
                'source':      (a.get('source') or {}).get('name', 'newsapi'),
                'source_type': 'newsapi',
                'weight':      0.85,
            })
        return out
    except Exception as e:
        print(f'[Belarus NewsAPI] {str(e)[:120]}')
        return []


def _fetch_brave(query='belarus politics', max_records=20):
    """Tertiary fallback for low-volume scans."""
    if not BRAVE_API_KEY:
        return []
    headers = {
        'Accept':              'application/json',
        'X-Subscription-Token': BRAVE_API_KEY,
    }
    params = {'q': query, 'count': max_records, 'freshness': 'pw'}
    try:
        r = requests.get(BRAVE_BASE_URL, headers=headers, params=params, timeout=10)
        if r.status_code != 200:
            return []
        out = []
        for a in (r.json().get('results') or []):
            out.append({
                'title':       (a.get('title') or '')[:300],
                'description': (a.get('description') or '')[:600],
                'url':         a.get('url', ''),
                'published':   a.get('age'),
                'source':      (a.get('meta_url') or {}).get('hostname', 'brave'),
                'source_type': 'brave',
                'weight':      0.75,
            })
        return out
    except Exception as e:
        print(f'[Belarus Brave] {str(e)[:120]}')
        return []


def _fetch_reddit():
    """Belarus-relevant subreddits."""
    out = []
    subs = ['belarus', 'europe', 'CredibleDefense', 'LessCredibleDefence',
            'geopolitics', 'ukraine']
    for sub in subs:
        try:
            url = f'https://www.reddit.com/r/{sub}/new.json?limit=25'
            r = requests.get(
                url,
                headers={'User-Agent': 'Asifah-Analytics/1.0'},
                timeout=8
            )
            if r.status_code != 200:
                continue
            for child in (r.json().get('data', {}).get('children') or []):
                p = child.get('data', {})
                title = (p.get('title') or '').lower()
                # Filter: must mention Belarus topic
                if not any(kw in title for kw in BELARUS_TOPIC_KEYWORDS):
                    continue
                out.append({
                    'title':       p.get('title', '')[:300],
                    'description': (p.get('selftext') or '')[:400],
                    'url':         f"https://reddit.com{p.get('permalink', '')}",
                    'published':   datetime.fromtimestamp(
                        p.get('created_utc', 0), tz=timezone.utc
                    ).isoformat() if p.get('created_utc') else None,
                    'source':      f'reddit-{sub}',
                    'source_type': 'reddit',
                    'score':       p.get('score', 0),
                    'comments':    p.get('num_comments', 0),
                    'weight':      0.65,
                })
        except Exception as e:
            print(f'[Belarus Reddit] r/{sub}: {str(e)[:120]}')
        time.sleep(0.3)  # rate-limit politeness
    return out


def _fetch_all_articles():
    """Run all article fetchers, dedupe by URL, return single list."""
    articles = []

    # RSS
    for feed in RSS_FEEDS:
        articles.extend(_fetch_rss(feed['url'], feed['name'], feed['weight']))

    # GDELT
    for lang, queries in GDELT_QUERIES.items():
        for q in queries:
            articles.extend(_fetch_gdelt(q, language=lang, days=7))
            time.sleep(0.5)  # GDELT politeness

    # NewsAPI fallback (only if RSS+GDELT thin)
    if len(articles) < 30:
        articles.extend(_fetch_newsapi('belarus', max_records=40))

    # Brave tertiary fallback (only if still thin)
    if len(articles) < 15:
        articles.extend(_fetch_brave('belarus lukashenko', max_records=20))

    # Dedupe by URL
    seen = set()
    unique = []
    for a in articles:
        u = a.get('url')
        if u and u not in seen:
            seen.add(u)
            unique.append(a)

    return unique


# ============================================================
# ACTOR CLASSIFICATION
# ============================================================

def _score_article_for_actor(article, actor_def):
    """How strongly does this article relate to a given actor?"""
    text = ' '.join([
        (article.get('title') or '').lower(),
        (article.get('description') or '').lower(),
    ])
    if not text.strip():
        return 0
    matches = 0
    for kw in actor_def.get('keywords', []):
        if kw.lower() in text:
            matches += 1
    return matches


def _classify_articles(articles):
    """Assign each article to one or more actors. Returns dict actor→articles."""
    by_actor = {k: [] for k in ACTORS}
    for art in articles:
        best_actor, best_score = None, 0
        for actor_key, actor_def in ACTORS.items():
            s = _score_article_for_actor(art, actor_def)
            if s > best_score:
                best_score, best_actor = s, actor_key
        if best_actor and best_score >= 1:
            art_copy = dict(art)
            art_copy['actor_score'] = best_score
            by_actor[best_actor].append(art_copy)
    return by_actor


# ============================================================
# THEATRE SCORE
# ============================================================

def _compute_theatre_score(by_actor, articles):
    """
    Derive a 0-100 'pressure' score for the theatre.
    Belarus baseline +9 per project memory (high-pressure tuning).
    """
    BASELINE = 9
    actor_weights = {
        'lukashenko_regime':         0.85,
        'russian_forces_in_belarus': 1.10,
        'belarusian_opposition':     0.55,
        'nato_border_states':        0.95,
        'iran_belarus_axis':         1.05,
        'china_belarus_axis':        0.80,
        'ukraine_border_signals':    0.95,
    }
    score = BASELINE
    for actor_key, articles_list in by_actor.items():
        weight = actor_weights.get(actor_key, 0.7)
        # Each article above weight 0.5 adds proportionally; cap per-actor at 25
        actor_contribution = min(25, sum(a.get('weight', 0.7) for a in articles_list) * weight)
        score += actor_contribution
    return max(0, min(100, int(score)))


def _alert_level_from_score(score):
    if score >= 80:
        return 'critical'
    elif score >= 60:
        return 'high'
    elif score >= 40:
        return 'elevated'
    else:
        return 'normal'


# ============================================================
# CROSS-THEATER FINGERPRINT WRITE
# ============================================================

def _write_cross_theater_fingerprints(fingerprints):
    """Write fingerprint flags to Redis for downstream tracker reads."""
    for key, val in (fingerprints or {}).items():
        try:
            _redis_set(f'fingerprint:belarus:{key}', val)
        except Exception:
            pass


# ============================================================
# MAIN SCAN
# ============================================================

def run_belarus_rhetoric_scan(force=False):
    """
    Full scan orchestrator. Aggregates all sources, classifies by actor,
    runs interpreter, writes Redis cache + history.
    Returns the scan result dict.
    """
    if not force:
        cached = _redis_get(REDIS_KEY_LATEST)
        if cached and cached.get('cached_at'):
            try:
                cached_at = datetime.fromisoformat(cached['cached_at'])
                age = (datetime.now(timezone.utc) - cached_at).total_seconds()
                if age < REFRESH_INTERVAL_SEC:
                    cached['cache_status'] = 'hit'
                    return cached
            except Exception:
                pass

    print('[Belarus Rhetoric] Starting fresh scan...')
    started = time.time()

    # Articles
    articles = _fetch_all_articles()
    print(f'[Belarus Rhetoric] Articles: {len(articles)}')

    # Telegram
    telegram_messages = []
    if TELEGRAM_AVAILABLE:
        try:
            telegram_messages = fetch_belarus_telegram_signals() or []
            print(f'[Belarus Rhetoric] Telegram: {len(telegram_messages)} messages')
        except Exception as e:
            print(f'[Belarus Rhetoric] Telegram fetch error: {str(e)[:120]}')

    # Bluesky
    bluesky_signals = []
    if BLUESKY_AVAILABLE:
        try:
            bluesky_signals = fetch_belarus_bluesky_signals() or []
            print(f'[Belarus Rhetoric] Bluesky: {len(bluesky_signals)} posts')
        except Exception as e:
            print(f'[Belarus Rhetoric] Bluesky fetch error: {str(e)[:120]}')

    # Reddit
    reddit_signals = _fetch_reddit()
    print(f'[Belarus Rhetoric] Reddit: {len(reddit_signals)} posts')

    # Classify articles by actor
    by_actor = _classify_articles(articles)
    actor_summaries = {}
    for actor_key, actor_articles in by_actor.items():
        actor_def = ACTORS[actor_key]
        actor_summaries[actor_key] = {
            'name':           actor_def['name'],
            'flag':           actor_def['flag'],
            'icon':           actor_def['icon'],
            'color':          actor_def['color'],
            'role':           actor_def['role'],
            'description':    actor_def['description'],
            'article_count':  len(actor_articles),
            'top_articles':   actor_articles[:5],
        }

    # Theatre score
    score = _compute_theatre_score(by_actor, articles)
    alert = _alert_level_from_score(score)

    # Articles by language for interpreter
    articles_en = [a for a in articles if a.get('language', 'eng') in ('eng', None)]
    articles_ru = [a for a in articles if a.get('language') == 'rus']

    # Build scan_data for interpreter
    scan_data = {
        'articles_en':        articles_en,
        'articles_ru':        articles_ru,
        'telegram_messages':  telegram_messages,
        'bluesky_signals':    bluesky_signals,
        'reddit_signals':     reddit_signals,
        'by_actor':           by_actor,
        'actor_summaries':    actor_summaries,
        'theatre_score':      score,
        'alert_level':        alert,
    }

    # Run analytical layer
    interpretation = interpret_signals(scan_data)

    # Write cross-theater fingerprints to Redis
    _write_cross_theater_fingerprints(
        interpretation.get('cross_theater_fingerprints') or {}
    )

    # Compose final result
    elapsed = round(time.time() - started, 1)
    result = {
        'theatre':           'belarus',
        'flag':              '🇧🇾',
        'display_name':      'Belarus',
        'theatre_score':     score,
        'alert_level':       alert,
        'pressure_score':    score,
        'tracker_version':   '1.0.0',
        'cached_at':         datetime.now(timezone.utc).isoformat(),
        'scan_duration_sec': elapsed,
        'cache_status':      'fresh',
        # Article metadata
        'total_articles':    len(articles),
        'articles_by_source': {
            'rss':     sum(1 for a in articles if a.get('source_type') == 'rss'),
            'gdelt':   sum(1 for a in articles if a.get('source_type') == 'gdelt'),
            'newsapi': sum(1 for a in articles if a.get('source_type') == 'newsapi'),
            'brave':   sum(1 for a in articles if a.get('source_type') == 'brave'),
        },
        'telegram_count':  len(telegram_messages),
        'bluesky_count':   len(bluesky_signals),
        'reddit_count':    len(reddit_signals),
        'articles_en':     articles_en,
        'articles_ru':     articles_ru,
        # Actor breakdown
        'actor_summaries': actor_summaries,
        # Interpretation (canonical schema)
        'so_what':         interpretation.get('so_what'),
        'top_signals':     interpretation.get('top_signals') or [],
        'red_lines':       interpretation.get('red_lines'),
        'green_lines':     interpretation.get('green_lines'),
        'diplomatic_track': interpretation.get('diplomatic_track'),
        'commodity_signal': interpretation.get('commodity_signal'),
        'cross_theater_fingerprints': interpretation.get('cross_theater_fingerprints'),
        'composite_modifier': interpretation.get('composite_modifier', 0),
        'interpreter_version': interpretation.get('interpreter_version'),
    }

    # Persist
    _redis_set(REDIS_KEY_LATEST, result)
    _redis_lpush_trim(REDIS_KEY_HISTORY, {
        'cached_at':     result['cached_at'],
        'theatre_score': result['theatre_score'],
        'alert_level':   result['alert_level'],
        'top_signals':   result['top_signals'][:5],
    })

    print(f'[Belarus Rhetoric] Scan complete: score={score}, alert={alert}, '
          f'articles={len(articles)}, elapsed={elapsed}s')
    return result


# ============================================================
# BACKGROUND REFRESH
# ============================================================

def _background_refresh():
    """Daemon: scan every 6 hours."""
    time.sleep(120)  # boot stabilization
    while True:
        try:
            with _scan_lock:
                run_belarus_rhetoric_scan(force=True)
        except Exception as e:
            print(f'[Belarus Rhetoric] Background error: {str(e)[:120]}')
        time.sleep(REFRESH_INTERVAL_SEC)


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print('[Belarus Rhetoric] Background refresh thread started (6h cycle)')


# ============================================================
# ENDPOINT REGISTRATION
# ============================================================

def register_belarus_rhetoric_endpoints(app):
    """Register Flask endpoints. Call from Europe app.py."""

    @app.route('/api/rhetoric/belarus', methods=['GET'])
    def api_rhetoric_belarus():
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            data = run_belarus_rhetoric_scan(force=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   str(e)[:200],
                'theatre': 'belarus',
            }), 500

    @app.route('/api/rhetoric/belarus/summary', methods=['GET'])
    def api_rhetoric_belarus_summary():
        """Compact form for hub pages."""
        try:
            d = run_belarus_rhetoric_scan(force=False)
            return jsonify({
                'theatre':         'belarus',
                'flag':            '🇧🇾',
                'display_name':    'Belarus',
                'theatre_score':   d.get('theatre_score', 0),
                'alert_level':     d.get('alert_level', 'normal'),
                'top_signals':     (d.get('top_signals') or [])[:3],
                'so_what_scenario': (d.get('so_what') or {}).get('scenario'),
                'cached_at':       d.get('cached_at'),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/rhetoric/belarus/history', methods=['GET'])
    def api_rhetoric_belarus_history():
        """Recent scan snapshots from Redis list."""
        if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
            return jsonify({'success': False, 'error': 'Redis not configured', 'history': []})
        try:
            limit = min(int(request.args.get('limit', 30)), 120)
            r = requests.get(
                f'{UPSTASH_REDIS_URL}/lrange/{REDIS_KEY_HISTORY}/0/{limit-1}',
                headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                timeout=8
            )
            raw = (r.json().get('result') or []) if r.status_code == 200 else []
            history = []
            for item in raw:
                try:
                    history.append(json.loads(item))
                except Exception:
                    pass
            return jsonify({
                'success': True,
                'theatre': 'belarus',
                'count':   len(history),
                'history': history,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200], 'history': []}), 500

    print('[Belarus Rhetoric] Endpoints registered: /api/rhetoric/belarus, /summary, /history')
