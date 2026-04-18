"""
========================================
BLUESKY — Executive & Government Statement Monitor (v1.0.0)
========================================
Drop-in replacement for the deprecated Nitter module (April 2026).

Bluesky's public AppView API (https://public.api.bsky.app) requires NO auth
and exposes a stable JSON endpoint at:
    /xrpc/app.bsky.feed.getAuthorFeed?actor={handle}&limit={N}

We track two types of accounts:
  1. Native Bluesky accounts — official gov/institutional accounts that
     migrated to Bluesky (StateDept, NATO, etc.)
  2. govmirrors.com mirrors — volunteer-run project that mirrors X posts
     to Bluesky for government accounts that haven't migrated. Lets us
     retain signal from holdouts like Russian MoD, Trump, etc.

Architecture mirrors the old Nitter module:
  - NITTER_ACCOUNTS_EUROPE  →  BLUESKY_ACCOUNTS_EUROPE
  - fetch_nitter_account()  →  fetch_bluesky_account()
  - fetch_nitter_for_target()  →  fetch_bluesky_for_target()

Returns the same article dict shape so downstream scoring code
works unchanged. Only the module name and source field differ.
"""

import requests
import time
from datetime import datetime, timezone, timedelta

# Public AppView — no auth required for read-only
BLUESKY_API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"

# Timeout for individual account fetches (seconds)
# Bluesky is fast — public API typically responds in <500ms.
BLUESKY_TIMEOUT = 8

# ────────────────────────────────────────────────────────────────
# ACCOUNT DIRECTORY (mirrors shape of NITTER_ACCOUNTS_EUROPE)
# ────────────────────────────────────────────────────────────────
# (handle, weight, targets[], description)
#
# handle:  Bluesky handle WITHOUT the @ prefix
#          e.g. "state-department.bsky.social"
#          govmirrors: "statedept.govmirrors.com" (mirror of @StateDept)
#
# weight:  1.2 = head of state / direct govt statement
#          1.1 = minister / senior official / MFA
#          1.0 = institutional / military command
#          0.9 = multilateral / monitoring / analytical
#
# targets: list of Europe backend target keys this account is relevant to.
#          Use ['*'] for all targets (worldwide-caution scope).
#
# A note on govmirrors.com:
#   This is a volunteer-run project (https://govmirrors.com) that mirrors
#   X/Twitter government accounts onto Bluesky. It's not official, but it
#   provides a legal, stable path to monitor accounts that haven't left X.
#   Mirrors can go dark — if fetches fail consistently, comment the handle.
# ────────────────────────────────────────────────────────────────
BLUESKY_ACCOUNTS_EUROPE = [
    # ── US government — native Bluesky ────────────────────────
    ('state-department.bsky.social',  1.0, ['*'],
        'US State Department (official) — travel advisories, diplomatic signals'),

    # ── US government — govmirrors (X-sourced) ─────────────────
    # Use mirrors ONLY if native Bluesky account does not exist.
    ('potus.govmirrors.com',          1.0, ['greenland', 'ukraine', 'russia', 'poland', 'hungary'],
        'POTUS (X mirror) — White House executive statements'),
    ('statedept.govmirrors.com',      0.9, ['*'],
        'StateDept (X mirror) — redundant with native, kept as backup'),

    # ── NATO / EU institutions — native Bluesky ────────────────
    ('natohq.bsky.social',            1.0, ['*'],
        'NATO (official) — alliance posture, deployments, Article 5'),

    # ── Ukraine — native Bluesky ───────────────────────────────
    ('zelenskyyua.bsky.social',       1.2, ['ukraine', 'russia'],
        'President Zelensky (if native) — direct statements'),
    ('mfa.gov.ua',                    1.1, ['ukraine', 'russia'],
        'Ukraine MFA (custom domain) — diplomatic signals'),

    # ── European institutions — where available ────────────────
    # Many European institutional accounts are on Mastodon/EU Voice rather
    # than Bluesky. Keep this list minimal and verified; add handles as
    # they're confirmed live. Unknown handles will 404 harmlessly.
    ('euvsdisinfo.bsky.social',       0.9, ['russia', 'ukraine', 'hungary'],
        'EU vs Disinfo — Russian disinformation monitoring'),

    # ── govmirrors fallbacks for X-only accounts ──────────────
    ('realdonaldtrump.govmirrors.com', 1.2, ['greenland', 'ukraine', 'russia', 'poland', 'hungary'],
        'Trump (X mirror) — Greenland/Ukraine/NATO statements'),
    ('secrubio.govmirrors.com',        1.1, ['greenland', 'ukraine', 'russia', 'poland'],
        'US SecState Rubio (X mirror) — Europe/Arctic policy'),
    ('modrussia.govmirrors.com',       1.1, ['russia', 'ukraine'],
        'Russian MoD (X mirror) — official claims/posture'),
    ('mfarussia.govmirrors.com',       1.0, ['russia', 'ukraine'],
        'Russian MFA (X mirror) — diplomatic signaling'),
]


def fetch_bluesky_account(handle, weight=1.0, limit=20, timeout=BLUESKY_TIMEOUT):
    """
    Fetch recent posts from a single Bluesky account.

    Uses the public AppView API — no authentication required.
    Returns list of article dicts matching the Europe backend schema.

    On 404 (handle doesn't exist) → logs and returns []
    On 429 (rate limit) → logs and returns []
    On network/parse error → logs and returns []
    """
    headers = {
        'User-Agent': 'AsifahAnalytics/1.0 (+https://asifahanalytics.com)',
        'Accept': 'application/json',
    }
    params = {'actor': handle, 'limit': limit}

    try:
        resp = requests.get(BLUESKY_API, headers=headers, params=params, timeout=timeout)

        if resp.status_code == 404:
            print(f'[Bluesky] @{handle}: handle not found (404) — consider removing from list')
            return []
        if resp.status_code == 429:
            print(f'[Bluesky] @{handle}: rate-limited (429) — backing off')
            return []
        if resp.status_code != 200:
            print(f'[Bluesky] @{handle}: HTTP {resp.status_code}')
            return []

        data = resp.json()
        feed = data.get('feed', [])
        articles = []

        for item in feed:
            post = item.get('post', {})
            record = post.get('record', {})
            author = post.get('author', {})

            text = record.get('text', '') or ''
            if not text.strip():
                continue

            # Bluesky timestamps are ISO-8601 UTC
            pub = record.get('createdAt') or post.get('indexedAt') or ''

            # Construct canonical post URL from DID + rkey
            # Format: https://bsky.app/profile/{handle}/post/{rkey}
            post_uri = post.get('uri', '')
            rkey = post_uri.rsplit('/', 1)[-1] if post_uri else ''
            url = f'https://bsky.app/profile/{handle}/post/{rkey}' if rkey else f'https://bsky.app/profile/{handle}'

            # Description = first 400 chars of text (Bluesky is short-form)
            desc = text[:400]

            articles.append({
                'title':       text[:200],
                'description': desc,
                'url':         url,
                'publishedAt': pub,
                'source':      {'name': f'Bluesky @{handle}'},
                'content':     text[:500],
                'language':    'en',
                '_bluesky_weight':  weight,
                '_bluesky_author':  author.get('displayName', handle),
            })

        if articles:
            print(f'[Bluesky] @{handle}: {len(articles)} posts')
        return articles

    except requests.exceptions.Timeout:
        print(f'[Bluesky] @{handle}: timeout after {timeout}s')
        return []
    except Exception as e:
        print(f'[Bluesky] @{handle}: {str(e)[:80]}')
        return []


def fetch_bluesky_for_target(target, days=7, max_posts_per_account=20):
    """
    Fetch Bluesky posts relevant to a specific Europe target.

    Filters by:
      - target key (account must have '*' or target in its targets list)
      - recency (post must be within last {days} days)
      - deduplication (URL-based)

    Returns list of article dicts ready for downstream scoring.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_posts = []
    seen_urls = set()
    accounts_queried = 0

    for handle, weight, targets, desc in BLUESKY_ACCOUNTS_EUROPE:
        # Skip accounts not relevant to this target
        if '*' not in targets and target not in targets:
            continue

        accounts_queried += 1
        posts = fetch_bluesky_account(handle, weight=weight, limit=max_posts_per_account)

        for p in posts:
            if p['url'] in seen_urls:
                continue

            # Recency filter
            try:
                pub_str = p['publishedAt'].replace('Z', '+00:00')
                pub = datetime.fromisoformat(pub_str)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub < cutoff:
                    continue
            except Exception:
                # If date parsing fails, keep the post (better than losing signal)
                pass

            seen_urls.add(p['url'])
            all_posts.append(p)

        # Light politeness delay — Bluesky public API is fast but we
        # don't want to look abusive
        time.sleep(0.2)

    print(f'[Bluesky] {target}: {len(all_posts)} posts from {accounts_queried} accounts queried')
    return all_posts
