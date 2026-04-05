"""
Asifah Analytics — Greenland Sovereignty Rhetoric Tracker
v1.0.0 — April 2026

ANALYTICAL FRAME — Inverted threat model:
The United States is the primary pressure actor. Greenland, Denmark,
and NATO allies are the sovereignty defense actors. Russia is an
opportunistic third-party exploiting the friction.

This tracker answers three analytical questions:

  Q1: How aggressively is the U.S. pushing on Greenland?
      → US_PRESSURE vector
      Trump/White House acquisition language, Pentagon Arctic posture,
      Congressional statements, economic coercion signals,
      USAID/diplomatic leverage language

  Q2: How is Greenland + Denmark + NATO pushing back?
      → SOVEREIGNTY_DEFENSE vector
      Múte Egede / IA party defiance language, Danish defense deployments,
      NATO Article 5 invocation signals, Nordic solidarity statements,
      Greenlandic self-determination rhetoric, Danish military activity

  Q3: Is Russia exploiting the friction?
      → RUSSIA_ARCTIC vector
      Northern Fleet posturing, Arctic sovereignty declarations,
      wedge diplomacy (offering Greenland alternatives to US),
      Arctic Council disruption language, Russian media framing

ACTORS:
  us_pressure       — Trump admin, Pentagon, Congress on Greenland acquisition
  greenland_inuit   — Múte Egede, Inuit Ataqatigiit, Greenlandic government (Naalakkersuisut)
  denmark_nato      — Copenhagen government, Danish military, NATO collective defense
  russia_arctic     — Kremlin Arctic opportunism, Northern Fleet, wedge signaling
  china_observer    — Beijing Arctic interest (secondary — monitoring only)

ESCALATION MODEL (inverted from standard trackers):
  Level 0 — Baseline:      Normal diplomatic noise, no acquisition pressure
  Level 1 — Rhetoric:      U.S. public statements of interest, no operational signals
  Level 2 — Pressure:      Active U.S. coercion attempts, economic leverage, military signaling
  Level 3 — Crisis:        Danish/Greenlandic formal protests, NATO consultations triggered
  Level 4 — Confrontation: U.S. unilateral actions, Danish military deployment, NATO Article 5 language
  Level 5 — Rupture:       Military incident, forced annexation attempt, alliance fracture

REDIS KEYS:
  Cache:    rhetoric:greenland:latest
  History:  rhetoric:greenland:history
  Baseline: rhetoric_baseline:greenland

ENDPOINTS:
  GET /api/rhetoric/greenland
  GET /api/rhetoric/greenland/summary
  GET /api/rhetoric/greenland/history

CHANGELOG:
  v1.0.0 (2026-04-04): Initial build — inverted threat model, 4-actor system

COPYRIGHT © 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import threading
import time
import requests
import xml.etree.ElementTree as ET
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from flask import jsonify, request

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

try:
    from telegram_signals_europe import fetch_greenland_telegram_signals
    TELEGRAM_AVAILABLE = True
    print("[Greenland Rhetoric] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Greenland Rhetoric] ⚠️ Telegram signals not available — RSS/GDELT only")

RHETORIC_CACHE_KEY  = 'rhetoric:greenland:latest'
HISTORY_KEY         = 'rhetoric:greenland:history'
BASELINE_KEY        = 'rhetoric_baseline:greenland'

RHETORIC_CACHE_TTL  = 6 * 3600   # 6 hours
SCAN_INTERVAL_HOURS = 6
HISTORY_MAX_ENTRIES = 120

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ESCALATION LEVELS
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Baseline',       'color': '#6b7280', 'description': 'Normal diplomatic noise — no acquisition pressure'},
    1: {'label': 'Rhetoric',       'color': '#3b82f6', 'description': 'U.S. public statements of interest — no operational signals'},
    2: {'label': 'Pressure',       'color': '#f59e0b', 'description': 'Active U.S. coercion, economic leverage, military signaling'},
    3: {'label': 'Crisis',         'color': '#f97316', 'description': 'Formal protests, NATO consultations triggered, diplomatic rupture'},
    4: {'label': 'Confrontation',  'color': '#ef4444', 'description': 'U.S. unilateral actions, Danish military deployment, Article 5 language'},
    5: {'label': 'Rupture',        'color': '#dc2626', 'description': 'Military incident, annexation attempt, alliance fracture'},
}


# ============================================
# ACTORS
# ============================================
ACTORS = {

    'us_pressure': {
        'name': 'U.S. Pressure (Trump Admin)',
        'flag': '🇺🇸', 'icon': '🦅',
        'color': '#1d4ed8',
        'role': 'Primary Pressure Actor',
        'description': 'Trump/White House acquisition language, Pentagon Arctic posture, economic coercion',
        'keywords': [
            # Acquisition / takeover language
            'trump greenland', 'greenland acquisition', 'buy greenland',
            'take greenland', 'us take greenland', 'greenland purchase',
            'greenland deal', 'greenland us control', 'annex greenland',
            'greenland belong to us', 'make greenland american',
            'trump wants greenland', 'trump greenland military',
            'us greenland takeover', 'greenland territory us',
            # Economic coercion
            'greenland tariff', 'denmark tariff greenland',
            'us sanctions denmark', 'economic pressure greenland',
            'greenland aid cut', 'us leverage greenland',
            'greenland mineral rights us', 'us greenland mining',
            # Military signaling
            'us military greenland', 'us troops greenland',
            'us base greenland', 'pentagon greenland',
            'us arctic strategy greenland', 'us icebreaker greenland',
            'us arctic military buildup', 'us arctic command greenland',
            'pituffik us expansion', 'thule expansion',
            # Diplomatic pressure
            'us ambassador denmark greenland', 'state department greenland',
            'marco rubio greenland', 'us secretary state greenland',
            'us greenland ultimatum', 'greenland referendum us pressure',
            # Congressional
            'congress greenland', 'senate greenland', 'greenland bill us',
            'greenland legislation', 'us greenland act',
        ],
        'baseline_statements_per_week': 12,
        'weight': 1.4,   # Primary signal — overweighted
    },

    'greenland_inuit': {
        'name': 'Greenland / Inuit Voice',
        'flag': '🇬🇱', 'icon': '🧊',
        'color': '#0ea5e9',
        'role': 'Sovereignty Defense — Local',
        'description': 'Múte Egede, Inuit Ataqatigiit, Naalakkersuisut — Greenlandic self-determination',
        'keywords': [
            # Leadership statements
            'mute egede', 'múte egede', 'egede greenland',
            'naalakkersuisut', 'greenland government statement',
            'inuit ataqatigiit', 'greenlandic government rejects',
            'greenland prime minister', 'greenland premier',
            # Self-determination language
            'greenland self-determination', 'greenland independence',
            'greenland sovereignty', 'greenland not for sale',
            'greenland decides own future', 'greenland autonomy',
            'greenland referendum', 'greenlandic people decide',
            'greenland self-rule', 'greenland home rule',
            'kalaallit nunaat sovereignty', 'inuit rights arctic',
            # Defiance / resistance language
            'greenland rejects us', 'greenland refuses',
            'greenland will not', 'greenland opposes',
            'greenland independence vote', 'greenland protest us',
            'greenlandic people oppose', 'greenland reaction trump',
            # Greenlandic language signals (key Kalaallisut terms in reporting)
            'kalaallit nunaat', 'namminersorlutik',
            'inatsisartut', 'sulisa',
            # Local politics
            'siumut greenland', 'demokraatit greenland',
            'naleraq greenland', 'atassut greenland',
            'greenland election', 'greenland coalition',
        ],
        'baseline_statements_per_week': 6,
        'weight': 1.2,
    },

    'denmark_nato': {
        'name': 'Denmark / NATO Alliance',
        'flag': '🇩🇰', 'icon': '🛡️',
        'color': '#16a34a',
        'role': 'Sovereignty Defense — Alliance',
        'description': 'Copenhagen government, Danish military, NATO Article 5, Nordic solidarity',
        'keywords': [
            # Danish government statements
            'denmark rejects', 'denmark greenland sovereignty',
            'denmark not for sale', 'denmark greenland not sale',
            'danish prime minister greenland', 'danish pm greenland',
            'danish pm pledges greenland', 'danish pm supports greenland',
            'mette frederiksen greenland', 'danish pm mette',
            'lars lokke greenland', 'copenhagen greenland',
            'danish foreign minister greenland', 'danish government greenland',
            'denmark us greenland', 'denmark protests us',
            'denmark greenland response', 'denmark greenland firm',
            'denmark supports greenland', 'denmark backs greenland',
            'denmark pledges greenland', 'danish support greenland',
            'denmark trump greenland', 'denmark pressure greenland',
            # Danish military deployment (sovereignty signaling)
            'danish frigate greenland', 'danish navy arctic',
            'arktisk kommando', 'arctic command denmark',
            'danish armed forces greenland', 'denmark military greenland',
            'danish patrol greenland', 'danish defence greenland',
            'sirius patrol', 'danish p-8 greenland',
            'denmark military buildup arctic', 'danish warship greenland',
            # NATO collective response
            'nato greenland', 'nato article 5 greenland',
            'nato denmark greenland', 'nato arctic sovereignty',
            'nato ally greenland', 'nato response greenland',
            'nato greenland acquisition', 'nato consultation greenland',
            'collective defense greenland', 'article 5 invoked',
            # Nordic solidarity
            'nordic greenland', 'norway denmark greenland',
            'nordic solidarity greenland', 'scandinavia greenland',
            'nordic council greenland', 'norway supports denmark',
            'iceland denmark greenland', 'finland greenland',
            'sweden denmark greenland', 'nordic nato greenland',
            # European response
            'eu greenland', 'europe greenland sovereignty',
            'european commission greenland', 'eu response trump greenland',
            # Danish language signals
            'grønland suverænitet', 'grønland ikke til salg',
            'dansk suverænitet grønland', 'forsvaret grønland',
            'grønland forsvar', 'dansk militær arktis',
        ],
        'baseline_statements_per_week': 10,
        'weight': 1.1,
    },

    'russia_arctic': {
        'name': 'Russia (Arctic Opportunism)',
        'flag': '🇷🇺', 'icon': '🐻',
        'color': '#dc2626',
        'role': 'Third-Party Exploiter',
        'description': 'Kremlin wedge signaling, Northern Fleet posturing, Arctic Council disruption',
        'keywords': [
            # Kremlin framing / wedge diplomacy
            'russia greenland', 'russia arctic greenland',
            'kremlin greenland', 'putin greenland',
            'russia nato greenland', 'russia us greenland',
            'russia greenland sovereignty', 'russia greenland us threat',
            'russia warns greenland', 'russia arctic sovereignty',
            'russia greenland offer', 'russia greenland alternative',
            # Northern Fleet / military posture
            'northern fleet arctic', 'russia northern fleet',
            'russia submarine arctic', 'russian submarine greenland',
            'russia arctic military', 'russia arctic exercise',
            'russia arctic patrol', 'russia arctic base',
            'russia icebreaker arctic', 'russian icebreaker',
            'russia arctic buildup', 'severomorsk deployment',
            'borei submarine patrol', 'russia ssbn arctic',
            'russia arctic command', 'murmansk military',
            # Arctic Council disruption
            'arctic council russia', 'russia arctic council',
            'arctic council disruption', 'arctic governance russia',
            # Russian media framing (English-language TASS signals)
            'russia today greenland', 'tass greenland',
            'russia today arctic', 'tass arctic greenland',
            'russia greenland nato threat', 'russia greenland hypocrisy',
            'russia nato expansion arctic',
            # Russian language keywords (GDELT)
            'гренландия', 'арктика россия', 'северный флот',
            'арктический суверенитет', 'нато арктика',
        ],
        'baseline_statements_per_week': 5,
        'weight': 0.8,   # Third-party — lower weight than primary actors
    },

    'china_observer': {
        'name': 'China (Arctic Observer)',
        'flag': '🇨🇳', 'icon': '👁️',
        'color': '#7c3aed',
        'role': 'Secondary Observer — Low Weight',
        'description': 'Beijing Arctic interest, near-Arctic state claims, Greenland mining investment signals',
        'keywords': [
            'china greenland', 'china arctic greenland',
            'beijing greenland', 'china greenland mining',
            'china greenland minerals', 'china greenland investment',
            'china near arctic state', 'china arctic strategy',
            'china arctic silk road', 'polar silk road greenland',
            'china us greenland competition', 'china arctic interest',
            'beijing arctic sovereignty', 'china arctic council',
            '中国 格陵兰', '北极 中国',
        ],
        'baseline_statements_per_week': 3,
        'weight': 0.6,
    },
}


# ============================================
# RSS FEEDS
# ============================================
RSS_FEEDS = [
    # Arctic-focused
    'https://www.arctictoday.com/feed/',
    'https://www.highnorthnews.com/en/rss.xml',
    # Danish news (English)
    'https://www.thelocal.dk/feed/',
    'https://denmark.dk/news-and-media/rss-feeds',
    # Nordic/European defense
    'https://news.google.com/rss/search?q=greenland+sovereignty+OR+denmark+greenland+OR+trump+greenland&hl=en&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=greenland+acquisition+OR+greenland+independence+OR+greenland+nato&hl=en&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=greenland+military+OR+arctic+sovereignty+OR+pituffik+OR+thule&hl=en&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=mute+egede+OR+naalakkersuisut+OR+inuit+ataqatigiit+greenland&hl=en&gl=US&ceid=US:en',
    'https://news.google.com/rss/search?q=russia+arctic+greenland+OR+russia+northern+fleet+arctic&hl=en&gl=US&ceid=US:en',
    # Danish-language (GDELT will also cover this)
    'https://news.google.com/rss/search?q=grønland+suverænitet+OR+arktisk+kommando+OR+dansk+forsvar+grønland&hl=da&gl=DK&ceid=DK:da',
]

# ============================================
# NITTER FEEDS — Primary source Twitter/X accounts
# Mirror fallback: if mirror 1 fails, try mirror 2, etc.
# No API key required — public RSS.
# ============================================
NITTER_MIRRORS = [
    "nitter.poast.org",
    "nitter.privacydev.net",
    "nitter.woodland.cafe",
]

# Account list: (username, weight, description)
# Weight > 1.0 = primary source (direct government statement)
NITTER_ACCOUNTS = [
    # US pressure actors
    ('realDonaldTrump',   1.2, 'Trump direct statements on Greenland'),
    ('SecRubio',          1.1, 'US Secretary of State — Greenland/Arctic'),
    ('POTUS',             1.0, 'White House official account'),
    # Danish government
    ('Statsmin',          1.2, 'Danish Prime Minister'),
    ('DanishMFA',         1.1, 'Danish Ministry of Foreign Affairs'),
    ('DanishDefence',     1.1, 'Danish Defence Command'),
    # Greenlandic government
    ('NaalakMut',         1.2, 'Naalakkersuisut — Greenland government'),
    # NATO / multilateral
    ('NATO',              1.0, 'NATO official — Arctic posture signals'),
    ('SecGen_NATO',       1.0, 'NATO Secretary General'),
    # Arctic / Nordic monitoring
    ('ArcticCouncil',     0.9, 'Arctic Council — multilateral signals'),
    ('NordicCouncil',     0.9, 'Nordic Council'),
]


def _fetch_nitter(username, weight=1.0, timeout=8):
    """
    Fetch RSS for a Twitter/X account via Nitter mirror fallback.
    Tries each mirror in order until one succeeds.
    Returns list of articles with source tagged as 'Nitter @{username}'.
    """
    articles = []
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; AsifahAnalytics/1.0)'}

    for mirror in NITTER_MIRRORS:
        url = f'https://{mirror}/{username}/rss'
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item')[:20]:
                title_el   = item.find('title')
                link_el    = item.find('link')
                pubdate_el = item.find('pubDate')
                desc_el    = item.find('description')
                if title_el is None:
                    continue
                title = title_el.text or ''
                link  = link_el.text if link_el is not None else ''
                pub   = ''
                if pubdate_el is not None and pubdate_el.text:
                    try:
                        pub = parsedate_to_datetime(pubdate_el.text).isoformat()
                    except Exception:
                        pub = pubdate_el.text or ''
                desc = ''
                if desc_el is not None and desc_el.text:
                    # Strip HTML tags from Nitter descriptions
                    import re
                    desc = re.sub(r'<[^>]+>', '', desc_el.text)[:300]
                articles.append({
                    'title':     title,
                    'url':       link,
                    'published': pub,
                    'source':    f'Nitter @{username}',
                    'body':      f'{title} {desc}'.lower(),
                    'nitter_weight': weight,
                })
            if articles:
                print(f'[Greenland Rhetoric/Nitter] @{username}: {len(articles)} posts via {mirror}')
                return articles  # Success — don't try other mirrors
        except Exception as e:
            print(f'[Greenland Rhetoric/Nitter] @{username} mirror {mirror} failed: {str(e)[:60]}')
            continue

    if not articles:
        print(f'[Greenland Rhetoric/Nitter] @{username}: all mirrors failed')
    return articles


def _fetch_all_nitter(days=5):
    """Fetch from all Nitter accounts and filter by recency."""
    import re
    all_posts = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for username, weight, desc in NITTER_ACCOUNTS:
        posts = _fetch_nitter(username, weight=weight)
        for p in posts:
            # Filter to recency window
            if p.get('published'):
                try:
                    pub_dt = datetime.fromisoformat(p['published'].replace('Z', '+00:00'))
                    if pub_dt < cutoff:
                        continue
                except Exception:
                    pass
            all_posts.append(p)
        time.sleep(0.4)

    print(f'[Greenland Rhetoric/Nitter] Total posts: {len(all_posts)}')
    return all_posts


GDELT_QUERIES = [
    # English — U.S. pressure
    ('greenland acquisition trump purchase', 'eng'),
    ('greenland sovereignty united states military', 'eng'),
    ('greenland denmark nato arctic', 'eng'),
    ('mute egede greenland independence', 'eng'),
    # English — Russia Arctic
    ('russia arctic sovereignty greenland northern fleet', 'eng'),
    # Danish
    ('grønland suverænitet dansk forsvar', 'dan'),
    ('arktisk kommando grønland militær', 'dan'),
    # Greenlandic/Nordic covered by GDELT Danish
]


# ============================================
# REDIS HELPERS
# ============================================
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
        print(f'[Greenland Rhetoric] Redis GET error ({key}): {e}')
        return None


def _redis_set(key, value, ttl=None):
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
        print(f'[Greenland Rhetoric] Redis SET error ({key}): {e}')
        return False


def _redis_lpush(key, value, max_len=HISTORY_MAX_ENTRIES):
    """Push to Redis list with trim."""
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return
    try:
        payload = json.dumps(value, default=str)
        requests.post(
            f'{UPSTASH_REDIS_URL}/lpush/{key}',
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json'
            },
            data=json.dumps([payload]),
            timeout=5
        )
        requests.post(
            f'{UPSTASH_REDIS_URL}/ltrim/{key}/0/{max_len - 1}',
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5
        )
    except Exception as e:
        print(f'[Greenland Rhetoric] Redis LPUSH error: {e}')


# ============================================
# ARTICLE FETCHING
# ============================================
def _fetch_rss(url, timeout=10):
    """Fetch and parse a single RSS feed."""
    articles = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; AsifahAnalytics/1.0)'}
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return articles
        root = ET.fromstring(resp.content)
        for item in root.findall('.//item')[:15]:
            title_el   = item.find('title')
            link_el    = item.find('link')
            pubdate_el = item.find('pubDate')
            desc_el    = item.find('description')
            if title_el is None:
                continue
            title = title_el.text or ''
            link  = link_el.text  if link_el  is not None else ''
            pub   = ''
            if pubdate_el is not None and pubdate_el.text:
                try:
                    pub = parsedate_to_datetime(pubdate_el.text).isoformat()
                except Exception:
                    pub = pubdate_el.text or ''
            desc = desc_el.text[:300] if desc_el is not None and desc_el.text else ''
            articles.append({
                'title':     title,
                'url':       link,
                'published': pub,
                'source':    url,
                'body':      f'{title} {desc}'.lower(),
            })
    except Exception as e:
        print(f'[Greenland Rhetoric] RSS error ({url[:60]}): {str(e)[:80]}')
    return articles


def _fetch_gdelt(query, lang='eng', days=5, timeout=15):
    """Fetch articles from GDELT v2 doc API."""
    articles = []
    try:
        params = {
            'query':      query,
            'mode':       'artlist',
            'maxrecords': 50,
            'timespan':   f'{days}d',
            'sourcelang': lang,
            'format':     'json',
        }
        url = 'https://api.gdeltproject.org/api/v2/doc/doc'
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code != 200:
            return articles
        data = resp.json()
        for art in data.get('articles', []):
            articles.append({
                'title':     art.get('title', ''),
                'url':       art.get('url', ''),
                'published': art.get('seendate', ''),
                'source':    art.get('domain', ''),
                'body':      f"{art.get('title', '')} {art.get('url', '')}".lower(),
            })
    except Exception as e:
        print(f'[Greenland Rhetoric] GDELT error ({query[:40]}): {str(e)[:80]}')
    return articles


def _fetch_all_articles(days=5):
    """Fetch from all RSS feeds and GDELT queries."""
    all_articles = []
    seen_urls = set()

    print(f'[Greenland Rhetoric] Fetching RSS feeds ({len(RSS_FEEDS)} feeds)...')
    for feed_url in RSS_FEEDS:
        arts = _fetch_rss(feed_url)
        for a in arts:
            if a['url'] not in seen_urls:
                seen_urls.add(a['url'])
                all_articles.append(a)
        time.sleep(0.3)

    print(f'[Greenland Rhetoric] Fetching GDELT ({len(GDELT_QUERIES)} queries)...')
    for query, lang in GDELT_QUERIES:
        arts = _fetch_gdelt(query, lang=lang, days=days)
        for a in arts:
            if a['url'] not in seen_urls:
                seen_urls.add(a['url'])
                all_articles.append(a)
        time.sleep(0.5)

    # Nitter — primary source Twitter/X accounts
    print(f'[Greenland Rhetoric] Fetching Nitter ({len(NITTER_ACCOUNTS)} accounts)...')
    nitter_posts = _fetch_all_nitter(days=days)
    for p in nitter_posts:
        if p['url'] not in seen_urls:
            seen_urls.add(p['url'])
            all_articles.append(p)

    print(f'[Greenland Rhetoric] Total articles after dedup: {len(all_articles)}')
    return all_articles


# ============================================
# SCORING ENGINE
# ============================================
def _score_actor(actor_id, actor_cfg, articles, telegram_msgs):
    """Score a single actor across all articles and Telegram messages."""
    keywords  = [kw.lower() for kw in actor_cfg['keywords']]
    hits      = []
    hit_count = 0

    for art in articles:
        body = art.get('body', '').lower()
        matched = [kw for kw in keywords if kw in body]
        if matched:
            hit_count += len(matched)
            hits.append({
                'title':    art.get('title', '')[:150],
                'url':      art.get('url', ''),
                'source':   art.get('source', ''),
                'published': art.get('published', ''),
                'matched_keywords': matched[:5],
            })

    # Add Telegram signals
    tg_hits = 0
    for msg in telegram_msgs:
        body = msg.get('title', '').lower()
        matched = [kw for kw in keywords if kw in body]
        if matched:
            tg_hits += len(matched)
            hit_count += len(matched)

    # Baseline normalization
    baseline = actor_cfg.get('baseline_statements_per_week', 8)
    weight   = actor_cfg.get('weight', 1.0)
    raw_score = min(100, int((hit_count / max(baseline, 1)) * 25 * weight))

    # Map to 0–5 escalation level
    if raw_score >= 85:   level = 5
    elif raw_score >= 65: level = 4
    elif raw_score >= 45: level = 3
    elif raw_score >= 28: level = 2
    elif raw_score >= 12: level = 1
    else:                 level = 0

    level_info = ESCALATION_LEVELS[level]
    return {
        'actor':          actor_id,
        'name':           actor_cfg['name'],
        'flag':           actor_cfg['flag'],
        'icon':           actor_cfg['icon'],
        'color':          actor_cfg['color'],
        'role':           actor_cfg['role'],
        'raw_score':      raw_score,
        'level':          level,
        'label':          level_info['label'],
        'escalation_color': level_info['color'],
        'description':    level_info['description'],
        'article_hits':   len(hits),
        'keyword_hits':   hit_count,
        'telegram_hits':  tg_hits,
        'top_articles':   hits[:5],
    }


def _compute_composite(actor_scores):
    """
    Compute composite theatre score.
    U.S. pressure is the primary driver; sovereignty defense is secondary context.
    Russia Arctic is an independent amplifier.
    """
    us       = actor_scores.get('us_pressure',     {})
    gl       = actor_scores.get('greenland_inuit',  {})
    dk       = actor_scores.get('denmark_nato',     {})
    ru       = actor_scores.get('russia_arctic',    {})
    cn       = actor_scores.get('china_observer',   {})

    us_raw = us.get('raw_score', 0)
    gl_raw = gl.get('raw_score', 0)
    dk_raw = dk.get('raw_score', 0)
    ru_raw = ru.get('raw_score', 0)

    # Composite: US pressure (50%) + sovereignty defense avg (30%) + Russia (15%) + China (5%)
    composite = (
        us_raw * 0.50 +
        ((gl_raw + dk_raw) / 2) * 0.30 +
        ru_raw * 0.15 +
        cn.get('raw_score', 0) * 0.05
    )
    composite = min(100, int(composite))

    # Overall level from composite
    if composite >= 85:   theatre_level = 5
    elif composite >= 65: theatre_level = 4
    elif composite >= 45: theatre_level = 3
    elif composite >= 28: theatre_level = 2
    elif composite >= 12: theatre_level = 1
    else:                 theatre_level = 0

    level_info = ESCALATION_LEVELS[theatre_level]

    # Sovereignty defense intensity (how hard Greenland+Denmark are pushing back)
    defense_intensity = min(5, int(((gl_raw + dk_raw) / 2) / 20))

    # Russia opportunism flag
    russia_opportunism = ru.get('level', 0) >= 2

    # Key signal flags
    us_level         = us.get('level', 0)
    greenland_level  = gl.get('level', 0)
    denmark_level    = dk.get('level', 0)
    russia_level     = ru.get('level', 0)

    # Convergence: US high + Denmark/Greenland high = maximum tension
    convergence_signal = ''
    if us_level >= 3 and (greenland_level >= 2 or denmark_level >= 2):
        convergence_signal = '⚠️ High U.S. pressure meeting active sovereignty defense'
    elif us_level >= 4:
        convergence_signal = '🚨 U.S. acquisition pressure at crisis level'
    elif greenland_level >= 3 and denmark_level >= 3:
        convergence_signal = '🛡️ Strong coordinated sovereignty defense response'
    elif russia_level >= 3:
        convergence_signal = '🐻 Russia actively exploiting Greenland friction'
    elif us_level >= 2:
        convergence_signal = '📡 Elevated U.S. pressure on Greenland sovereignty'

    return {
        'theatre_score':            composite,
        'theatre_level':            theatre_level,
        'theatre_escalation_level': theatre_level,
        'theatre_escalation_label': level_info['label'],
        'theatre_escalation_color': level_info['color'],
        'theatre_label':            level_info['label'],
        'theatre_color':            level_info['color'],
        'defence_intensity':        defense_intensity,
        'russia_opportunism':       russia_opportunism,
        'convergence_signal':       convergence_signal,
        'us_pressure_level':        us_level,
        'greenland_level':          greenland_level,
        'denmark_level':            denmark_level,
        'russia_level':             russia_level,
    }


# ============================================
# MAIN SCAN
# ============================================
def run_greenland_rhetoric_scan(days=5):
    """Full scan: fetch articles, score all actors, return structured result."""
    print(f'[Greenland Rhetoric] Starting scan (days={days})...')
    start_time = time.time()

    # Fetch articles
    articles = _fetch_all_articles(days=days)

    # Fetch Telegram
    telegram_msgs = []
    if TELEGRAM_AVAILABLE:
        try:
            telegram_msgs = fetch_greenland_telegram_signals(hours_back=days * 24) or []
            print(f'[Greenland Rhetoric] Telegram: {len(telegram_msgs)} messages')
        except Exception as e:
            print(f'[Greenland Rhetoric] Telegram error: {e}')

    # Score each actor
    actor_scores = {}
    for actor_id, actor_cfg in ACTORS.items():
        actor_scores[actor_id] = _score_actor(actor_id, actor_cfg, articles, telegram_msgs)
        print(f'[Greenland Rhetoric] {actor_cfg["name"]}: L{actor_scores[actor_id]["level"]} ({actor_scores[actor_id]["raw_score"]}/100)')

    # Composite theatre score
    composite = _compute_composite(actor_scores)

    elapsed = round(time.time() - start_time, 1)
    now = datetime.now(timezone.utc).isoformat()

    # Top articles across all actors (deduplicated, sorted by hit count)
    all_top = []
    seen = set()
    for scores in actor_scores.values():
        for art in scores.get('top_articles', []):
            if art['url'] not in seen:
                seen.add(art['url'])
                all_top.append(art)
    all_top = all_top[:20]

    result = {
        'success':              True,
        'theatre':              'Greenland',
        'version':              '1.0.0',
        'timestamp':            now,
        'scanned_at':           now,
        'scan_duration_seconds': elapsed,
        'total_articles':       len(articles),
        'telegram_messages':    len(telegram_msgs),
        # Composite
        **composite,
        # Per-actor
        'actors':               actor_scores,
        # Top articles
        'top_articles':         all_top,
        # Legacy fields for summary endpoint
        'theatre_score':        composite['theatre_score'],
        'is_strike_actor':      False,   # Inverted model — no strike actor
        'is_sovereignty_crisis': composite['theatre_level'] >= 3,
    }

    print(f'[Greenland Rhetoric] Scan complete in {elapsed}s | Theatre L{composite["theatre_level"]} ({composite["theatre_score"]}/100) | {composite["convergence_signal"] or "No convergence signal"}')
    return result


# ============================================
# BACKGROUND SCAN
# ============================================
def _bg_scan():
    """Run scan and write to Redis cache + history."""
    global _rhetoric_running
    try:
        result = run_greenland_rhetoric_scan()
        _redis_set(RHETORIC_CACHE_KEY, result, ttl=RHETORIC_CACHE_TTL)
        # Append to history
        history_entry = {
            'timestamp':            result['timestamp'],
            'theatre_score':        result['theatre_score'],
            'theatre_level':        result['theatre_level'],
            'theatre_label':        result['theatre_label'],
            'us_pressure_level':    result['us_pressure_level'],
            'greenland_level':      result['greenland_level'],
            'denmark_level':        result['denmark_level'],
            'russia_level':         result['russia_level'],
            'convergence_signal':   result['convergence_signal'],
        }
        _redis_lpush(HISTORY_KEY, history_entry)
        print(f'[Greenland Rhetoric] ✅ Cache + history written')
    except Exception as e:
        print(f'[Greenland Rhetoric] ❌ Background scan error: {e}')
    finally:
        with _rhetoric_lock:
            _rhetoric_running = False


# ============================================
# FLASK ROUTE REGISTRATION
# ============================================
def register_greenland_rhetoric_routes(app):

    def _periodic():
        time.sleep(180)   # 3-minute stagger after boot
        print('[Greenland Rhetoric] Starting initial scan...')
        _bg_scan()
        while True:
            print(f'[Greenland Rhetoric] Sleeping {SCAN_INTERVAL_HOURS}h...')
            time.sleep(SCAN_INTERVAL_HOURS * 3600)
            _bg_scan()

    threading.Thread(target=_periodic, daemon=True).start()
    print(f'[Greenland Rhetoric] ✅ Periodic scan thread started ({SCAN_INTERVAL_HOURS}h cycle)')

    @app.route('/api/rhetoric/greenland', methods=['GET'])
    def greenland_rhetoric():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')
        days  = int(request.args.get('days', 5))

        if force:
            try:
                return jsonify(run_greenland_rhetoric_scan(days=days))
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)[:200]}), 500

        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            cached['cached'] = True
            return jsonify(cached)

        global _rhetoric_running
        with _rhetoric_lock:
            if not _rhetoric_running:
                _rhetoric_running = True
                threading.Thread(target=_bg_scan, daemon=True).start()

        return jsonify({
            'success':                  True,
            'awaiting_scan':            True,
            'theatre':                  'Greenland',
            'theatre_score':            0,
            'theatre_escalation_level': 0,
            'theatre_escalation_label': 'Scanning...',
            'theatre_escalation_color': '#6b7280',
            'message':                  'First scan in progress — fetching Arctic/Nordic sources...',
            'version':                  '1.0.0',
        })

    @app.route('/api/rhetoric/greenland/summary', methods=['GET'])
    def greenland_rhetoric_summary():
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            actors = cached.get('actors', {})
            return jsonify({
                'success':                  True,
                'theatre':                  'Greenland',
                # Composite
                'theatre_score':            cached.get('theatre_score', 0),
                'theatre_level':            cached.get('theatre_level', 0),
                'theatre_escalation_level': cached.get('theatre_escalation_level', 0),
                'theatre_escalation_label': cached.get('theatre_escalation_label', 'Baseline'),
                'theatre_escalation_color': cached.get('theatre_escalation_color', '#6b7280'),
                'theatre_label':            cached.get('theatre_label', 'Baseline'),
                'theatre_color':            cached.get('theatre_color', '#6b7280'),
                # Key signals
                'us_pressure_level':        cached.get('us_pressure_level', 0),
                'greenland_level':          cached.get('greenland_level', 0),
                'denmark_level':            cached.get('denmark_level', 0),
                'russia_level':             cached.get('russia_level', 0),
                'convergence_signal':       cached.get('convergence_signal', ''),
                'defence_intensity':        cached.get('defence_intensity', 0),
                'russia_opportunism':       cached.get('russia_opportunism', False),
                'is_sovereignty_crisis':    cached.get('is_sovereignty_crisis', False),
                # Per-actor quick view
                'actor_levels': {
                    aid: {
                        'level': adat.get('level', 0),
                        'label': adat.get('label', 'Baseline'),
                        'color': adat.get('escalation_color', '#6b7280'),
                        'score': adat.get('raw_score', 0),
                    }
                    for aid, adat in actors.items()
                },
                'total_articles':   cached.get('total_articles', 0),
                'scanned_at':       cached.get('scanned_at', ''),
                'cached':           True,
            })
        return jsonify({
            'success':       False,
            'awaiting_scan': True,
            'theatre':       'Greenland',
            'message':       'No cached data — scan in progress',
        })

    @app.route('/api/rhetoric/greenland/history', methods=['GET'])
    def greenland_rhetoric_history():
        try:
            limit = max(1, min(int(request.args.get('limit', 120)), 120))
            entries = []
            if UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN:
                resp = requests.get(
                    f'{UPSTASH_REDIS_URL}/lrange/{HISTORY_KEY}/0/{limit - 1}',
                    headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                    timeout=5
                )
                for item in resp.json().get('result', []):
                    try:
                        entries.append(json.loads(item))
                    except Exception:
                        pass
            entries.reverse()
            return jsonify({
                'success': True,
                'theatre': 'Greenland',
                'count':   len(entries),
                'entries': entries,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    print('[Greenland Rhetoric] ✅ Routes registered: '
          '/api/rhetoric/greenland, /api/rhetoric/greenland/summary, '
          '/api/rhetoric/greenland/history')
