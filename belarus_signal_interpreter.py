"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — BELARUS SIGNAL INTERPRETER
  v1.0.0 (Apr 30 2026)
═══════════════════════════════════════════════════════════════════════

Analytical layer for the Belarus rhetoric tracker. Reads scan_data
(produced by rhetoric_tracker_belarus.py), applies red/green-line rules,
detects historical patterns, builds So-What narrative, and emits
canonical top_signals[] for the Europe Regional BLUF synthesis.

ANALYTICAL FRAMING:
  Belarus is the most strategically dependent state in Russia's
  near-abroad — economically, militarily, and politically. The
  interpreter watches three concurrent dynamics:
    1. Lukashenko domestic stability (succession watch)
    2. Russian forces in Belarus (Ukraine war facilitator)
    3. Strategic axis cooperation (Iran/China via SCO)
  Plus the cross-cutting commodity vector (potash dominance, energy
  transit, sanctions bypass).

ACTOR FRAMEWORK (7 actors):
  - lukashenko_regime
  - russian_forces_in_belarus
  - belarusian_opposition
  - nato_border_states
  - iran_belarus_axis
  - china_belarus_axis
  - ukraine_border_signals

CROSS-THEATER FINGERPRINTS WRITTEN:
  - belarus_iran_active        → consumed by Russia + Iran trackers
  - belarus_russia_axis        → consumed by Russia tracker
  - nato_perimeter_pressure    → consumed by Russia + Greenland trackers
  - lukashenko_succession_watch → consumed by Russia + Iran trackers

COMMODITY INTEGRATION (light, Phase 1):
  Reads from Europe backend's commodity proxy at
  /api/europe/commodity/belarus and adds ONE analytical band
  (commodity_pressure) to top_signals. Triggers a small escalation
  modifier when commodity alert is high/critical.

USAGE:
  from belarus_signal_interpreter import interpret_signals
  result = interpret_signals(scan_data)
"""

import requests
from datetime import datetime, timezone

INTERPRETER_VERSION = '1.0.0'

# Europe backend self-call URL (signal interpreter runs in Europe backend)
COMMODITY_PROXY_URL = 'http://localhost:10000/api/europe/commodity/belarus'

# ============================================================
# RED LINES
# ============================================================
# Each red line is an analytical trigger that, when matched, signals
# a meaningful escalation in Belarus's strategic posture.
# Severity: 1 (mild) → 5 (catastrophic)
# Status: 'INACTIVE' | 'APPROACHING' | 'BREACHED'
# ============================================================
RED_LINES = [
    {
        'id':       'nuclear_deployment_expansion',
        'category': 'Nuclear',
        'title':    'Russian Nuclear Deployment Expansion',
        'severity': 5,
        'description':
            'Indicators of additional Russian tactical nuclear systems being '
            'transferred to Belarus, expanded storage facility construction, '
            'or warhead count growth beyond the 2023 baseline. Compresses '
            'NATO decision-making timelines on the eastern flank.',
        'triggers_breached': [
            'iskander', 'tactical nuclear', 'warhead transfer',
            'asipovichy', 'nuclear storage', 'dual-key',
            'ядерное оружие', 'тактическое ядерное',
        ],
        'triggers_approaching': [
            'nuclear sharing', 'nuclear capable', 'нести ядерное',
            'nuclear exercise', 'nuclear drill',
        ],
    },
    {
        'id':       'suwalki_gap_threat_belarus',
        'category': 'NATO Border',
        'title':    'Suwałki Gap Threat Indicators',
        'severity': 5,
        'description':
            'Belarusian or Russian forces postured to seize or interdict the '
            '65-mile corridor between Belarus and Kaliningrad — the land '
            'bridge connecting Poland to Lithuania and the Baltic states. '
            'Most strategically sensitive geography on NATO\'s eastern flank.',
        'triggers_breached': [
            'suwałki gap', 'suwalki corridor', 'kaliningrad land bridge',
            'baltic land corridor cut', 'belarus border seizure',
        ],
        'triggers_approaching': [
            'suwalki', 'lithuania border', 'poland border closure',
            'baltic isolation', 'kaliningrad reinforcement',
        ],
    },
    {
        'id':       'wagner_remnant_mobilization',
        'category': 'Military',
        'title':    'Wagner Remnant Mobilization in Belarus',
        'severity': 4,
        'description':
            'Reports of Wagner Group residuals (post-2023 mutiny relocation) '
            'mobilizing for offensive operations from Belarusian territory, '
            'particularly toward NATO border regions or Ukrainian frontier.',
        'triggers_breached': [
            'wagner mobilization', 'wagner offensive', 'pmc deployment belarus',
            'group wagner active', 'вагнер мобилизация',
        ],
        'triggers_approaching': [
            'wagner', 'pmc training', 'wagner camp',
            'private military', 'частная военная',
        ],
    },
    {
        'id':       'lukashenko_succession_crisis',
        'category': 'Regime',
        'title':    'Lukashenko Succession Crisis',
        'severity': 4,
        'description':
            'Acute health event, sudden incapacitation, or open succession '
            'maneuvering by the security services or Russian-backed candidates. '
            'Creates a window of regime instability that Russia is positioned '
            'to exploit for deeper integration.',
        'triggers_breached': [
            'lukashenko hospitalized', 'lukashenko incapacitated',
            'lukashenko died', 'лукашенко скончался', 'лукашенко в больнице',
            'transitional council', 'belarus succession',
        ],
        'triggers_approaching': [
            'lukashenko health', 'health concerns lukashenko',
            'лукашенко здоровье', 'absent from public', 'medical leave',
        ],
    },
    {
        'id':       'migrant_weaponization_surge',
        'category': 'Hybrid',
        'title':    'Migrant Weaponization Surge',
        'severity': 3,
        'description':
            'Renewed or intensified Belarusian state-organized funneling of '
            'third-country migrants to NATO borders (Poland, Lithuania, '
            'Latvia) as a hybrid pressure tool — pattern first observed 2021.',
        'triggers_breached': [
            'migrant surge belarus', 'border breach lithuania',
            'organized migration belarus', 'hybrid attack border',
            'мигранты белоруссия граница',
        ],
        'triggers_approaching': [
            'migrants belarus border', 'border pressure',
            'migrant pushback', 'frontex',
        ],
    },
    {
        'id':       'iran_belarus_capability_transfer',
        'category': 'Axis Cooperation',
        'title':    'Iran-Belarus Capability Transfer',
        'severity': 4,
        'description':
            'Concrete evidence of Iranian military technology transfer to '
            'Belarus — drones, missile components, training. Would establish '
            'first formal Iran defense relationship with a state on NATO\'s '
            'perimeter.',
        'triggers_breached': [
            'shahed belarus', 'iran drone belarus', 'iranian missile belarus',
            'tehran minsk transfer', 'iran technology belarus',
            'иран беларусь беспилотник',
        ],
        'triggers_approaching': [
            'iran belarus cooperation', 'sco trilateral',
            'khrenin talaei', 'belarus tehran defense',
            'sco belarus iran',
        ],
    },
    {
        'id':       'china_strategic_anchor_belarus',
        'category': 'Axis Cooperation',
        'title':    'China Strategic Anchor in Belarus',
        'severity': 3,
        'description':
            'PRC formalization of Belarus as a strategic continental anchor — '
            'industrial park expansion, military cooperation MoUs, BRI rail '
            'route reconfiguration. Cements sanctions-bypass infrastructure.',
        'triggers_breached': [
            'china belarus military', 'plac belarus', 'great stone expansion',
            'beijing minsk strategic', 'китай беларусь военный',
        ],
        'triggers_approaching': [
            'china belarus cooperation', 'great stone industrial',
            'belt and road belarus', 'sco anchor', 'pla joint exercise',
        ],
    },
    {
        'id':       'opposition_crackdown_intensification',
        'category': 'Regime',
        'title':    'Opposition Crackdown Intensification',
        'severity': 2,
        'description':
            'Mass arrest sweeps, new Article 130 prosecutions, increased '
            'cross-border repression of exiled opposition. Pattern suggests '
            'regime nervousness about succession or external events.',
        'triggers_breached': [
            'mass arrest belarus', 'opposition crackdown',
            'tsikhanouskaya threat', 'massive raids belarus',
            'политические заключенные массовые',
        ],
        'triggers_approaching': [
            'political prisoner', 'viasna report', 'article 130',
            'tsikhanouskaya', 'kalinouski regiment',
        ],
    },
]


# ============================================================
# GREEN LINES (de-escalation / off-ramps)
# ============================================================
GREEN_LINES = [
    {
        'id':       'nuclear_de_escalation',
        'category': 'Nuclear',
        'title':    'Nuclear De-escalation Signaling',
        'description':
            'Public Russian or Belarusian statements indicating reduction in '
            'nuclear posture, withdrawal of Iskanders, or new arms control '
            'overtures involving Belarus.',
        'triggers_active': [
            'iskander withdrawal', 'nuclear pullback', 'arms control belarus',
            'denuclearization',
        ],
        'triggers_signaled': [
            'nuclear restraint', 'nuclear de-escalation',
        ],
    },
    {
        'id':       'lukashenko_succession_orderly',
        'category': 'Regime',
        'title':    'Orderly Succession Process',
        'description':
            'Constitutional succession framework activated, transition team '
            'announced, smooth handover indicators rather than crisis.',
        'triggers_active': [
            'orderly transition belarus', 'constitutional succession',
            'transition team announced',
        ],
        'triggers_signaled': [
            'succession plan', 'lukashenko successor',
        ],
    },
    {
        'id':       'migrant_corridor_stabilization',
        'category': 'Hybrid',
        'title':    'Border Migrant Stabilization',
        'description':
            'Belarus reduces migrant funneling, reopens dialogue with NATO '
            'border states, IOM/UNHCR engagement on humanitarian routes.',
        'triggers_active': [
            'border reopening belarus', 'iom belarus dialogue',
            'migration agreement border',
        ],
        'triggers_signaled': [
            'border de-escalation', 'humanitarian corridor',
        ],
    },
    {
        'id':       'opposition_political_prisoner_release',
        'category': 'Regime',
        'title':    'Political Prisoner Release',
        'description':
            'Mass release of political prisoners, often in exchange for '
            'sanctions relief or diplomatic engagement signals.',
        'triggers_active': [
            'political prisoner release', 'mass amnesty belarus',
            'bialiatski freed', 'tikhanovsky released',
        ],
        'triggers_signaled': [
            'prisoner release indicated', 'amnesty considered',
        ],
    },
    {
        'id':       'us_belarus_diplomatic_engagement',
        'category': 'Diplomatic',
        'title':    'US-Belarus Diplomatic Re-engagement',
        'description':
            'Resumption of senior-level US-Belarus diplomatic dialogue, '
            'potential easing of sanctions language, or embassy normalization.',
        'triggers_active': [
            'us belarus dialogue', 'sanctions easing belarus',
            'embassy minsk reopening',
        ],
        'triggers_signaled': [
            'diplomatic outreach belarus', 'sanctions review belarus',
        ],
    },
]


# ============================================================
# RED LINE SCORING
# ============================================================

def _check_keywords(scan_data, keywords):
    """Match keywords against scan_data article corpus + signals."""
    if not keywords:
        return 0
    corpus_parts = []

    # Articles in any language
    for key in ('articles_en', 'articles_ru', 'articles_be',
                'articles_pl', 'articles_lt'):
        for art in (scan_data.get(key) or []):
            corpus_parts.append((art.get('title') or '').lower())
            corpus_parts.append((art.get('description') or '').lower())
            corpus_parts.append((art.get('summary') or '').lower())

    # Telegram + Bluesky + Reddit signals
    for key in ('telegram_messages', 'bluesky_signals', 'reddit_signals'):
        for sig in (scan_data.get(key) or []):
            corpus_parts.append((sig.get('text') or sig.get('title') or '').lower())

    corpus = ' | '.join(corpus_parts)
    if not corpus:
        return 0

    matches = 0
    for kw in keywords:
        if kw.lower() in corpus:
            matches += 1
    return matches


def _score_red_lines(scan_data):
    """Evaluate each red line against scan corpus, return triggered list."""
    triggered = []
    for rl in RED_LINES:
        breached_hits    = _check_keywords(scan_data, rl.get('triggers_breached', []))
        approaching_hits = _check_keywords(scan_data, rl.get('triggers_approaching', []))

        if breached_hits >= 2:
            status = 'BREACHED'
        elif breached_hits >= 1 or approaching_hits >= 3:
            status = 'APPROACHING'
        elif approaching_hits >= 1:
            status = 'WATCHING'
        else:
            status = 'INACTIVE'

        triggered.append({
            'id':              rl['id'],
            'category':        rl['category'],
            'title':           rl['title'],
            'severity':        rl['severity'],
            'description':     rl['description'],
            'status':          status,
            'breached_hits':   breached_hits,
            'approaching_hits': approaching_hits,
        })
    return triggered


def _score_green_lines(scan_data):
    """Evaluate green lines, return triggered list."""
    triggered = []
    for gl in GREEN_LINES:
        active_hits   = _check_keywords(scan_data, gl.get('triggers_active', []))
        signaled_hits = _check_keywords(scan_data, gl.get('triggers_signaled', []))

        if active_hits >= 1:
            status = 'ACTIVE'
        elif signaled_hits >= 1:
            status = 'SIGNALED'
        else:
            status = 'DORMANT'

        triggered.append({
            'id':            gl['id'],
            'category':      gl['category'],
            'title':         gl['title'],
            'description':   gl['description'],
            'status':        status,
            'active_hits':   active_hits,
            'signaled_hits': signaled_hits,
        })
    return triggered


# ============================================================
# COMMODITY INTEGRATION (Phase 1: light)
# ============================================================

def _fetch_commodity_signal():
    """
    Reads from Europe commodity proxy. Returns analytical band ready for
    top_signals, plus an escalation modifier (0..+5).
    Graceful fallback to None if unavailable.
    """
    try:
        resp = requests.get(COMMODITY_PROXY_URL, timeout=4)
        if resp.status_code != 200:
            return None
        d = resp.json()
        if not d.get('success', True):
            return None

        alert = (d.get('alert_level') or 'normal').lower()
        pressure = d.get('commodity_pressure', 0)
        commodities = d.get('commodity_summaries') or []
        top_signals_in = d.get('top_signals') or []

        modifier_map = {'normal': 0, 'elevated': 1, 'high': 3, 'critical': 5}
        modifier = modifier_map.get(alert, 0)

        # Build short_text from top commodity by signal count
        if commodities:
            top_c = max(commodities, key=lambda c: c.get('signal_count', 0) or 0)
            top_name = (top_c.get('name') or top_c.get('commodity') or 'commodity').upper()
            top_sigs = top_c.get('signal_count', 0)
            short = f"Commodity Pressure: {alert.upper()} — {top_name} ({top_sigs} signals)"
        else:
            short = f"Commodity Pressure: {alert.upper()}"

        # Long form for tooltip
        long_parts = [
            f"Belarus + Russia together control ~40% of global potash supply.",
            f"Potash sanctions bypass via Russian ports + China rail since 2022.",
            f"Hosts Russian tactical nuclear weapons since 2023 — uranium / strategic-mineral signal vector.",
        ]
        if commodities:
            top3 = sorted(commodities, key=lambda c: c.get('signal_count', 0) or 0, reverse=True)[:3]
            cmd_summary = ', '.join(
                f"{(c.get('name') or c.get('commodity') or '').upper()} ({c.get('signal_count', 0)})"
                for c in top3
            )
            long_parts.append(f"Top exposures by signal count: {cmd_summary}.")
        long = ' '.join(long_parts)

        band = {
            'category':    'commodity',
            'level':       alert,
            'short_text':  short,
            'long_text':   long,
            'icon':        '🛢️',
            'source_link': '/commodities.html#potash',
            'pressure':    pressure,
        }
        return {
            'band':              band,
            'escalation_modifier': modifier,
            'pressure':          pressure,
            'alert':             alert,
        }
    except Exception as e:
        print(f'[Belarus Interpreter] Commodity fetch failed: {str(e)[:120]}')
        return None


# ============================================================
# DIPLOMATIC TRACK (canonical pattern)
# ============================================================

CEASEFIRE_TRIGGERS = [
    'belarus mediation', 'minsk talks revived', 'lukashenko mediator',
    'release of prisoners', 'minsk format',
    'переговоры минск', 'минский формат',
]


def _score_diplomatic_track(scan_data, green_lines_triggered):
    """Aggregate diplomatic engagement signals."""
    matches = _check_keywords(scan_data, CEASEFIRE_TRIGGERS)
    active_gls = [g for g in green_lines_triggered if g['status'] == 'ACTIVE']
    diplomatic_score = matches + (len(active_gls) * 2)

    if diplomatic_score >= 6:
        scenario = 'Active Diplomatic Engagement'
        modifier = -10
    elif diplomatic_score >= 3:
        scenario = 'Tentative Diplomatic Signals'
        modifier = -5
    elif diplomatic_score >= 1:
        scenario = 'Limited De-escalation Indicators'
        modifier = -2
    else:
        scenario = 'No Active De-escalation Track'
        modifier = 0

    return {
        'score':           diplomatic_score,
        'scenario':        scenario,
        'modifier':        modifier,
        'active_green_lines_count': len(active_gls),
    }


# ============================================================
# SO WHAT BUILDER
# ============================================================

def _build_so_what(scan_data, red_lines_triggered, green_lines_triggered,
                   diplomatic, commodity_signal):
    """
    Build the analytical 'so what' narrative — what does this scan mean
    in plain analytical language?
    """
    breached = [r for r in red_lines_triggered if r['status'] == 'BREACHED']
    approaching = [r for r in red_lines_triggered if r['status'] == 'APPROACHING']
    active_gl = [g for g in green_lines_triggered if g['status'] == 'ACTIVE']

    # Highest severity drives top scenario
    highest_severity = max((r['severity'] for r in breached), default=0)

    # Determine scenario
    if highest_severity >= 5:
        scenario = 'CRITICAL: Strategic Red Line Breached'
        priority = 'critical'
    elif highest_severity >= 4 or len(breached) >= 2:
        scenario = 'HIGH: Multiple Escalation Indicators'
        priority = 'high'
    elif breached or len(approaching) >= 3:
        scenario = 'ELEVATED: Approaching Threshold'
        priority = 'elevated'
    elif approaching:
        scenario = 'WATCH: Early Warning Indicators Active'
        priority = 'watch'
    else:
        scenario = 'NORMAL: Baseline Monitoring'
        priority = 'normal'

    # Build assessment paragraph
    assessment_parts = []

    # Lead with breached red lines
    if breached:
        breached_titles = ', '.join(r['title'] for r in breached[:3])
        assessment_parts.append(
            f"Red line(s) breached: {breached_titles}."
        )

    # Approaching red lines
    if approaching:
        approaching_titles = ', '.join(r['title'] for r in approaching[:3])
        assessment_parts.append(
            f"Approaching threshold: {approaching_titles}."
        )

    # Diplomatic context
    if diplomatic['score'] > 0:
        assessment_parts.append(
            f"Diplomatic track: {diplomatic['scenario'].lower()} "
            f"(score {diplomatic['score']})."
        )

    # Active green lines
    if active_gl:
        gl_titles = ', '.join(g['title'] for g in active_gl[:2])
        assessment_parts.append(
            f"Active de-escalation indicators: {gl_titles}."
        )

    # Commodity context (if loaded)
    if commodity_signal and commodity_signal.get('alert') != 'normal':
        assessment_parts.append(
            f"Commodity pressure: {commodity_signal['alert']} "
            f"(potash + energy transit; sanctions bypass dynamics)."
        )

    # Default if quiet
    if not assessment_parts:
        assessment_parts.append(
            "No active red lines. Monitoring baseline rhetoric, regime "
            "stability, axis cooperation, and NATO border posture."
        )

    return {
        'scenario':       scenario,
        'priority':       priority,
        'assessment':     ' '.join(assessment_parts),
        'breached_count': len(breached),
        'approaching_count': len(approaching),
        'active_green_count': len(active_gl),
    }


# ============================================================
# TOP SIGNALS BUILDER (canonical schema for BLUF synthesis)
# ============================================================

def _build_top_signals(red_lines_triggered, green_lines_triggered,
                       diplomatic, commodity_signal, scan_data):
    """
    Emit canonical top_signals[] for Europe Regional BLUF + GPI.

    Each signal has:
      - category (e.g., 'nuclear', 'regime', 'axis', 'border', 'commodity')
      - level    ('critical', 'high', 'elevated', 'normal')
      - short_text (for hub display)
      - long_text  (for tooltip)
      - icon
      - source_link (optional)
    """
    signals = []
    SEVERITY_TO_LEVEL = {5: 'critical', 4: 'high', 3: 'elevated',
                         2: 'normal', 1: 'normal'}

    # 1. Red lines (BREACHED first, then APPROACHING)
    breached = [r for r in red_lines_triggered if r['status'] == 'BREACHED']
    breached.sort(key=lambda r: -r['severity'])
    for r in breached[:3]:
        signals.append({
            'category':   r['category'].lower().replace(' ', '_'),
            'level':      SEVERITY_TO_LEVEL.get(r['severity'], 'normal'),
            'short_text': f"BREACHED: {r['title']}",
            'long_text':  r['description'],
            'icon':       '🚨',
            'source_link': f"/rhetoric-belarus.html#{r['id']}",
        })

    approaching = [r for r in red_lines_triggered if r['status'] == 'APPROACHING']
    approaching.sort(key=lambda r: -r['severity'])
    for r in approaching[:2]:
        signals.append({
            'category':   r['category'].lower().replace(' ', '_'),
            'level':      'elevated',
            'short_text': f"Approaching: {r['title']}",
            'long_text':  r['description'],
            'icon':       '⚠️',
            'source_link': f"/rhetoric-belarus.html#{r['id']}",
        })

    # 2. Active green lines (de-escalation)
    active_gl = [g for g in green_lines_triggered if g['status'] == 'ACTIVE']
    for g in active_gl[:2]:
        signals.append({
            'category':   'diplomatic',
            'level':      'normal',
            'short_text': f"De-escalation: {g['title']}",
            'long_text':  g['description'],
            'icon':       '🟢',
            'source_link': f"/rhetoric-belarus.html#{g['id']}",
        })

    # 3. Commodity signal (Phase 1 light integration)
    if commodity_signal and commodity_signal.get('band'):
        signals.append(commodity_signal['band'])

    # 4. Diplomatic track summary (only if scenario is meaningful)
    if diplomatic['score'] >= 3:
        signals.append({
            'category':   'diplomatic',
            'level':      'normal',
            'short_text': f"Diplomatic Track: {diplomatic['scenario']}",
            'long_text':  f"Diplomatic score: {diplomatic['score']}. "
                          f"Active green lines: {diplomatic['active_green_lines_count']}.",
            'icon':       '🤝',
            'source_link': '/rhetoric-belarus.html#diplomatic',
        })

    return signals[:7]  # cap at 7 entries


# ============================================================
# CROSS-THEATER FINGERPRINTS
# ============================================================

def _build_fingerprints(red_lines_triggered, commodity_signal):
    """
    Cross-theater fingerprints for downstream tracker consumption.
    Each is a boolean + level pair used by Russia, Iran, Greenland, GPI.
    """
    fingerprints = {
        'belarus_iran_active':         False,
        'belarus_iran_level':          0,
        'belarus_russia_axis':         True,  # default-on (structural)
        'nato_perimeter_pressure':     False,
        'lukashenko_succession_watch': False,
        'wagner_active_belarus':       False,
        'china_belarus_anchor':        False,
        'commodity_potash_pressure':   False,
    }

    for r in red_lines_triggered:
        if r['status'] in ('BREACHED', 'APPROACHING'):
            if r['id'] == 'iran_belarus_capability_transfer':
                fingerprints['belarus_iran_active'] = True
                fingerprints['belarus_iran_level']  = r['severity']
            elif r['id'] == 'suwalki_gap_threat_belarus':
                fingerprints['nato_perimeter_pressure'] = True
            elif r['id'] == 'migrant_weaponization_surge':
                fingerprints['nato_perimeter_pressure'] = True
            elif r['id'] == 'lukashenko_succession_crisis':
                fingerprints['lukashenko_succession_watch'] = True
            elif r['id'] == 'wagner_remnant_mobilization':
                fingerprints['wagner_active_belarus'] = True
            elif r['id'] == 'china_strategic_anchor_belarus':
                fingerprints['china_belarus_anchor'] = True

    if commodity_signal and commodity_signal.get('alert') in ('high', 'critical'):
        fingerprints['commodity_potash_pressure'] = True

    return fingerprints


# ============================================================
# MAIN ENTRY
# ============================================================

def interpret_signals(scan_data):
    """
    Main entry point. Called from rhetoric_tracker_belarus.py.
    Returns interpretation dict with canonical top_signals[].
    """
    try:
        red_lines      = _score_red_lines(scan_data)
        green_lines    = _score_green_lines(scan_data)
        diplomatic     = _score_diplomatic_track(scan_data, green_lines)
        commodity_sig  = _fetch_commodity_signal()
        so_what        = _build_so_what(scan_data, red_lines, green_lines,
                                        diplomatic, commodity_sig)
        top_signals    = _build_top_signals(red_lines, green_lines,
                                            diplomatic, commodity_sig,
                                            scan_data)
        fingerprints   = _build_fingerprints(red_lines, commodity_sig)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']
        active_gl   = [g for g in green_lines if g['status'] == 'ACTIVE']

        # Calculate composite escalation modifier
        composite_modifier = diplomatic['modifier']
        if commodity_sig:
            composite_modifier += commodity_sig.get('escalation_modifier', 0)

        return {
            'so_what':             so_what,
            'top_signals':         top_signals,
            'red_lines': {
                'triggered':         red_lines,
                'breached_count':    len(breached),
                'approaching_count': len(approaching),
                'highest_severity':  max((r['severity'] for r in red_lines), default=0),
            },
            'green_lines': {
                'triggered':         green_lines,
                'active_count':      len(active_gl),
                'signaled_count':    len([g for g in green_lines if g['status'] == 'SIGNALED']),
                'diplomatic_score':  diplomatic['score'],
            },
            'diplomatic_track':    diplomatic,
            'commodity_signal':    commodity_sig,
            'cross_theater_fingerprints': fingerprints,
            'composite_modifier':  composite_modifier,
            'interpreter_version': INTERPRETER_VERSION,
            'interpreted_at':      datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f'[Belarus Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what': {
                'scenario':   'Interpreter error',
                'priority':   'normal',
                'assessment': str(e)[:200],
                'breached_count': 0,
                'approaching_count': 0,
                'active_green_count': 0,
            },
            'top_signals':         [],
            'red_lines':           {'triggered': [], 'breached_count': 0,
                                    'approaching_count': 0, 'highest_severity': 0},
            'green_lines':         {'triggered': [], 'active_count': 0,
                                    'signaled_count': 0, 'diplomatic_score': 0},
            'diplomatic_track':    {'score': 0, 'scenario': 'Unknown', 'modifier': 0},
            'commodity_signal':    None,
            'cross_theater_fingerprints': {},
            'composite_modifier':  0,
            'interpreter_version': INTERPRETER_VERSION,
            'error':               str(e)[:200],
        }
