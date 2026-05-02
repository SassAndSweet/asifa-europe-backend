"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — UKRAINE RHETORIC TRACKER
  v1.0.0 (Apr 30 2026)
═══════════════════════════════════════════════════════════════════════

Multi-actor rhetoric tracker for Ukraine. Aggregates signals across:
  - RSS (Kyiv Independent, Ukrainska Pravda EN, Ukrinform, ISW, Kiel)
  - GDELT multi-language queries (English + Ukrainian + Russian)
  - NewsAPI fallback
  - Brave Search tertiary fallback
  - Telegram channels (Ukraine-specific subset of Europe channels)
  - Bluesky (Zelensky, Ukraine MFA, OSINT defenders, Wartranslated)
  - Reddit (/r/ukraine, /r/credibledefense, /r/europe, /r/ukrainewarvideoreport)

Calls ukraine_signal_interpreter.interpret_signals() for analytical layer.

Writes Redis cache key 'rhetoric:ukraine:latest'.

ACTOR FRAMEWORK (7 actors):
  - ukrainian_government
  - ukrainian_armed_forces
  - russian_forces_in_ukraine
  - us_government                  (own actor — aid pipeline decisive)
  - nato_western_support           (Europe + UK + non-US Western)
  - defense_industrial_base        (drone advisor exports SUB-VECTOR)
  - occupied_territories_signals

ENDPOINTS:
  GET /api/rhetoric/ukraine
  GET /api/rhetoric/ukraine/summary
  GET /api/rhetoric/ukraine/history
"""

import os
import json
import time
import threading
import requests
import feedparser
from datetime import datetime, timezone
from flask import jsonify, request

try:
    from telegram_signals_europe import fetch_ukraine_telegram_signals
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print('[Ukraine Rhetoric] Telegram signals not available')

try:
    from bluesky_signals_europe import fetch_ukraine_bluesky_signals
    BLUESKY_AVAILABLE = True
except ImportError:
    BLUESKY_AVAILABLE = False
    print('[Ukraine Rhetoric] Bluesky signals not available')

from ukraine_signal_interpreter import interpret_signals

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

REDIS_KEY_LATEST     = 'rhetoric:ukraine:latest'
REDIS_KEY_HISTORY    = 'rhetoric:ukraine:history'
REFRESH_INTERVAL_SEC = 6 * 3600

_scan_lock = threading.Lock()


# ============================================================
# RSS FEEDS
# ============================================================
RSS_FEEDS = [
    # Ukrainian press
    {'name': 'Kyiv Independent',         'url': 'https://kyivindependent.com/feed/',           'weight': 0.95},
    {'name': 'Ukrainska Pravda (EN)',    'url': 'https://www.pravda.com.ua/eng/rss/view_news/', 'weight': 0.90},
    {'name': 'Ukrinform',                'url': 'https://www.ukrinform.net/rss/block-lastnews', 'weight': 0.90},
    # Defense / OSINT
    {'name': 'ISW',                      'url': 'https://www.understandingwar.org/rss.xml',     'weight': 0.95},
    {'name': 'War on the Rocks',         'url': 'https://warontherocks.com/feed/',              'weight': 0.85},
    {'name': 'USNI News',                'url': 'https://news.usni.org/feed',                   'weight': 0.85},
    # Investigative / Russia-focused
    {'name': 'Meduza (English)',         'url': 'https://meduza.io/rss/en/all',                 'weight': 0.90},
    {'name': 'Bellingcat',               'url': 'https://www.bellingcat.com/feed/',             'weight': 0.95},
    # International
    {'name': 'Reuters World',            'url': 'https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best',  'weight': 0.90},
    {'name': 'Politico Europe',          'url': 'https://www.politico.eu/feed/',                'weight': 0.85},
]


# ============================================================
# ACTORS (7 actors per analytical plan)
# ============================================================
ACTORS = {
    'ukrainian_government': {
        'name': 'Ukrainian Government',
        'flag': '🇺🇦',
        'icon': '🏛️',
        'color': '#0ea5e9',
        'role': 'Office of the President, MFA, Cabinet, Verkhovna Rada',
        'description': (
            'Zelensky office, Yermak (chief of staff), Kuleba/MFA, Cabinet '
            'of Ministers, Verkhovna Rada (parliament). Watch for: '
            'diplomatic posture, ceasefire signals, mobilization legislation, '
            'sanctions advocacy, reconstruction frameworks.'
        ),
        'keywords': [
            'zelensky', 'volodymyr zelensky', 'office of the president ukraine',
            'yermak', 'andriy yermak', 'ukrainian mfa', 'kuleba',
            'sybiha', 'andrii sybiha', 'ukrainian government',
            'cabinet of ministers ukraine', 'verkhovna rada',
            'shmyhal', 'denys shmyhal',
            'kyiv government', 'ukrainian presidency',
            'офис президента', 'верховная рада',
        ],
    },
    'ukrainian_armed_forces': {
        'name': 'Ukrainian Armed Forces',
        'flag': '🪖',
        'icon': '⚔️',
        'color': '#0891b2',
        'role': 'AFU General Staff, theatre commands, GUR, SBU operations',
        'description': (
            'Armed Forces of Ukraine General Staff, Syrskyi (Cmdr-in-Chief), '
            'theatre commands, GUR (military intelligence) operations, SBU '
            'sabotage. Watch for: counter-offensive language, salient defense, '
            'GUR strikes deep in Russia, ATACMS / Storm Shadow employment.'
        ),
        'keywords': [
            'syrskyi', 'oleksandr syrskyi', 'afu general staff',
            'ukrainian armed forces', 'ukrainian military',
            'ukrainian army', 'ukrainian forces',
            'gur', 'ukrainian military intelligence', 'budanov',
            'kyrylo budanov', 'sbu', 'ukrainian special forces',
            'ukrainian counter-offensive', 'ukrainian operation',
            'atacms strike', 'storm shadow ukraine',
            'всу', 'генштаб украины', 'буданов',
        ],
    },
    'russian_forces_in_ukraine': {
        'name': 'Russian Forces in Ukraine',
        'flag': '🇷🇺',
        'icon': '💥',
        'color': '#dc2626',
        'role': 'Russian theatre forces, MoD operations, Shahed/missile campaigns',
        'description': (
            'Russian forces operating in / against Ukraine. Watch for: '
            'Shahed swarms, cruise missile salvos, frontline advances, '
            'glide bomb employment, infrastructure strike campaigns, '
            'Tornado-S deployment.'
        ),
        'keywords': [
            'russian forces ukraine', 'russian troops ukraine',
            'russian advance', 'russian offensive ukraine',
            'shahed', 'shahed swarm', 'iranian-made drones',
            'kalibr strike', 'kalibr missile', 'kinzhal strike',
            'tornado-s', 'glide bomb', 'fab-1500',
            'russian missile strike ukraine', 'russian shelling',
            'российские войска украина', 'шахед',
        ],
    },
    'us_government': {
        'name': 'United States Government',
        'flag': '🇺🇸',
        'icon': '🏛️',
        'color': '#1e40af',
        'role': 'Trump admin, State Dept, DoD, Congress — aid pipeline',
        'description': (
            'US government posture toward Ukraine — Trump administration '
            'position, State Department signals, DoD weapons authorizations, '
            'Congressional aid debate. The decisive variable for Ukrainian '
            'war sustainability.'
        ),
        'keywords': [
            'trump ukraine', 'trump zelensky', 'witkoff',
            'us aid ukraine', 'us military aid ukraine',
            'congressional aid ukraine', 'state department ukraine',
            'pentagon ukraine', 'us weapons ukraine',
            'patriot ukraine', 'atacms ukraine authorization',
            'us ukraine policy', 'biden ukraine', 'rubio ukraine',
            'us secretary of state ukraine', 'us defense secretary ukraine',
            'трамп украина', 'сша украина помощь',
        ],
    },
    'nato_western_support': {
        'name': 'NATO / Western Support',
        'flag': '🇪🇺',
        'icon': '🛡️',
        'color': '#3b82f6',
        'role': 'EU, UK, Germany, France, Poland, Nordics — non-US Western',
        'description': (
            'Western support outside the US — EU peace facility, UK weapons '
            'aid, German Leopard/Patriot deliveries, French SCALP, Polish '
            'logistics hub, Nordic ammunition surge. Backfill capacity for '
            'US gaps + independent commitment trajectory.'
        ),
        'keywords': [
            'nato ukraine', 'eu ukraine aid', 'european aid ukraine',
            'germany ukraine aid', 'leopard ukraine', 'patriot delivery germany',
            'uk ukraine', 'storm shadow uk', 'british aid ukraine',
            'france ukraine', 'scalp delivery', 'macron ukraine',
            'poland ukraine', 'polish aid ukraine',
            'finland ukraine', 'sweden ukraine', 'norway ukraine',
            'eu peace facility', 'eu summit ukraine',
            'rheinmetall expansion', 'european defense fund',
        ],
    },
    'defense_industrial_base': {
        'name': 'Defense Industrial Base',
        'flag': '🏭',
        'icon': '🚁',
        'color': '#a16207',
        'role': 'Ukrainian DIB + drone advisor exports to GCC (sub-vector)',
        'description': (
            'Ukrainian defense industrial base — domestic drone production '
            '(Bayraktar localization, Magura, Bober, Punisher), missile '
            'programs, Western weapons integration, AND drone advisor exports '
            'to GCC (UAE, Saudi Arabia, Israel during Iran war). Unique '
            'leverage vector — defense knowledge as strategic export.'
        ),
        'keywords': [
            # Ukrainian DIB
            'ukrainian defense industry', 'ukroboronprom',
            'magura', 'magura naval drone', 'bober drone', 'punisher drone',
            'ukrainian drone production', 'ukrainian missile program',
            'neptune missile', 'long neptune',
            'shahed knockoff ukraine', 'rampage ukraine',
            # Drone advisor exports (the unique vector)
            'ukrainian drone advisors', 'ukrainian drone instructors',
            'ukraine drone training abroad', 'ukrainian advisors uae',
            'ukrainian advisors saudi', 'kyiv drone diplomacy',
            'ukraine drone export', 'ukrainian drone partnership gcc',
            'ukraine israel drone', 'ukraine drone gcc',
            # Western integration
            'f-16 ukraine', 'mirage 2000 ukraine', 'leopard ukraine',
            'himars ukraine',
        ],
    },
    'occupied_territories_signals': {
        'name': 'Occupied Territories Signals',
        'flag': '🏚️',
        'icon': '⚖️',
        'color': '#7c2d12',
        'role': 'Mariupol/Crimea/Donbas: atrocity, deportation, partisan',
        'description': (
            'Russian-occupied territories — atrocity disclosures, mass '
            'deportation events, filtration camp expansion, Russification '
            'campaigns, partisan activity, ICC indictments. Drives Western '
            'political pressure dynamics.'
        ),
        'keywords': [
            'mariupol', 'azovstal', 'occupied territories ukraine',
            'occupied donbas', 'occupied crimea', 'occupied kherson',
            'filtration camp', 'forced deportation ukrainian',
            'children deported ukraine', 'forced russification',
            'ukrainian partisan', 'crimea partisan',
            'icc warrant putin', 'icc warrant lvova-belova',
            'mass grave ukraine', 'atrocity ukraine',
            'оккупированная территория украины', 'фильтрационный лагерь',
        ],
    },
}


# ============================================================
# GDELT QUERIES
# ============================================================
GDELT_QUERIES = {
    'eng': [
        '"ukraine" AND ("zelensky" OR "kyiv")',
        '"ukraine" AND ("frontline" OR "offensive" OR "advance")',
        '"ukraine" AND ("nato" OR "eu" OR "western aid")',
        '"ukraine" AND ("trump" OR "us aid" OR "congressional")',
        '"ukraine" AND ("drone" OR "shahed" OR "magura")',
        '"ukraine" AND ("ceasefire" OR "negotiation" OR "diplomatic")',
        '"ukrainian advisors" OR "ukrainian drone training"',
    ],
    'ukr': [
        '"україна" AND ("зеленський" OR "київ")',
        '"україна" AND ("фронт" OR "наступ")',
    ],
    'rus': [
        '"украина" AND ("зеленский" OR "киев")',
        '"украина" AND ("сво" OR "наступление")',
    ],
}


# ============================================================
# TOPIC FILTER
# ============================================================
UKRAINE_TOPIC_KEYWORDS = [
    'ukraine', 'ukrainian', 'kyiv', 'kiev', 'zelensky', 'zelenskyy',
    'kharkiv', 'odesa', 'odessa', 'donbas', 'mariupol', 'crimea',
    'kherson', 'sumy', 'zaporizhzhia',
    'україна', 'украина', 'киев', 'київ',
]


# ============================================================
# REDIS HELPERS (canonical pattern, same as Belarus)
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
        print(f'[Ukraine Rhetoric] Redis get error: {str(e)[:120]}')
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
        print(f'[Ukraine Rhetoric] Redis set error: {str(e)[:120]}')
        return False


def _redis_lpush_trim(key, value, max_len=120):
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
        print(f'[Ukraine Rhetoric] Redis lpush error: {str(e)[:120]}')
        return False


# ============================================================
# FETCHERS (canonical pattern)
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
        print(f'[Ukraine RSS] {source_name}: {str(e)[:120]}')
    return out


def _fetch_gdelt(query, language='eng', days=7, max_records=25):
    params = {
        'query':      query,
        'mode':       'artlist',
        'maxrecords': max_records,
        'format':     'json',
        'sort':       'datedesc',
        'timespan':   f'{days*24}h',
        'sourcelang': language,
    }
    try:
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 15))
        if resp.status_code == 429:
            print('[Ukraine GDELT] Rate limited (429) — backing off')
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
        print(f'[Ukraine GDELT] Query error: {str(e)[:120]}')
        return []


def _fetch_newsapi(query='ukraine', max_records=40):
    if not NEWSAPI_KEY:
        return []
    params = {
        'q':        query,
        'pageSize': max_records,
        'language': 'en',
        'sortBy':   'publishedAt',
        'apiKey':   NEWSAPI_KEY,
    }
    try:
        r = requests.get(NEWSAPI_BASE_URL, params=params, timeout=10)
        if r.status_code != 200:
            print(f'[Ukraine NewsAPI] HTTP {r.status_code}')
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
        print(f'[Ukraine NewsAPI] {str(e)[:120]}')
        return []


def _fetch_brave(query='ukraine war', max_records=20):
    if not BRAVE_API_KEY:
        return []
    headers = {
        'Accept': 'application/json',
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
        print(f'[Ukraine Brave] {str(e)[:120]}')
        return []


def _fetch_reddit():
    out = []
    subs = ['ukraine', 'CredibleDefense', 'LessCredibleDefence',
            'UkrainianConflict', 'ukrainewarvideoreport',
            'europe', 'geopolitics']
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
                if not any(kw in title for kw in UKRAINE_TOPIC_KEYWORDS):
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
            print(f'[Ukraine Reddit] r/{sub}: {str(e)[:120]}')
        time.sleep(0.3)
    return out


def _fetch_all_articles():
    articles = []
    for feed in RSS_FEEDS:
        articles.extend(_fetch_rss(feed['url'], feed['name'], feed['weight']))
    for lang, queries in GDELT_QUERIES.items():
        for q in queries:
            articles.extend(_fetch_gdelt(q, language=lang, days=7))
            time.sleep(0.5)
    if len(articles) < 30:
        articles.extend(_fetch_newsapi('ukraine', max_records=40))
    if len(articles) < 15:
        articles.extend(_fetch_brave('ukraine war', max_records=20))
    seen, unique = set(), []
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
    """Ukraine baseline +12 (active war, higher than Belarus)."""
    BASELINE = 12
    actor_weights = {
        'ukrainian_government':       0.85,
        'ukrainian_armed_forces':     0.95,
        'russian_forces_in_ukraine':  1.10,
        'us_government':              1.10,
        'nato_western_support':       0.85,
        'defense_industrial_base':    0.85,
        'occupied_territories_signals': 0.75,
    }
    score = BASELINE
    for actor_key, articles_list in by_actor.items():
        weight = actor_weights.get(actor_key, 0.7)
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


def _write_cross_theater_fingerprints(fingerprints):
    for key, val in (fingerprints or {}).items():
        try:
            _redis_set(f'fingerprint:ukraine:{key}', val)
        except Exception:
            pass


# ============================================================
# MAIN SCAN
# ============================================================

def run_ukraine_rhetoric_scan(force=False):
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

    print('[Ukraine Rhetoric] Starting fresh scan...')
    started = time.time()

    articles = _fetch_all_articles()
    print(f'[Ukraine Rhetoric] Articles: {len(articles)}')

    telegram_messages = []
    if TELEGRAM_AVAILABLE:
        try:
            telegram_messages = fetch_ukraine_telegram_signals() or []
            print(f'[Ukraine Rhetoric] Telegram: {len(telegram_messages)} messages')
        except Exception as e:
            print(f'[Ukraine Rhetoric] Telegram fetch error: {str(e)[:120]}')

    bluesky_signals = []
    if BLUESKY_AVAILABLE:
        try:
            bluesky_signals = fetch_ukraine_bluesky_signals() or []
            print(f'[Ukraine Rhetoric] Bluesky: {len(bluesky_signals)} posts')
        except Exception as e:
            print(f'[Ukraine Rhetoric] Bluesky fetch error: {str(e)[:120]}')

    reddit_signals = _fetch_reddit()
    print(f'[Ukraine Rhetoric] Reddit: {len(reddit_signals)} posts')

    by_actor = _classify_articles(articles)
    actor_summaries = {}
    for actor_key, actor_articles in by_actor.items():
        actor_def = ACTORS[actor_key]
        actor_summaries[actor_key] = {
            'name':          actor_def['name'],
            'flag':          actor_def['flag'],
            'icon':          actor_def['icon'],
            'color':         actor_def['color'],
            'role':          actor_def['role'],
            'description':   actor_def['description'],
            'article_count': len(actor_articles),
            'top_articles':  actor_articles[:5],
        }

    score = _compute_theatre_score(by_actor, articles)
    alert = _alert_level_from_score(score)

    articles_en = [a for a in articles if a.get('language', 'eng') in ('eng', None)]
    articles_uk = [a for a in articles if a.get('language') == 'ukr']
    articles_ru = [a for a in articles if a.get('language') == 'rus']

    scan_data = {
        'articles_en':       articles_en,
        'articles_uk':       articles_uk,
        'articles_ru':       articles_ru,
        'telegram_messages': telegram_messages,
        'bluesky_signals':   bluesky_signals,
        'reddit_signals':    reddit_signals,
        'by_actor':          by_actor,
        'actor_summaries':   actor_summaries,
        'theatre_score':     score,
        'alert_level':       alert,
    }

    interpretation = interpret_signals(scan_data)
    _write_cross_theater_fingerprints(
        interpretation.get('cross_theater_fingerprints') or {}
    )

    elapsed = round(time.time() - started, 1)
    result = {
        'theatre':           'ukraine',
        'flag':              '🇺🇦',
        'display_name':      'Ukraine',
        'theatre_score':     score,
        'alert_level':       alert,
        'pressure_score':    score,
        'tracker_version':   '1.0.0',
        'cached_at':         datetime.now(timezone.utc).isoformat(),
        'scan_duration_sec': elapsed,
        'cache_status':      'fresh',
        'total_articles':    len(articles),
        'articles_by_source': {
            'rss':     sum(1 for a in articles if a.get('source_type') == 'rss'),
            'gdelt':   sum(1 for a in articles if a.get('source_type') == 'gdelt'),
            'newsapi': sum(1 for a in articles if a.get('source_type') == 'newsapi'),
            'brave':   sum(1 for a in articles if a.get('source_type') == 'brave'),
        },
        'telegram_count':    len(telegram_messages),
        'bluesky_count':     len(bluesky_signals),
        'reddit_count':      len(reddit_signals),
        'articles_en':       articles_en,
        'articles_uk':       articles_uk,
        'articles_ru':       articles_ru,
        'actor_summaries':   actor_summaries,
        'so_what':           interpretation.get('so_what'),
        'top_signals':       interpretation.get('top_signals') or [],
        'red_lines':         interpretation.get('red_lines'),
        'green_lines':       interpretation.get('green_lines'),
        'diplomatic_track':  interpretation.get('diplomatic_track'),
        'commodity_signal':  interpretation.get('commodity_signal'),
        'cross_theater_fingerprints': interpretation.get('cross_theater_fingerprints'),
        'composite_modifier': interpretation.get('composite_modifier', 0),
        'interpreter_version': interpretation.get('interpreter_version'),
    }

    _redis_set(REDIS_KEY_LATEST, result)
    _redis_lpush_trim(REDIS_KEY_HISTORY, {
        'cached_at':     result['cached_at'],
        'theatre_score': result['theatre_score'],
        'alert_level':   result['alert_level'],
        'top_signals':   result['top_signals'][:5],
    })

    print(f'[Ukraine Rhetoric] Scan complete: score={score}, alert={alert}, '
          f'articles={len(articles)}, elapsed={elapsed}s')
    return result


# ============================================================
# BACKGROUND REFRESH
# ============================================================

def _background_refresh():
    time.sleep(120)
    while True:
        try:
            with _scan_lock:
                run_ukraine_rhetoric_scan(force=True)
        except Exception as e:
            print(f'[Ukraine Rhetoric] Background error: {str(e)[:120]}')
        time.sleep(REFRESH_INTERVAL_SEC)


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print('[Ukraine Rhetoric] Background refresh thread started (6h cycle)')


# ============================================================
# ENDPOINT REGISTRATION
# ============================================================

def register_ukraine_rhetoric_endpoints(app):
    @app.route('/api/rhetoric/ukraine', methods=['GET'])
    def api_rhetoric_ukraine():
        try:
            force = request.args.get('force', 'false').lower() == 'true'
            data = run_ukraine_rhetoric_scan(force=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({
                'success': False,
                'error':   str(e)[:200],
                'theatre': 'ukraine',
            }), 500

    @app.route('/api/rhetoric/ukraine/summary', methods=['GET'])
    def api_rhetoric_ukraine_summary():
        try:
            d = run_ukraine_rhetoric_scan(force=False)
            return jsonify({
                'theatre':         'ukraine',
                'flag':            '🇺🇦',
                'display_name':    'Ukraine',
                'theatre_score':   d.get('theatre_score', 0),
                'alert_level':     d.get('alert_level', 'normal'),
                'top_signals':     (d.get('top_signals') or [])[:3],
                'so_what_scenario': (d.get('so_what') or {}).get('scenario'),
                'cached_at':       d.get('cached_at'),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/rhetoric/ukraine/history', methods=['GET'])
    def api_rhetoric_ukraine_history():
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
                'theatre': 'ukraine',
                'count':   len(history),
                'history': history,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200], 'history': []}), 500

    print('[Ukraine Rhetoric] Endpoints registered: /api/rhetoric/ukraine, /summary, /history')
