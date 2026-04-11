"""
Asifah Analytics — Russia Stability Index Backend
Europe Backend Module
v1.0.0 — April 2026

ANALYTICAL FRAME:
Russia's stability is measured on an INVERTED scale from its peer autocracies —
because Russia is simultaneously a nuclear power, a sanctions-pressured economy,
an active belligerent, and an information-suppressed state. Standard stability
metrics break down. This tracker answers:

  1. Is the war economy sustainable? (sanctions bite, ruble health, oil revenue)
  2. Is internal cohesion holding? (protests, brain drain, ethnic minority pressure)
  3. Is leadership unified? (silovik consensus, Kremlin signals, succession signals)
  4. Is the military pressure escalating or de-escalating? (reads from rhetoric fingerprint)
  5. Is global alignment strengthening or weakening Russia's position?

STABILITY SCORE: 0-100 (higher = MORE stable)
  Labels:
    80-100  Consolidated    — authoritarian control maintained, war ongoing but managed
    60-79   Managed Tension — economic/social pressure building, no systemic risk
    40-59   Elevated Stress — multiple vectors under pressure, cracks visible
    20-39   Systemic Pressure — structural instability, leadership cohesion at risk
    0-19    Crisis Risk     — mobilization, succession, or collapse signals present

VECTORS (5):
  sanctions_economy   25%  — ruble, Brent/Urals, MOEX, inflation signals
  military_posture    25%  — reads Russia rhetoric tracker fingerprint from Redis
  internal_cohesion   20%  — protests, arrests, brain drain, minority casualty signals
  leadership          15%  — Kremlin unity, silovik signals, succession risk
  global_alignment    15%  — China-Russia axis, BRICS, sanctions evasion signals

LIVE DATA SOURCES:
  Ruble/USD:    open.er-api.com (free, no key)
  Brent Crude:  Yahoo Finance BZ=F (free, no key)
  MOEX Index:   Alpha Vantage (ALPHA_VANTAGE_KEY) — Moscow Exchange benchmark
  Urals proxy:  Calculated from Brent minus historical discount range
  Articles:     NewsAPI + GDELT

REDIS KEYS:
  Cache:    stability:russia:latest
  History:  stability:russia:history
  Reads:    rhetoric:crosstheater:fingerprints (written by Russia rhetoric tracker)

ENDPOINTS:
  GET /api/stability/russia
  GET /api/stability/russia/summary
  GET /api/stability/russia/history

CHANGELOG:
  v1.0.0 (2026-04-11): Initial build

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import threading
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
ALPHA_VANTAGE_KEY   = os.environ.get('ALPHA_VANTAGE_KEY')

CACHE_KEY           = 'stability:russia:latest'
HISTORY_KEY         = 'stability:russia:history'
CROSSTHEATER_KEY    = 'rhetoric:crosstheater:fingerprints'

SCAN_INTERVAL_HOURS = 12

_stability_running  = False
_stability_lock     = threading.Lock()


# ============================================
# STABILITY LABELS
# ============================================
def _stability_label(score):
    if score >= 80: return ('Consolidated',       '#22c55e')
    if score >= 60: return ('Managed Tension',    '#f59e0b')
    if score >= 40: return ('Elevated Stress',    '#f97316')
    if score >= 20: return ('Systemic Pressure',  '#ef4444')
    return               ('Crisis Risk',          '#dc2626')


# ============================================
# STATIC REFERENCE DATA
# ============================================
RUSSIA_LEADERSHIP = [
    {
        'name':      'Vladimir Putin',
        'role':      'President',
        'flag':      '🇷🇺',
        'since':     '2000',
        'note':      'Longest-serving Russian/Soviet leader since Stalin. ICC arrest warrant March 2023.',
        'risk_note': 'ICC warrant — unlawful deportation of Ukrainian children',
        'data_as_of': '2026-04-11',
    },
    {
        'name':      'Mikhail Mishustin',
        'role':      'Prime Minister',
        'flag':      '🇷🇺',
        'since':     '2020',
        'note':      'Technocrat managing wartime economy. Budget reoriented to defense.',
        'risk_note': None,
        'data_as_of': '2026-04-11',
    },
    {
        'name':      'Sergei Lavrov',
        'role':      'Foreign Minister',
        'flag':      '🇷🇺',
        'since':     '2004',
        'note':      'Primary diplomatic face internationally. Statements reflect Kremlin policy directly.',
        'risk_note': None,
        'data_as_of': '2026-04-11',
    },
    {
        'name':      'Valery Gerasimov',
        'role':      'Chief of General Staff',
        'flag':      '🇷🇺',
        'since':     '2023',
        'note':      'Ukraine war commander. Survived Prigozhin mutiny.',
        'risk_note': 'Position historically volatile — Ukraine setbacks reshuffle military leadership',
        'data_as_of': '2026-04-11',
    },
    {
        'name':      'Nikolai Patrushev',
        'role':      'Presidential Aide / Security',
        'flag':      '🇷🇺',
        'since':     '2023',
        'note':      'Hardline silovik ideologue. Putin\'s closest ideological ally.',
        'risk_note': None,
        'data_as_of': '2026-04-11',
    },
    {
        'name':      'Dmitry Medvedev',
        'role':      'Dep. Security Council Chair',
        'flag':      '🇷🇺',
        'since':     '2020',
        'note':      'Primary Kremlin nuclear rhetoric instrument. Statements are deliberate Kremlin signaling.',
        'risk_note': '📡 Asifah tracks Medvedev rhetoric as nuclear coercion proxy',
        'data_as_of': '2026-04-11',
    },
]

STATIC_ECONOMIC = {
    'defense_spending_gdp_pct': {'value': '6–8%', 'note': 'Highest since Cold War', 'source': 'SIPRI', 'source_url': 'https://www.sipri.org/', 'data_as_of': '2025'},
    'frozen_reserves_usd':      {'value': '~$300B', 'note': 'Frozen in Western jurisdictions', 'source': 'EU/G7/US Treasury', 'source_url': 'https://www.treasury.gov/resource-center/sanctions', 'data_as_of': '2024'},
    'g7_oil_price_cap':         {'value': '$60/bbl', 'note': 'Russia consistently selling above via shadow fleet', 'source': 'G7/IEA', 'source_url': 'https://www.iea.org/', 'data_as_of': '2024'},
    'cbr_key_rate':             {'value': '21%', 'note': 'Emergency rate to defend ruble', 'source': 'Central Bank of Russia', 'source_url': 'https://www.cbr.ru/', 'data_as_of': '2024-10'},
    'swift_status':             {'value': 'EXCLUDED', 'note': 'Major banks disconnected Feb 2022', 'source': 'EU Council', 'source_url': 'https://www.consilium.europa.eu/', 'data_as_of': '2022-02'},
    'brain_drain_estimate':     {'value': '500K–1M', 'note': 'Emigrated since Feb 2022, disproportionately tech-skilled', 'source': 'Novaya Gazeta / academic est.', 'source_url': 'https://novayagazeta.ru/', 'data_as_of': '2024'},
    'china_trade_bilateral':    {'value': '$240B+/yr', 'note': 'Russia\'s primary trading partner, replacing Western goods', 'source': 'SIPRI / Chinese Customs', 'source_url': 'https://www.sipri.org/', 'data_as_of': '2024'},
}

STATIC_WAR_STATUS = {
    'territory_held_pct':       {'value': '~18%', 'note': 'of Ukraine incl. Crimea', 'source': 'ISW', 'source_url': 'https://www.understandingwar.org/', 'data_as_of': '2026-04'},
    'estimated_casualties':     {'value': '300,000+', 'note': 'KIA + WIA since Feb 2022', 'source': 'UK MoD / USG estimates', 'source_url': 'https://www.gov.uk/government/organisations/ministry-of-defence', 'data_as_of': '2026-04'},
    'icc_warrant_status':       {'value': 'ACTIVE', 'note': 'Putin + Lvova-Belova, March 2023', 'source': 'ICC', 'source_url': 'https://www.icc-cpi.int/', 'data_as_of': '2023-03'},
    'active_front_km':          {'value': '~1,000 km', 'note': 'Contact line Zaporizhzhia to Kharkiv', 'source': 'ISW', 'source_url': 'https://www.understandingwar.org/', 'data_as_of': '2026-04'},
    'partial_mobilization_called': {'value': '~300,000', 'note': 'Sept 2022 partial mobilization', 'source': 'Russian govt / RUSI', 'source_url': 'https://www.rusi.org/', 'data_as_of': '2022-09'},
}


# ============================================
# REDIS HELPERS
# ============================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5
        )
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
    except Exception as e:
        print(f"[Russia Stability] Redis GET error: {str(e)[:80]}")
    return None


def _redis_set(key, value):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        requests.post(
            UPSTASH_REDIS_URL,
            headers={
                "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                "Content-Type": "application/json"
            },
            json=["SET", key, json.dumps(value, default=str)],
            timeout=5
        )
        return True
    except Exception as e:
        print(f"[Russia Stability] Redis SET error: {str(e)[:80]}")
    return False


def _redis_lpush_trim(key, value, max_len=336):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return
    try:
        payload = json.dumps(value, default=str)
        for cmd in [
            ["LPUSH", key, payload],
            ["LTRIM", key, 0, max_len - 1],
        ]:
            requests.post(
                UPSTASH_REDIS_URL,
                headers={
                    "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                    "Content-Type": "application/json"
                },
                json=cmd,
                timeout=5
            )
    except Exception as e:
        print(f"[Russia Stability] Redis LPUSH error: {str(e)[:80]}")


# ============================================
# LIVE MARKET DATA FETCHERS
# ============================================

def _fetch_ruble_usd():
    """
    Fetch live Ruble/USD from open.er-api.com (free, no key).
    Returns (rate, status) where status = 'stable' | 'warning' | 'stress'.

    Ruble thresholds (historical context):
      Pre-war 2022:  ~75 RUB/USD (baseline)
      Post-sanctions: 80-90 RUB/USD (warning — capital controls holding)
      Stress zone:   >90 RUB/USD (sanctions biting through controls)
      Crisis zone:   >100 RUB/USD (March 2022 peak was ~140)
    """
    try:
        resp = requests.get(
            'https://open.er-api.com/v6/latest/USD',
            timeout=(5, 10)
        )
        if resp.status_code == 200:
            data = resp.json()
            rate = data.get('rates', {}).get('RUB')
            if rate:
                if rate >= 100:
                    status = 'crisis'
                elif rate >= 90:
                    status = 'stress'
                elif rate >= 80:
                    status = 'warning'
                else:
                    status = 'stable'
                print(f"[Russia Stability] Ruble/USD: {rate:.2f} ({status})")
                return round(rate, 2), status
    except Exception as e:
        print(f"[Russia Stability] Ruble/USD fetch error: {str(e)[:80]}")
    return None, 'unknown'


def _fetch_brent_price():
    """
    Fetch live Brent crude from Yahoo Finance (BZ=F). Free, no key.
    Returns (price, change_pct, status).

    Brent context for Russia:
      Russia's budget breaks even around $60-70/bbl (varies by year).
      G7 price cap is $60/bbl. Shadow fleet allows selling above cap.
      High Brent = MORE revenue for Russia (inverted vs. China).
      Very low Brent (<$60) = budget stress, sanctions more effective.
    """
    try:
        resp = requests.get(
            'https://query1.finance.yahoo.com/v8/finance/chart/BZ=F',
            headers={'User-Agent': 'Mozilla/5.0 AsifahAnalytics/1.0'},
            timeout=(5, 10)
        )
        if resp.status_code == 200:
            data = resp.json()
            meta = data.get('chart', {}).get('result', [{}])[0].get('meta', {})
            price = meta.get('regularMarketPrice') or meta.get('previousClose')
            prev  = meta.get('chartPreviousClose') or meta.get('previousClose')
            if price:
                change_pct = round(((price - prev) / prev) * 100, 2) if prev and prev != 0 else 0.0
                # For Russia: low price = stress (less revenue)
                if price < 60:
                    status = 'stress'    # Below G7 cap — sanctions maximally effective
                elif price < 70:
                    status = 'warning'   # Near budget breakeven
                else:
                    status = 'elevated'  # Russia earning above breakeven
                print(f"[Russia Stability] Brent: ${price:.2f} ({change_pct:+.2f}%, {status})")
                return round(price, 2), change_pct, status
    except Exception as e:
        print(f"[Russia Stability] Brent fetch error: {str(e)[:80]}")
    return None, 0.0, 'unknown'


def _fetch_urals_discount(brent_price):
    """
    Estimate Urals crude discount vs. Brent.
    Since Urals isn't freely available, we use a documented proxy:
    - Pre-2022: ~$2-3 discount to Brent (normal quality differential)
    - 2022-2023: $25-35 discount (sanctions shock)
    - 2024-2026: ~$10-18 discount (shadow fleet adapted, China/India buying)

    Returns (urals_est, discount, note).
    Source: Argus Media / Bloomberg commodity tracking.
    """
    if not brent_price:
        return None, None, 'Brent unavailable'
    # Current estimated discount range (April 2026)
    estimated_discount = 12.0  # Updated manually — Argus Media
    urals_est = round(brent_price - estimated_discount, 2)
    note = f'~${estimated_discount:.0f} discount to Brent · Argus Media est. Apr 2026'
    print(f"[Russia Stability] Urals est: ${urals_est:.2f} (Brent ${brent_price:.2f} - ${estimated_discount:.0f} discount)")
    return urals_est, estimated_discount, note


def _fetch_moex_index():
    """
    Fetch Moscow Exchange (MOEX) index via Alpha Vantage.
    MOEX is the primary Russian equity benchmark — a proxy for domestic
    business confidence and sanction impact on Russian capital markets.

    Alpha Vantage ticker: IMOEX (or MOEX) — may need INDEXRUS:IMOEX format.
    Falls back gracefully if unavailable.

    MOEX context:
      Pre-war 2022:  ~3,800 points (baseline)
      March 2022:    ~2,200 (sanctions shock bottom)
      Recovery 2023-24: ~3,000-3,500 (war economy adaptation)
      Stress level:  <2,500
    """
    if not ALPHA_VANTAGE_KEY:
        print("[Russia Stability] MOEX: No Alpha Vantage key")
        return None, 'unknown'
    try:
        # Alpha Vantage global quote endpoint
        resp = requests.get(
            'https://www.alphavantage.co/query',
            params={
                'function': 'GLOBAL_QUOTE',
                'symbol':   'IMOEX.ME',
                'apikey':   ALPHA_VANTAGE_KEY,
            },
            timeout=(5, 15)
        )
        if resp.status_code == 200:
            data = resp.json()
            quote = data.get('Global Quote', {})
            price = quote.get('05. price')
            change_pct = quote.get('10. change percent', '0%').replace('%', '')
            if price:
                price_f = float(price)
                if price_f < 2500:
                    status = 'stress'
                elif price_f < 3000:
                    status = 'warning'
                else:
                    status = 'stable'
                print(f"[Russia Stability] MOEX: {price_f:.0f} ({change_pct}%, {status})")
                return round(price_f, 0), status
        # Alpha Vantage sometimes returns note for rate limits
        note = data.get('Note') or data.get('Information', '')
        if note:
            print(f"[Russia Stability] MOEX Alpha Vantage note: {note[:80]}")
    except Exception as e:
        print(f"[Russia Stability] MOEX fetch error: {str(e)[:80]}")
    return None, 'unknown'


def _get_sanctions_economy_level(ruble_rate, ruble_status, brent_price, brent_status, moex_index, moex_status):
    """
    Convert live economic indicators into an instability level (0-5).
    Higher = more economic instability = lower stability score.

    Russia's economic stability paradox:
    - High Brent = GOOD for Russia (inverted vs. China)
    - Weak ruble = BAD (sanctions biting through capital controls)
    - Low MOEX = BAD (domestic capital flight / business confidence collapse)
    """
    level = 0

    # Ruble signal (primary)
    if ruble_status == 'crisis':
        level += 3
        print(f"[Russia Stability] Ruble crisis: +3 ({ruble_rate} RUB/USD)")
    elif ruble_status == 'stress':
        level += 2
        print(f"[Russia Stability] Ruble stress: +2 ({ruble_rate} RUB/USD)")
    elif ruble_status == 'warning':
        level += 1
        print(f"[Russia Stability] Ruble warning: +1 ({ruble_rate} RUB/USD)")

    # Brent signal (inverted — low Brent = bad for Russia)
    if brent_status == 'stress':
        level += 2
        print(f"[Russia Stability] Brent below G7 cap: +2 (${brent_price:.2f})")
    elif brent_status == 'warning':
        level += 1
        print(f"[Russia Stability] Brent near breakeven: +1 (${brent_price:.2f})")

    # MOEX signal
    if moex_status == 'stress':
        level += 1
        print(f"[Russia Stability] MOEX stress: +1")
    elif moex_status == 'warning':
        level += 0  # Warning alone not enough — Russia restricts market anyway

    return min(5, level)


# ============================================
# RHETORIC FINGERPRINT READER
# ============================================
def _read_rhetoric_fingerprint():
    """
    Read Russia signals from cross-theater Redis fingerprint.
    Written by rhetoric_tracker_russia.py every 12 hours.
    Returns (military_level, nuclear_level, hybrid_level, arctic_level, ukraine_level).
    """
    try:
        fingerprint = _redis_get(CROSSTHEATER_KEY) or {}
        russia = fingerprint.get('russia', {})
        mil_level     = russia.get('russia_military_level', 0)
        nuclear_level = russia.get('nuclear_level', 0)
        hybrid_level  = russia.get('hybrid_level', 0)
        arctic_level  = russia.get('arctic_level', 0)
        ukraine_level = russia.get('ukraine_level', 0)
        print(f"[Russia Stability] Rhetoric fingerprint: mil={mil_level}, nuc={nuclear_level}, "
              f"hyb={hybrid_level}, arc={arctic_level}, ukr={ukraine_level}")
        return mil_level, nuclear_level, hybrid_level, arctic_level, ukraine_level
    except Exception as e:
        print(f"[Russia Stability] Fingerprint read error: {str(e)[:80]}")
        return 0, 0, 0, 0, 0


# ============================================
# ARTICLE FETCHING + KEYWORD SCORING
# ============================================

KEYWORD_VECTORS = {

    'internal_cohesion': {
        # High signals = LOWER cohesion = LOWER stability
        3: [
            'russia mass protest', 'russia uprising', 'russia revolt',
            'russia anti-war riot', 'russia mutiny soldiers',
            'russia regional separatism', 'buryatia dagestan protest',
            'wagner mutiny russia', 'russia military refuses orders',
            'russia soldiers surrender mass',
        ],
        2: [
            'russia anti-war protest', 'russia demonstration',
            'russia arrested protesters', 'russia detained dissent',
            'russia civil unrest', 'russia draft protest',
            'russia desertion soldiers', 'russia military morale',
            'russia brain drain exodus', 'russians flee mobilization',
            'russia opposition arrested', 'navalny supporters',
            'russia ethnic minority protests', 'buryatia casualties',
        ],
        1: [
            'russia protest', 'russia dissent', 'russia unrest',
            'russia opposition', 'russia soldiers refuse',
            'russia emigrants', 'russia emigration',
        ],
    },

    'leadership': {
        # High signals = LOWER leadership stability
        3: [
            'putin health', 'putin successor', 'russia leadership crisis',
            'kremlin power struggle', 'silovik conflict',
            'russia coup attempt', 'russia leadership change',
            'gerasimov fired', 'russia minister arrested',
            'kremlin infighting', 'russia elite conflict',
        ],
        2: [
            'kremlin succession', 'russia leadership uncertainty',
            'putin isolated', 'russia oligarch arrested',
            'kremlin purge', 'russia official fired',
            'medvedev contradicts putin', 'russia elite flee',
            'russia billionaire dead', 'russia oligarch death',
        ],
        1: [
            'kremlin', 'putin statement', 'russia government',
            'russia leadership', 'lavrov', 'patrushev',
        ],
    },

    'global_alignment': {
        # High signals = WEAKER alignment (worse for Russia)
        3: [
            'china cuts russia support', 'india stops russian oil',
            'russia isolated completely', 'brics collapse russia',
            'china sanctions russia', 'russia loses ally',
            'north korea stops russia', 'russia arms embargo',
        ],
        2: [
            'russia sanctions tighten', 'russia secondary sanctions',
            'india reduces russia oil', 'turkey restricts russia',
            'russia payment problems china', 'russia yuan problems',
            'russia shadow fleet seized', 'russia oil tanker seized',
        ],
        1: [
            'russia sanctions', 'russia isolated', 'russia china',
            'russia india oil', 'russia brics', 'russia yuan',
            'russia shadow fleet', 'russia oil cap',
        ],
    },
}


def _fetch_newsapi_articles(query, days=3, max_results=30):
    if not NEWSAPI_KEY:
        return []
    try:
        from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
        resp = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q':        query,
                'from':     from_date,
                'language': 'en',
                'sortBy':   'relevancy',
                'pageSize': max_results,
                'apiKey':   NEWSAPI_KEY,
            },
            timeout=(5, 15)
        )
        if resp.status_code == 200:
            articles = resp.json().get('articles', [])
            print(f"[Russia Stability] NewsAPI '{query[:40]}': {len(articles)} articles")
            return articles
    except Exception as e:
        print(f"[Russia Stability] NewsAPI error: {str(e)[:80]}")
    return []


def _fetch_gdelt_articles(query, language='eng', days=3, max_records=25):
    try:
        params = {
            'query':      query,
            'mode':       'artlist',
            'maxrecords': max_records,
            'timespan':   f'{days}d',
            'format':     'json',
            'sourcelang': language,
        }
        resp = requests.get(
            'https://api.gdeltproject.org/api/v2/doc/doc',
            params=params,
            timeout=(5, 15)
        )
        if resp.status_code == 429:
            print(f"[Russia Stability] GDELT 429 rate limit — skipping: {query[:40]}")
            return []
        if resp.status_code == 200:
            articles = resp.json().get('articles', [])
            print(f"[Russia Stability] GDELT '{query[:40]}': {len(articles)} articles")
            time.sleep(0.5)
            return articles
    except Exception as e:
        print(f"[Russia Stability] GDELT error: {str(e)[:80]}")
    return []


def _score_vector_from_articles(articles, keyword_dict):
    """Score articles against a keyword vector. Returns level 0-5."""
    max_level = 0
    for art in articles:
        title = (art.get('title') or art.get('name') or '').lower()
        desc  = (art.get('description') or art.get('url') or '').lower()
        text  = f"{title} {desc}"
        for level in sorted(keyword_dict.keys(), reverse=True):
            for kw in keyword_dict[level]:
                if kw.lower() in text:
                    max_level = max(max_level, level)
                    break
    return max_level


# ============================================
# STABILITY SCORE COMPUTATION
# ============================================

def _compute_stability_score(vector_levels):
    """
    Compute composite stability score 0-100.
    Higher = MORE stable (inverted from instability).

    Weights:
      sanctions_economy  25%
      military_posture   25%
      internal_cohesion  20%
      leadership         15%
      global_alignment   15%
    """
    weights = {
        'sanctions_economy': 0.25,
        'military_posture':  0.25,
        'internal_cohesion': 0.20,
        'leadership':        0.15,
        'global_alignment':  0.15,
    }

    instability = sum(
        vector_levels.get(k, 0) * w * 20   # 20 = 100 / 5 levels
        for k, w in weights.items()
    )

    stability = max(0, min(100, round(100 - instability)))

    # Convergence penalty: 3+ vectors at L3+ means -10
    elevated = sum(1 for v in vector_levels.values() if v >= 3)
    if elevated >= 3:
        stability = max(0, stability - 10)
        print(f"[Russia Stability] Convergence penalty: {elevated} vectors at L3+")

    return stability


# ============================================
# MAIN SCAN
# ============================================

def run_russia_stability_scan():
    """Full Russia stability scan. Returns result dict."""
    scan_start = time.time()
    print(f"\n[Russia Stability] Starting scan at {datetime.now(timezone.utc).isoformat()}")

    # ── 1. LIVE MARKET DATA ──
    ruble_rate, ruble_status                    = _fetch_ruble_usd()
    brent_price, brent_change_pct, brent_status = _fetch_brent_price()
    urals_est, urals_discount, urals_note       = _fetch_urals_discount(brent_price)
    moex_index, moex_status                     = _fetch_moex_index()

    # ── 2. RHETORIC FINGERPRINT ──
    mil_level, nuclear_level, hybrid_level, arctic_level, ukraine_level = _read_rhetoric_fingerprint()

    # ── 3. SANCTIONS / ECONOMY VECTOR ──
    econ_level = _get_sanctions_economy_level(
        ruble_rate, ruble_status,
        brent_price, brent_status,
        moex_index, moex_status
    )

    # ── 4. MILITARY POSTURE VECTOR ──
    # Derived from rhetoric tracker fingerprint — already scored
    # Nuclear signaling at L3+ adds extra instability
    military_posture_level = max(mil_level, min(5, nuclear_level + 1 if nuclear_level >= 3 else mil_level))
    print(f"[Russia Stability] Military posture level: {military_posture_level}")

    # ── 5. ARTICLE-BASED VECTORS ──
    all_articles = []

    newsapi_queries = [
        ('Russia protest dissent anti-war unrest domestic',    'internal_cohesion'),
        ('Russia brain drain emigration exodus mobilization',  'internal_cohesion'),
        ('Putin health Kremlin succession leadership crisis',  'leadership'),
        ('Russia oligarch Kremlin purge silovik conflict',     'leadership'),
        ('Russia China sanctions India oil BRICS alignment',   'global_alignment'),
        ('Russia shadow fleet oil tanker sanctions evade',     'global_alignment'),
        ('Russia Ukraine war frontline Zaporizhzhia Kherson',  'sanctions_economy'),
        ('Russia ruble inflation economy wartime budget',      'sanctions_economy'),
        ('Russia military posture NATO nuclear Gerasimov',     'sanctions_economy'),
    ]

    article_buckets = {k: [] for k in KEYWORD_VECTORS.keys()}
    article_buckets['sanctions_economy'] = []   # Live market signals bucket

    articles_en     = []   # English articles for frontend tab
    articles_ru     = []   # Russian-language articles for frontend tab
    articles_reddit = []   # Reddit articles for frontend tab

    for query, bucket in newsapi_queries:
        fetched = _fetch_newsapi_articles(query, days=5)
        for a in fetched:
            a['language'] = 'en'
        all_articles.extend(fetched)
        article_buckets[bucket].extend(fetched)
        articles_en.extend(fetched)

    # GDELT for Russian-language signals
    gdelt_queries = [
        ('Россия протест оппозиция арест', 'internal_cohesion', 'rus'),
        ('Путин Кремль руководство преемник', 'leadership', 'rus'),
        ('Россия Китай санкции обход', 'global_alignment', 'rus'),
        ('Россия война Украина фронт', 'sanctions_economy', 'rus'),
        ('Россия экономика санкции инфляция рубль', 'sanctions_economy', 'rus'),
        ('Russia domestic unrest dissent protest', 'internal_cohesion', 'eng'),
        ('Russia sanctions economy inflation ruble', 'sanctions_economy', 'eng'),
        ('Russia Ukraine war ceasefire frontline 2026', 'sanctions_economy', 'eng'),
        ('Russia NATO military posture nuclear signaling', 'sanctions_economy', 'eng'),
    ]

    for query, bucket, lang in gdelt_queries:
        fetched = _fetch_gdelt_articles(query, language=lang, days=5)
        lang_tag = 'ru' if lang == 'rus' else 'en'
        for a in fetched:
            a['language'] = lang_tag
        all_articles.extend(fetched)
        article_buckets[bucket].extend(fetched)
        if lang_tag == 'ru':
            articles_ru.extend(fetched)
        else:
            articles_en.extend(fetched)

    # Reddit via GDELT
    reddit_queries = [
        'site:reddit.com Russia Ukraine war',
        'site:reddit.com Russia sanctions economy',
        'site:reddit.com Russia military Kremlin Putin',
    ]
    for rq in reddit_queries:
        fetched = _fetch_gdelt_articles(rq, language='eng', days=7)
        for a in fetched:
            a['language'] = 'reddit'
        all_articles.extend(fetched)
        articles_reddit.extend(fetched)

    # Score article-based vectors
    cohesion_level   = _score_vector_from_articles(article_buckets['internal_cohesion'], KEYWORD_VECTORS['internal_cohesion'])
    leadership_level = _score_vector_from_articles(article_buckets['leadership'],        KEYWORD_VECTORS['leadership'])
    alignment_level  = _score_vector_from_articles(article_buckets['global_alignment'],  KEYWORD_VECTORS['global_alignment'])

    print(f"[Russia Stability] Vectors: econ={econ_level}, mil={military_posture_level}, "
          f"cohesion={cohesion_level}, leadership={leadership_level}, alignment={alignment_level}")

    # ── 6. COMPOSITE SCORE ──
    vector_levels = {
        'sanctions_economy': econ_level,
        'military_posture':  military_posture_level,
        'internal_cohesion': cohesion_level,
        'leadership':        leadership_level,
        'global_alignment':  alignment_level,
    }

    stability_score = _compute_stability_score(vector_levels)
    label, color    = _stability_label(stability_score)

    scan_time = round(time.time() - scan_start, 1)
    scanned_at = datetime.now(timezone.utc).isoformat()

    print(f"[Russia Stability] Score: {stability_score} ({label}) in {scan_time}s, "
          f"{len(all_articles)} articles")

    result = {
        'success':              True,
        'country':              'Russia',
        'stability_score':      stability_score,
        'stability_label':      label,
        'stability_color':      color,

        # Vector levels
        'econ_level':           econ_level,
        'military_level':       military_posture_level,
        'cohesion_level':       cohesion_level,
        'leadership_level':     leadership_level,
        'alignment_level':      alignment_level,

        # Rhetoric tracker fingerprint pass-through
        'nuclear_level':        nuclear_level,
        'arctic_level':         arctic_level,
        'hybrid_level':         hybrid_level,
        'ukraine_level':        ukraine_level,

        # Live market data
        'ruble_usd':            ruble_rate,
        'ruble_status':         ruble_status,
        'brent_price':          brent_price,
        'brent_change_pct':     brent_change_pct,
        'brent_status':         brent_status,
        'urals_est':            urals_est,
        'urals_discount':       urals_discount,
        'urals_note':           urals_note,
        'moex_index':           moex_index,
        'moex_status':          moex_status,

        # Static reference data
        'static_economic':      STATIC_ECONOMIC,
        'war_status':           STATIC_WAR_STATUS,
        'leadership':           RUSSIA_LEADERSHIP,

        # Articles by language for frontend tabs
        'articles_en':          articles_en[:25],
        'articles_ru':          articles_ru[:25],
        'articles_reddit':      articles_reddit[:25],

        # Metadata
        'total_articles':       len(all_articles),
        'scan_time_seconds':    scan_time,
        'scanned_at':           scanned_at,
        'from_cache':           False,
        'version':              '1.1.0',
    }

    # Cache to Redis
    _redis_set(CACHE_KEY, result)
    _redis_lpush_trim(HISTORY_KEY, {
        'stability_score':  stability_score,
        'econ_level':       econ_level,
        'military_level':   military_posture_level,
        'cohesion_level':   cohesion_level,
        'leadership_level': leadership_level,
        'alignment_level':  alignment_level,
        'ruble_usd':        ruble_rate,
        'brent_price':      brent_price,
        'moex_index':       moex_index,
        'scanned_at':       scanned_at,
    })

    return result


# ============================================
# BACKGROUND REFRESH
# ============================================

def _background_loop():
    """Background thread: boot delay then refresh every SCAN_INTERVAL_HOURS."""
    time.sleep(90)  # Boot delay — let other modules initialize first
    while True:
        try:
            print("[Russia Stability] Background refresh starting...")
            run_russia_stability_scan()
        except Exception as e:
            print(f"[Russia Stability] Background refresh error: {str(e)[:80]}")
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def start_russia_stability_refresh():
    t = threading.Thread(target=_background_loop, daemon=True)
    t.start()
    print("[Russia Stability] Background refresh thread started")


# ============================================
# FLASK ENDPOINTS
# ============================================

def register_russia_stability_endpoints(app):

    @app.route('/api/stability/russia', methods=['GET'])
    def russia_stability():
        """
        Russia Stability Index — composite score across 5 vectors.
        ?force=true bypasses cache and runs a fresh scan.
        """
        force = request.args.get('force', 'false').lower() in ('true', '1', 'yes')

        if not force:
            cached = _redis_get(CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return jsonify(cached)

        global _stability_running
        with _stability_lock:
            if _stability_running:
                cached = _redis_get(CACHE_KEY)
                if cached:
                    cached['from_cache'] = True
                    cached['scan_in_progress'] = True
                    return jsonify(cached)
                return jsonify({'success': False, 'error': 'Scan in progress'}), 202
            _stability_running = True

        try:
            result = run_russia_stability_scan()
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500
        finally:
            with _stability_lock:
                _stability_running = False

    @app.route('/api/stability/russia/summary', methods=['GET'])
    def russia_stability_summary():
        """Lightweight summary for the russia.html stability card."""
        cached = _redis_get(CACHE_KEY)
        if not cached:
            return jsonify({
                'success': False,
                'error':   'No data yet — run /api/stability/russia?force=true first'
            }), 404

        return jsonify({
            'success':          True,
            'stability_score':  cached.get('stability_score', 0),
            'stability_label':  cached.get('stability_label', 'Unknown'),
            'stability_color':  cached.get('stability_color', '#6b7280'),
            'econ_level':       cached.get('econ_level', 0),
            'military_level':   cached.get('military_level', 0),
            'cohesion_level':   cached.get('cohesion_level', 0),
            'leadership_level': cached.get('leadership_level', 0),
            'alignment_level':  cached.get('alignment_level', 0),
            'nuclear_level':    cached.get('nuclear_level', 0),
            'ruble_usd':        cached.get('ruble_usd'),
            'ruble_status':     cached.get('ruble_status', 'unknown'),
            'brent_price':      cached.get('brent_price'),
            'brent_change_pct': cached.get('brent_change_pct', 0),
            'brent_status':     cached.get('brent_status', 'unknown'),
            'urals_est':        cached.get('urals_est'),
            'urals_discount':   cached.get('urals_discount'),
            'urals_note':       cached.get('urals_note', ''),
            'moex_index':       cached.get('moex_index'),
            'moex_status':      cached.get('moex_status', 'unknown'),
            'leadership':       cached.get('leadership', RUSSIA_LEADERSHIP),
            'total_articles':   cached.get('total_articles', 0),
            'articles_en':      cached.get('articles_en', []),
            'articles_ru':      cached.get('articles_ru', []),
            'articles_reddit':  cached.get('articles_reddit', []),
            'scanned_at':       cached.get('scanned_at', ''),
            'version':          '1.1.0-russia-stability',
        })

    @app.route('/api/stability/russia/history', methods=['GET'])
    def russia_stability_history():
        """Return stability score history for trend chart."""
        history = _redis_get(HISTORY_KEY)
        if not isinstance(history, list):
            history = []
        return jsonify({
            'success': True,
            'count':   len(history),
            'history': history[:120],
        })

    # Start background refresh thread
    start_russia_stability_refresh()

    print("[Russia Stability] Endpoints registered: "
          "/api/stability/russia, /api/stability/russia/summary, /api/stability/russia/history")
