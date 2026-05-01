"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — UKRAINE SIGNAL INTERPRETER
  v1.0.0 (Apr 30 2026)
═══════════════════════════════════════════════════════════════════════

Analytical layer for the Ukraine rhetoric tracker. Reads scan_data
(produced by rhetoric_tracker_ukraine.py), applies red/green-line rules,
detects historical patterns, builds So-What narrative, and emits
canonical top_signals[] for Europe Regional BLUF synthesis.

ANALYTICAL FRAMING:
  Ukraine's rhetoric posture is shaped by four concurrent dynamics:
    1. Frontline / battlefield reality (territorial control, attacks)
    2. Western aid pipeline integrity (US position decisive)
    3. Defense industrial maturation (drone advisor exports unique vector)
    4. Diplomatic / ceasefire prospects
  Plus the cross-cutting commodity vector — wheat, corn, sunflower oil,
  uranium pivot, titanium, steel — Black Sea grain corridor as strategic
  signal node.

ACTOR FRAMEWORK (7 actors):
  - ukrainian_government
  - ukrainian_armed_forces
  - russian_forces_in_ukraine
  - us_government                  (← own actor — aid pipeline decisive)
  - nato_western_support           (Europe + UK + non-US Western)
  - defense_industrial_base        (← includes drone advisor exports
                                      sub-vector for GCC/Israel)
  - occupied_territories_signals

CROSS-THEATER FINGERPRINTS WRITTEN:
  - ukraine_drone_advisor_active  → consumed by ME backend (UAE/Saudi/IL)
  - ukraine_grain_corridor_status → consumed by ME (food security signal)
  - us_aid_continuity             → consumed by Russia + GPI
  - frontline_pressure            → consumed by Russia + GPI

COMMODITY INTEGRATION (Phase 1 light):
  Reads /api/europe/commodity/ukraine and adds ONE band to top_signals.
  Triggers small escalation modifier when alert is high/critical.

USAGE:
  from ukraine_signal_interpreter import interpret_signals
  result = interpret_signals(scan_data)
"""

import requests
from datetime import datetime, timezone

INTERPRETER_VERSION = '1.0.0'

# Europe backend self-call URL (interpreter runs in Europe backend)
COMMODITY_PROXY_URL = 'http://localhost:10000/api/europe/commodity/ukraine'

# ============================================================
# RED LINES
# ============================================================
RED_LINES = [
    {
        'id':       'frontline_collapse',
        'category': 'Battlefield',
        'title':    'Ukrainian Frontline Collapse Indicator',
        'severity': 5,
        'description':
            'Reports of significant breakthrough by Russian forces — '
            'multiple settlement losses in 48-72h, command-and-control '
            'failure, mass retreat patterns, or political signaling of '
            'territorial concession on a major axis (Donbas, Zaporizhzhia, '
            'Kharkiv). Catastrophic for Ukrainian war posture.',
        'triggers_breached': [
            'mass retreat', 'frontline collapse', 'major breakthrough',
            'city falls', 'kupyansk fall', 'pokrovsk fall',
            'kostiantynivka fall', 'breakthrough confirmed',
        ],
        'triggers_approaching': [
            'frontline pressure', 'tactical retreat', 'salient under threat',
            'russian advance', 'positions abandoned',
        ],
    },
    {
        'id':       'us_aid_suspension_total',
        'category': 'Western Support',
        'title':    'US Aid Pipeline Suspension',
        'severity': 5,
        'description':
            'Trump administration formal suspension of military aid to '
            'Ukraine — weapons authorizations halted, funding frozen, '
            'intelligence-sharing curtailed. Existential for Ukrainian '
            'defense capacity.',
        'triggers_breached': [
            'aid suspended ukraine', 'weapons halted ukraine',
            'frozen ukraine funding', 'intelligence cut ukraine',
            'aid cutoff confirmed', 'congressional aid blocked',
        ],
        'triggers_approaching': [
            'aid pause', 'aid review', 'intelligence sharing review',
            'patriot delay', 'aid bill stalled',
        ],
    },
    {
        'id':       'tactical_nuclear_signaling',
        'category': 'Nuclear',
        'title':    'Russian Tactical Nuclear Signaling vs Ukraine',
        'severity': 5,
        'description':
            'Concrete Russian indicators of preparation to use tactical '
            'nuclear weapons against Ukraine — doctrinal statements, '
            'warhead movement, exercise patterns, or Putin-level threats '
            'with specific targeting language.',
        'triggers_breached': [
            'tactical nuclear strike', 'nuclear use ukraine',
            'tactical warhead deployed', 'nuclear posture raised',
        ],
        'triggers_approaching': [
            'nuclear threat ukraine', 'tactical nuclear option',
            'nuclear doctrine ukraine', 'red line nuclear',
        ],
    },
    {
        'id':       'energy_grid_collapse',
        'category': 'Infrastructure',
        'title':    'Energy Grid Catastrophic Failure',
        'severity': 4,
        'description':
            'Sustained Russian strike campaign produces grid collapse with '
            'extended blackouts, heating failure during winter, water/sewage '
            'shutdowns. Triggers humanitarian and refugee surge dynamics.',
        'triggers_breached': [
            'grid collapse', 'blackout extended', 'heating failure',
            'thermal plant destroyed', 'substation strike critical',
        ],
        'triggers_approaching': [
            'energy strikes wave', 'power outage', 'shahed swarm',
            'grid damage major', 'rolling blackouts',
        ],
    },
    {
        'id':       'kyiv_strike_significant',
        'category': 'Strategic Strike',
        'title':    'Significant Strike on Kyiv',
        'severity': 4,
        'description':
            'Major Russian strike against Kyiv with civilian casualties or '
            'significant infrastructure damage — government district, '
            'mass civilian targets, presidential or military command '
            'facilities.',
        'triggers_breached': [
            'kyiv strike major', 'kyiv casualties mass', 'kyiv attack civilian',
            'presidential building hit', 'kyiv government strike',
        ],
        'triggers_approaching': [
            'kyiv attacked', 'kyiv shahed', 'air raid kyiv',
            'kyiv missile', 'air defense kyiv',
        ],
    },
    {
        'id':       'drone_advisor_export_disclosed',
        'category': 'Defense Industry',
        'title':    'Ukrainian Drone Advisor Export Operations Disclosed',
        'severity': 3,
        'description':
            'Public disclosure or expansion of Ukrainian drone advisor / '
            'training operations to GCC partners (UAE, Saudi Arabia, Israel) '
            'or other partners. Unique Ukrainian leverage vector — defense '
            'knowledge as strategic export.',
        'triggers_breached': [
            'ukrainian drone advisors uae', 'ukrainian advisors saudi',
            'ukraine drone training gcc', 'ukrainian drone instructors',
            'ukraine drone export disclosed', 'kyiv drone training abroad',
        ],
        'triggers_approaching': [
            'ukraine drone partnership', 'ukraine defense export',
            'ukrainian drone industry', 'kyiv drone diplomacy',
        ],
    },
    {
        'id':       'grain_corridor_disruption',
        'category': 'Commodity / Strategic',
        'title':    'Black Sea Grain Corridor Disruption',
        'severity': 3,
        'description':
            'Major Russian attack on grain corridor infrastructure (Odesa '
            'ports, ships, insurance regime collapse). Ripples into MENA '
            'food security and global commodity markets.',
        'triggers_breached': [
            'odesa port strike major', 'grain ship hit',
            'grain corridor blocked', 'insurance withdrawal black sea',
            'grain export halted',
        ],
        'triggers_approaching': [
            'odesa attack', 'grain ship threat', 'black sea drone',
            'grain corridor pressure',
        ],
    },
    {
        'id':       'mobilization_crisis_ukraine',
        'category': 'Manpower',
        'title':    'Ukrainian Mobilization Crisis',
        'severity': 3,
        'description':
            'Indicators of severe Ukrainian manpower shortage — political '
            'crisis over conscription, mass evasion, frontline unit collapse '
            'from undermanning, or major mobilization law overhaul.',
        'triggers_breached': [
            'mobilization crisis', 'conscription crisis', 'tcc protests',
            'manpower shortage critical', 'mobilization riots',
        ],
        'triggers_approaching': [
            'mobilization protest', 'tcc tension', 'recruitment shortfall',
            'conscription debate', 'mobilization age lowered',
        ],
    },
    {
        'id':       'occupation_atrocity_disclosure',
        'category': 'Occupied Territories',
        'title':    'Major Atrocity Disclosure in Occupied Territories',
        'severity': 3,
        'description':
            'Disclosure of significant civilian atrocity, mass deportation '
            'event, or filtration camp expansion in Russian-occupied '
            'territories. Drives Western political pressure and ICC dynamics.',
        'triggers_breached': [
            'mass grave found', 'filtration camp disclosed',
            'forced deportation children mass', 'icc warrant new',
            'atrocity site disclosed',
        ],
        'triggers_approaching': [
            'occupation report', 'filtration camp', 'forced russification',
            'children deported', 'mariupol survivors',
        ],
    },
]


# ============================================================
# GREEN LINES
# ============================================================
GREEN_LINES = [
    {
        'id':       'ceasefire_framework_active',
        'category': 'Diplomatic',
        'title':    'Ukraine Ceasefire Framework Active',
        'description':
            'Concrete ceasefire negotiation framework underway — named '
            'envoys, agreed venue, line-of-contact discussions, prisoner '
            'exchange momentum.',
        'triggers_active': [
            'ceasefire framework', 'ceasefire negotiation', 'minsk format revived',
            'istanbul format', 'witkoff zelensky', 'negotiated settlement framework',
        ],
        'triggers_signaled': [
            'ceasefire talks', 'negotiation possibility',
            'diplomatic opening ukraine',
        ],
    },
    {
        'id':       'us_aid_continuity',
        'category': 'Western Support',
        'title':    'US Aid Continuity Confirmed',
        'description':
            'Trump administration confirms aid continuation, weapons '
            'authorization, or new military package. De-risks war posture.',
        'triggers_active': [
            'aid continued ukraine', 'weapons authorized ukraine',
            'patriot delivery', 'atacms approved', 'aid package signed',
        ],
        'triggers_signaled': [
            'aid signal positive', 'trump ukraine aid',
            'congressional support ukraine',
        ],
    },
    {
        'id':       'european_aid_surge',
        'category': 'Western Support',
        'title':    'European Aid Surge / Backfill',
        'description':
            'Major European aid surge (Germany, UK, France, EU) potentially '
            'backfilling US gaps. Signals durable European commitment.',
        'triggers_active': [
            'germany aid package', 'uk weapons ukraine', 'eu peace facility',
            'european aid surge', 'rheinmetall expansion',
        ],
        'triggers_signaled': [
            'european commitment ukraine', 'eu defense support',
        ],
    },
    {
        'id':       'prisoner_exchange_momentum',
        'category': 'Humanitarian',
        'title':    'Prisoner Exchange Momentum',
        'description':
            'Major prisoner exchange completed or scheduled — particularly '
            'Mariupol defenders, journalists, or civilian hostages.',
        'triggers_active': [
            'prisoner exchange completed', 'pow swap', 'azov defenders home',
            'civilian prisoner returned', 'mass exchange',
        ],
        'triggers_signaled': [
            'prisoner exchange planned', 'pow negotiation',
        ],
    },
    {
        'id':       'reconstruction_signaling',
        'category': 'Recovery',
        'title':    'Reconstruction Commitment Signaling',
        'description':
            'Concrete reconstruction commitments — Lugano follow-on, EU '
            'frozen-asset deployment, IMF Ukraine facility expansion.',
        'triggers_active': [
            'frozen assets deployed', 'reconstruction package agreed',
            'ukraine recovery fund', 'eu reconstruction confirmed',
        ],
        'triggers_signaled': [
            'reconstruction conference', 'recovery framework',
            'lugano follow on',
        ],
    },
]


# ============================================================
# KEYWORD MATCHING
# ============================================================

def _check_keywords(scan_data, keywords):
    """Match keywords against scan_data article corpus + signals."""
    if not keywords:
        return 0
    corpus_parts = []
    for key in ('articles_en', 'articles_uk', 'articles_ru', 'articles_pl'):
        for art in (scan_data.get(key) or []):
            corpus_parts.append((art.get('title') or '').lower())
            corpus_parts.append((art.get('description') or '').lower())
            corpus_parts.append((art.get('summary') or '').lower())
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


# ============================================================
# RED / GREEN LINE SCORING
# ============================================================

def _score_red_lines(scan_data):
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
            'id': rl['id'], 'category': rl['category'], 'title': rl['title'],
            'severity': rl['severity'], 'description': rl['description'],
            'status': status,
            'breached_hits': breached_hits, 'approaching_hits': approaching_hits,
        })
    return triggered


def _score_green_lines(scan_data):
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
            'id': gl['id'], 'category': gl['category'], 'title': gl['title'],
            'description': gl['description'], 'status': status,
            'active_hits': active_hits, 'signaled_hits': signaled_hits,
        })
    return triggered


# ============================================================
# COMMODITY INTEGRATION
# ============================================================

def _fetch_commodity_signal():
    """Reads from Europe commodity proxy. Returns analytical band + modifier."""
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

        modifier_map = {'normal': 0, 'elevated': 1, 'high': 3, 'critical': 5}
        modifier = modifier_map.get(alert, 0)

        if commodities:
            top_c = max(commodities, key=lambda c: c.get('signal_count', 0) or 0)
            top_name = (top_c.get('name') or top_c.get('commodity') or 'commodity').upper()
            top_sigs = top_c.get('signal_count', 0)
            short = f"Commodity Pressure: {alert.upper()} — {top_name} ({top_sigs} signals)"
        else:
            short = f"Commodity Pressure: {alert.upper()}"

        long_parts = [
            "Pre-war Ukraine: world's #1 sunflower oil exporter, top-3 corn, top-5 wheat.",
            "Black Sea grain corridor disruption ripples into MENA food security signals.",
            "Defense industrial base — including drone advisor exports — is unique strategic vector.",
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
            'source_link': '/commodities.html#wheat',
            'pressure':    pressure,
        }
        return {
            'band':                band,
            'escalation_modifier': modifier,
            'pressure':            pressure,
            'alert':               alert,
        }
    except Exception as e:
        print(f'[Ukraine Interpreter] Commodity fetch failed: {str(e)[:120]}')
        return None


# ============================================================
# DIPLOMATIC TRACK
# ============================================================

CEASEFIRE_TRIGGERS = [
    'ceasefire negotiation', 'witkoff zelensky', 'istanbul format',
    'minsk format revived', 'envoy ukraine russia',
    'переговоры украина', 'мирный процесс',
]


def _score_diplomatic_track(scan_data, green_lines_triggered):
    matches = _check_keywords(scan_data, CEASEFIRE_TRIGGERS)
    active_gls = [g for g in green_lines_triggered if g['status'] == 'ACTIVE']
    diplomatic_score = matches + (len(active_gls) * 2)

    if diplomatic_score >= 6:
        scenario = 'Active Ceasefire Track'
        modifier = -10
    elif diplomatic_score >= 3:
        scenario = 'Tentative Diplomatic Signals'
        modifier = -5
    elif diplomatic_score >= 1:
        scenario = 'Limited De-escalation Indicators'
        modifier = -2
    else:
        scenario = 'No Active Track'
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
    breached    = [r for r in red_lines_triggered if r['status'] == 'BREACHED']
    approaching = [r for r in red_lines_triggered if r['status'] == 'APPROACHING']
    active_gl   = [g for g in green_lines_triggered if g['status'] == 'ACTIVE']

    highest_severity = max((r['severity'] for r in breached), default=0)

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

    assessment_parts = []

    if breached:
        breached_titles = ', '.join(r['title'] for r in breached[:3])
        assessment_parts.append(f"Red line(s) breached: {breached_titles}.")

    if approaching:
        approaching_titles = ', '.join(r['title'] for r in approaching[:3])
        assessment_parts.append(f"Approaching threshold: {approaching_titles}.")

    if diplomatic['score'] > 0:
        assessment_parts.append(
            f"Diplomatic track: {diplomatic['scenario'].lower()} (score {diplomatic['score']})."
        )

    if active_gl:
        gl_titles = ', '.join(g['title'] for g in active_gl[:2])
        assessment_parts.append(f"Active de-escalation indicators: {gl_titles}.")

    if commodity_signal and commodity_signal.get('alert') != 'normal':
        assessment_parts.append(
            f"Commodity pressure: {commodity_signal['alert']} "
            f"(grain corridor + defense export dynamics)."
        )

    if not assessment_parts:
        assessment_parts.append(
            "No active red lines. Monitoring baseline frontline pressure, "
            "Western aid continuity, defense industrial signaling, and "
            "diplomatic track."
        )

    return {
        'scenario':            scenario,
        'priority':            priority,
        'assessment':          ' '.join(assessment_parts),
        'breached_count':      len(breached),
        'approaching_count':   len(approaching),
        'active_green_count':  len(active_gl),
    }


# ============================================================
# TOP SIGNALS BUILDER
# ============================================================

def _build_top_signals(red_lines_triggered, green_lines_triggered,
                       diplomatic, commodity_signal, scan_data):
    signals = []
    SEVERITY_TO_LEVEL = {5: 'critical', 4: 'high', 3: 'elevated',
                         2: 'normal', 1: 'normal'}

    breached = [r for r in red_lines_triggered if r['status'] == 'BREACHED']
    breached.sort(key=lambda r: -r['severity'])
    for r in breached[:3]:
        signals.append({
            'category':    r['category'].lower().replace(' ', '_').replace('/', '_'),
            'level':       SEVERITY_TO_LEVEL.get(r['severity'], 'normal'),
            'short_text':  f"BREACHED: {r['title']}",
            'long_text':   r['description'],
            'icon':        '🚨',
            'source_link': f"/rhetoric-ukraine.html#{r['id']}",
        })

    approaching = [r for r in red_lines_triggered if r['status'] == 'APPROACHING']
    approaching.sort(key=lambda r: -r['severity'])
    for r in approaching[:2]:
        signals.append({
            'category':    r['category'].lower().replace(' ', '_').replace('/', '_'),
            'level':       'elevated',
            'short_text':  f"Approaching: {r['title']}",
            'long_text':   r['description'],
            'icon':        '⚠️',
            'source_link': f"/rhetoric-ukraine.html#{r['id']}",
        })

    active_gl = [g for g in green_lines_triggered if g['status'] == 'ACTIVE']
    for g in active_gl[:2]:
        signals.append({
            'category':    'diplomatic',
            'level':       'normal',
            'short_text':  f"De-escalation: {g['title']}",
            'long_text':   g['description'],
            'icon':        '🟢',
            'source_link': f"/rhetoric-ukraine.html#{g['id']}",
        })

    if commodity_signal and commodity_signal.get('band'):
        signals.append(commodity_signal['band'])

    if diplomatic['score'] >= 3:
        signals.append({
            'category':    'diplomatic',
            'level':       'normal',
            'short_text':  f"Diplomatic Track: {diplomatic['scenario']}",
            'long_text':   f"Diplomatic score: {diplomatic['score']}. "
                           f"Active green lines: {diplomatic['active_green_lines_count']}.",
            'icon':        '🤝',
            'source_link': '/rhetoric-ukraine.html#diplomatic',
        })

    return signals[:7]


# ============================================================
# CROSS-THEATER FINGERPRINTS
# ============================================================

def _build_fingerprints(red_lines_triggered, commodity_signal, scan_data):
    """
    Fingerprints written for downstream tracker consumption.
    """
    fingerprints = {
        'ukraine_drone_advisor_active':    False,
        'ukraine_grain_corridor_status':   'open',  # 'open'/'pressured'/'disrupted'
        'us_aid_continuity':               True,    # default-on, flips on suspension red line
        'frontline_pressure':              'normal', # 'normal'/'elevated'/'critical'
        'kyiv_under_strike':               False,
        'mobilization_crisis_active':      False,
        'energy_grid_pressure':            False,
    }

    for r in red_lines_triggered:
        if r['status'] in ('BREACHED', 'APPROACHING'):
            if r['id'] == 'drone_advisor_export_disclosed':
                fingerprints['ukraine_drone_advisor_active'] = True
            elif r['id'] == 'grain_corridor_disruption':
                fingerprints['ukraine_grain_corridor_status'] = (
                    'disrupted' if r['status'] == 'BREACHED' else 'pressured'
                )
            elif r['id'] == 'us_aid_suspension_total':
                if r['status'] == 'BREACHED':
                    fingerprints['us_aid_continuity'] = False
            elif r['id'] == 'frontline_collapse':
                fingerprints['frontline_pressure'] = (
                    'critical' if r['status'] == 'BREACHED' else 'elevated'
                )
            elif r['id'] == 'kyiv_strike_significant':
                fingerprints['kyiv_under_strike'] = True
            elif r['id'] == 'mobilization_crisis_ukraine':
                fingerprints['mobilization_crisis_active'] = True
            elif r['id'] == 'energy_grid_collapse':
                fingerprints['energy_grid_pressure'] = True

    return fingerprints


# ============================================================
# MAIN ENTRY
# ============================================================

def interpret_signals(scan_data):
    """
    Main entry point. Called from rhetoric_tracker_ukraine.py.
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
                                            diplomatic, commodity_sig, scan_data)
        fingerprints   = _build_fingerprints(red_lines, commodity_sig, scan_data)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']
        active_gl   = [g for g in green_lines if g['status'] == 'ACTIVE']

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
            'diplomatic_track':           diplomatic,
            'commodity_signal':           commodity_sig,
            'cross_theater_fingerprints': fingerprints,
            'composite_modifier':         composite_modifier,
            'interpreter_version':        INTERPRETER_VERSION,
            'interpreted_at':             datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f'[Ukraine Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what': {
                'scenario':           'Interpreter error',
                'priority':           'normal',
                'assessment':         str(e)[:200],
                'breached_count':     0,
                'approaching_count':  0,
                'active_green_count': 0,
            },
            'top_signals':                [],
            'red_lines':                  {'triggered': [], 'breached_count': 0,
                                           'approaching_count': 0, 'highest_severity': 0},
            'green_lines':                {'triggered': [], 'active_count': 0,
                                           'signaled_count': 0, 'diplomatic_score': 0},
            'diplomatic_track':           {'score': 0, 'scenario': 'Unknown', 'modifier': 0},
            'commodity_signal':           None,
            'cross_theater_fingerprints': {},
            'composite_modifier':         0,
            'interpreter_version':        INTERPRETER_VERSION,
            'error':                      str(e)[:200],
        }
