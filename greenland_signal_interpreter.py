"""
greenland_signal_interpreter.py
Asifah Analytics -- Europe Backend Module
v1.0.0

Signal interpretation engine for the Greenland Sovereignty Rhetoric Tracker.

Greenland's analytical frame is fundamentally three-question:

  1. Is the U.S. escalating from rhetoric to coercion to unilateral action?
     How far is Washington actually willing to go -- and what's the trigger?

  2. Is Denmark/NATO holding the line -- or is alliance cohesion cracking
     under sustained U.S. pressure?

  3. Is Russia exploiting the friction to weaken NATO, establish Arctic
     access, or position Northern Fleet assets that threaten the US
     East Coast and Caribbean approach corridors?

Key contextual factors baked in:
  - Pituffik Space Base (formerly Thule AFB) is the US military's
    northernmost installation -- NORAD missile warning, space surveillance
  - Greenland sits in the polar flight corridor Russia-to-North-America
  - GIUK Gap (Greenland-Iceland-UK) is NATO's primary anti-submarine
    chokepoint for tracking Russian SSBN approaches to US East Coast
  - Russia Northern Fleet SSBNs (nuclear-armed submarines) patrol
    routes through GIUK -- Greenland access = US submarine detection
  - Northwest Passage increasingly navigable -- Arctic shipping stakes
  - ~56,000 Greenlanders (majority Inuit) have broad self-rule;
    paradox: US pressure is strengthening independence movement
  - DKK 3.9B (~$560M) annual Danish subsidy is the economic binding
    constraint on independence
  - Trump rhetoric has shifted from "interest" to "necessity" framing --
    qualitative escalation signal

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS
# ============================================================
RED_LINES = [

    # ── Category A: US escalation triggers ─────────────────
    {
        'id':       'us_unilateral_action',
        'label':    'U.S. Takes Unilateral Action re: Greenland',
        'detail':   'US deploys forces, imposes sanctions on Denmark, or takes formal unilateral steps '
                    'toward Greenland acquisition without Danish/Greenlandic consent',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🦅',
        'category': 'us_escalation',
        'source':   'International law -- unilateral acquisition of allied territory triggers '
                    'Article 5 ambiguity and NATO cohesion crisis',
    },
    {
        'id':       'pituffik_access_demand',
        'label':    'US Issues Formal Pituffik/Basing Ultimatum',
        'detail':   'Washington formally demands expanded Pituffik/Thule access or new basing rights '
                    'under threat of economic or diplomatic consequences',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🛡️',
        'category': 'us_escalation',
        'source':   'Pituffik Space Base is the US military\'s northernmost installation -- '
                    'any basing ultimatum reframes the relationship from allied to coercive',
    },
    {
        'id':       'nato_article5_invocation',
        'label':    'NATO Article 5 Language Invoked re: Greenland',
        'detail':   'Denmark or NATO leadership explicitly invokes Article 5 collective defense '
                    'in context of US pressure on Greenland',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🛡️',
        'category': 'alliance_fracture',
        'source':   'Article 5 invocation against a NATO member would be unprecedented -- '
                    'alliance-ending signal; redefines transatlantic security architecture',
    },
    {
        'id':       'russia_northern_fleet_surge',
        'label':    'Russian Northern Fleet Surge / SSBN Deployment Signal',
        'detail':   'Credible intelligence or reporting of Northern Fleet surge activity, '
                    'SSBN patrols through GIUK Gap, or Russian Arctic basing expansion '
                    'timed to US-Greenland friction',
        'severity': 3,
        'color':    '#ef4444',
        'icon':     '🐻',
        'category': 'russia_opportunism',
        'source':   'GIUK Gap is NATO\'s primary anti-submarine chokepoint -- '
                    'Russian SSBN activity during US-NATO friction is a deliberate exploitation signal',
    },
    {
        'id':       'us_economic_coercion_denmark',
        'label':    'U.S. Imposes Economic Pressure on Denmark',
        'detail':   'US imposes tariffs, sanctions, aid cuts, or formal economic leverage '
                    'explicitly linked to Greenland policy',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '💰',
        'category': 'us_escalation',
        'source':   'Economic coercion of an ally marks qualitative escalation from rhetoric '
                    'to operational pressure -- historically precedes further escalation',
    },
    {
        'id':       'greenland_formal_independence_vote',
        'label':    'Greenland Calls Formal Independence Referendum',
        'detail':   'Naalakkersuisut or Inatsisartut formally initiates independence referendum '
                    'process -- potentially accelerated by US pressure',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🧊',
        'category': 'sovereignty_signal',
        'source':   'Paradox signal: US pressure may accelerate Greenlandic independence drive '
                    '-- independence would complicate US acquisition far more than Danish sovereignty',
    },
    {
        'id':       'denmark_military_deployment_arctic',
        'label':    'Denmark Deploys Military Assets to Greenland',
        'detail':   'Denmark sends frigates, aircraft, or ground forces to Greenland in direct '
                    'response to US pressure -- sovereignty enforcement signal',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🛳️',
        'category': 'sovereignty_signal',
        'source':   'Danish military deployment to Greenland signals Copenhagen treating '
                    'US pressure as a sovereignty threat requiring kinetic posture',
    },
    {
        'id':       'russia_wedge_diplomacy',
        'label':    'Russia Offers Greenland "Alternative" to US Pressure',
        'detail':   'Kremlin offers Greenland economic, security, or diplomatic alternatives '
                    'to US/Danish arrangements -- wedge diplomacy signal',
        'severity': 2,
        'color':    '#f59e0b',
        'icon':     '🐻',
        'category': 'russia_opportunism',
        'source':   'Russia has historical pattern of exploiting NATO internal friction '
                    'with wedge offers (Ukraine, Hungary, Turkey); Arctic version would be novel',
    },
    {
        'id':       'nato_ally_public_rebuke_us',
        'label':    'Multiple NATO Allies Publicly Rebuke US on Greenland',
        'detail':   'Two or more NATO allies (beyond Denmark) formally condemn US Greenland '
                    'rhetoric or actions in public diplomatic statements',
        'severity': 2,
        'color':    '#f59e0b',
        'icon':     '🌐',
        'category': 'alliance_fracture',
        'source':   'Multi-ally rebuke signals alliance-wide cohesion crisis -- '
                    'not just a bilateral Denmark-US dispute',
    },
    {
        'id':       'greenland_us_dialogue',
        'label':    'Greenland/Denmark Opens Direct Dialogue with Washington',
        'detail':   'Naalakkersuisut or Danish government opens formal negotiations with '
                    'US administration on Greenland status, security, or mineral rights',
        'severity': 1,
        'color':    '#10b981',
        'icon':     '🤝',
        'category': 'deescalation_signal',
        'source':   'Dialogue signal -- could indicate negotiated resolution or Danish '
                    'willingness to accommodate some US security interests',
    },
]


# ============================================================
# HISTORICAL PRECEDENTS
# ============================================================
HISTORICAL_PRECEDENTS = [
    {
        'id':          'us_greenland_purchase_1946',
        'label':       'US Attempt to Purchase Greenland (1946)',
        'description': 'Truman administration offered Denmark $100M for Greenland; Denmark refused',
        'source':      'US State Dept archives; NARA; Danish Foreign Ministry records',
        'signals': {
            'us_pressure_min':  2,
            'denmark_level_min': 2,
            'nato_invoked':     False,
        },
        'outcome':     'Denmark refused sale. US retained Thule basing rights under 1951 Defense Agreement. '
                       'Bilateral relationship survived -- acquisition ambition did not.',
        'window_hours': 0,
        'confidence':   'High',
    },
    {
        'id':          'alaska_purchase_1867',
        'label':       'Alaska Purchase (1867)',
        'description': 'US purchased Alaska from Russia for $7.2M -- "Seward\'s Folly" became strategic cornerstone',
        'source':      'US State Dept; Library of Congress; USGS Strategic Minerals Report 2023',
        'signals': {
            'us_pressure_min':   3,
            'seller_willing':    True,
            'nato_invoked':      False,
        },
        'outcome':     'Completed purchase from willing seller (Russia). No analog to Greenland -- '
                       'Denmark is a NATO ally with democratic self-determination protections. '
                       'Historical parallel used by Trump; analytically weak.',
        'window_hours': 0,
        'confidence':   'Low',
    },
    {
        'id':          'svalbard_treaty_1920',
        'label':       'Svalbard Treaty (1920) -- Arctic Sovereignty Negotiated',
        'description': 'Norway given sovereignty over Svalbard; other nations retain economic rights',
        'source':      'Treaty of Svalbard 1920; Norwegian Polar Institute; IISS Arctic Security 2023',
        'signals': {
            'us_pressure_min':   1,
            'multilateral':      True,
            'nato_invoked':      False,
        },
        'outcome':     'Sovereignty preserved with negotiated access rights. '
                       'Template: US could seek negotiated access rights to Pituffik/Arctic '
                       'without requiring full acquisition -- diplomatic off-ramp.',
        'window_hours': 0,
        'confidence':   'Medium',
    },
    {
        'id':          'panama_canal_pressure_2024',
        'label':       'Trump Panama Canal Rhetoric (2024-2025)',
        'description': 'Trump demanded US retake Panama Canal; Panama rejected; no action followed',
        'source':      'Reuters; AP; Panama MFA statements; US State Dept 2025',
        'signals': {
            'us_pressure_min':   2,
            'nato_invoked':      False,
            'sovereignty_defense_min': 2,
        },
        'outcome':     'Rhetoric at L2-3; no operational action. Pattern: Trump maximum-pressure '
                       'rhetoric does not always escalate to action. Watch for operational signals '
                       '(troop movements, formal ultimatums) as escalation threshold.',
        'window_hours': 168,
        'confidence':   'High',
    },
    {
        'id':          'russia_ukraine_crimea_2014',
        'label':       'Russia Crimea Annexation (2014) -- Coercive Acquisition Template',
        'description': 'Russia annexed Crimea after military deployment; framed as referendum',
        'source':      'ICJ; UN General Assembly Resolution 68/262; ISW; IISS',
        'signals': {
            'us_pressure_min':       4,
            'unilateral_action':     True,
            'sovereignty_defense_min': 1,
        },
        'outcome':     'Annexation completed by force. Formal "referendum" held under occupation. '
                       'NOT a US analog -- included to calibrate severity of coercive acquisition signals. '
                       'If US reaches L4+ with unilateral action signals, this precedent becomes relevant '
                       'for modeling alliance response.',
        'window_hours': 72,
        'confidence':   'High',
    },
]


# ============================================================
# CORE SCORING FUNCTIONS
# ============================================================

def _score_red_lines(scan_data):
    """Evaluate Greenland signal state against defined red lines."""
    actors = scan_data.get('actors', {})

    us_level       = actors.get('us_pressure',     {}).get('level',
                     actors.get('us_pressure',     {}).get('escalation_level', 0))
    greenland_level = actors.get('greenland_inuit', {}).get('level',
                      actors.get('greenland_inuit', {}).get('escalation_level', 0))
    denmark_level  = actors.get('denmark_nato',    {}).get('level',
                     actors.get('denmark_nato',    {}).get('escalation_level', 0))
    russia_level   = actors.get('russia_arctic',   {}).get('level',
                     actors.get('russia_arctic',   {}).get('escalation_level', 0))

    theatre_score  = scan_data.get('theatre_score', 0)
    russia_opportunism = scan_data.get('russia_opportunism', False)

    # Scan article headlines for specific trigger phrases
    def _scan_articles(actor_ids, keywords):
        for aid in actor_ids:
            actor_data = actors.get(aid, {})
            # Support both 'top_articles' (interpreter format) and direct
            for art in actor_data.get('top_articles', []):
                title = art.get('title', '').lower()
                if any(kw in title for kw in keywords):
                    return True
        return False

    # Signal detection
    unilateral_signal = _scan_articles(
        ['us_pressure'],
        ['unilateral', 'us troops greenland', 'us forces greenland',
         'military action greenland', 'seize greenland', 'take greenland by force',
         'sanctions denmark', 'us sanctions', 'tariff denmark greenland']
    )
    pituffik_ultimatum = _scan_articles(
        ['us_pressure'],
        ['pituffik', 'thule', 'basing rights', 'base access', 'military base greenland',
         'expand base', 'us base demand', 'pentagon greenland ultimatum']
    )
    article5_signal = _scan_articles(
        ['denmark_nato'],
        ['article 5', 'collective defense', 'nato defense', 'treaty obligation',
         'nato ally greenland', 'invoke article', 'alliance commitment greenland']
    )
    russia_fleet_signal = _scan_articles(
        ['russia_arctic'],
        ['northern fleet', 'ssbn', 'submarine patrol', 'naval exercise arctic',
         'severomorsk', 'borei', 'arctic submarine', 'giuk', 'arctic naval',
         'russian warship arctic', 'northern fleet deployment']
    )
    economic_coercion = _scan_articles(
        ['us_pressure'],
        ['tariff denmark', 'sanction denmark', 'aid cut greenland', 'economic pressure denmark',
         'leverage greenland', 'denmark tariff', 'us economic greenland']
    )
    referendum_signal = _scan_articles(
        ['greenland_inuit'],
        ['referendum', 'independence vote', 'greenland vote', 'self-determination vote',
         'greenland poll independence', 'inatsisartut vote', 'independence referendum']
    )
    denmark_military = _scan_articles(
        ['denmark_nato'],
        ['danish frigate', 'danish warship', 'danish navy', 'danish troops',
         'danish military greenland', 'denmark deploys', 'arktisk kommando',
         'danish patrol', 'sirius patrol', 'danish p-8']
    )
    russia_wedge = _scan_articles(
        ['russia_arctic'],
        ['russia offer', 'russia greenland deal', 'kremlin offer', 'russia alternative',
         'russia greenland cooperation', 'moscow greenland', 'russia greenland partner']
    )
    ally_rebuke = _scan_articles(
        ['denmark_nato'],
        ['france condemns', 'uk condemns', 'germany condemns', 'europe condemns',
         'allies condemn', 'nato condemns', 'europe rejects us', 'allies reject',
         'european response trump greenland']
    )
    dialogue_signal = _scan_articles(
        ['greenland_inuit', 'denmark_nato', 'us_pressure'],
        ['negotiations', 'dialogue', 'talks', 'diplomatic solution',
         'mineral rights deal', 'basing agreement', 'security deal greenland',
         'greenland us agreement', 'negotiated access']
    )

    triggered = []

    # ── US unilateral action ──
    if unilateral_signal or us_level >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'us_unilateral_action'),
            'status':  'BREACHED' if (unilateral_signal and us_level >= 4) else 'APPROACHING',
            'trigger': f'US pressure L{us_level} -- '
                       f'{"unilateral action language detected" if unilateral_signal else "approaching unilateral threshold"}',
        })

    # ── Pituffik/basing ultimatum ──
    if pituffik_ultimatum and us_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'pituffik_access_demand'),
            'status':  'BREACHED' if us_level >= 4 else 'APPROACHING',
            'trigger': f'Pituffik/basing language + US pressure L{us_level} -- '
                       f'NORAD/Arctic basing rights in play',
        })

    # ── NATO Article 5 invocation ──
    if article5_signal or (denmark_level >= 4 and us_level >= 4):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'nato_article5_invocation'),
            'status':  'BREACHED' if article5_signal else 'APPROACHING',
            'trigger': f'Article 5 / collective defense language detected -- '
                       f'Denmark L{denmark_level}, US pressure L{us_level}',
        })

    # ── Russia Northern Fleet surge ──
    if russia_fleet_signal or russia_level >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'russia_northern_fleet_surge'),
            'status':  'BREACHED' if (russia_fleet_signal and russia_level >= 4) else 'APPROACHING',
            'trigger': f'Russia Arctic L{russia_level} -- '
                       f'{"Northern Fleet/SSBN language detected" if russia_fleet_signal else "elevated Arctic posture signals"}. '
                       f'GIUK Gap watch active.',
        })

    # ── US economic coercion of Denmark ──
    if economic_coercion and us_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'us_economic_coercion_denmark'),
            'status':  'APPROACHING',
            'trigger': f'Economic coercion language (tariffs/sanctions/leverage) + US L{us_level} -- '
                       f'rhetoric escalating to operational pressure',
        })

    # ── Greenland independence referendum ──
    if referendum_signal or greenland_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'greenland_formal_independence_vote'),
            'status':  'BREACHED' if referendum_signal else 'APPROACHING',
            'trigger': f'Greenland/Inuit L{greenland_level} -- '
                       f'{"referendum language detected -- independence paradox signal" if referendum_signal else "sovereignty defense escalating"}',
        })

    # ── Denmark military deployment ──
    if denmark_military and denmark_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'denmark_military_deployment_arctic'),
            'status':  'APPROACHING',
            'trigger': f'Danish military Arctic deployment language + Denmark/NATO L{denmark_level} -- '
                       f'Copenhagen treating pressure as sovereignty threat',
        })

    # ── Russia wedge diplomacy ──
    if russia_wedge or (russia_opportunism and russia_level >= 3):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'russia_wedge_diplomacy'),
            'status':  'APPROACHING',
            'trigger': f'Russia Arctic L{russia_level} -- '
                       f'{"wedge diplomacy language detected" if russia_wedge else "opportunism signals at elevated level"}',
        })

    # ── Multi-ally rebuke ──
    if ally_rebuke and denmark_level >= 2:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'nato_ally_public_rebuke_us'),
            'status':  'APPROACHING',
            'trigger': f'Multiple NATO ally condemnation language + Denmark/NATO L{denmark_level} -- '
                       f'alliance-wide cohesion signal',
        })

    # ── De-escalation: dialogue opening ──
    if dialogue_signal and us_level <= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'greenland_us_dialogue'),
            'status':  'APPROACHING',
            'trigger': f'Negotiation/dialogue language detected -- '
                       f'potential off-ramp from coercive track',
        })

    # Sort: severity desc, deescalation last
    triggered.sort(key=lambda x: (
        -x['severity'],
        0 if x['category'] != 'deescalation_signal' else 1
    ))
    return triggered


# ============================================================
# HISTORICAL PATTERN MATCHING
# ============================================================

def _match_historical(scan_data):
    """Match Greenland signal state against historical precedents."""
    actors = scan_data.get('actors', {})

    us_level       = actors.get('us_pressure',     {}).get('level',
                     actors.get('us_pressure',     {}).get('escalation_level', 0))
    denmark_level  = actors.get('denmark_nato',    {}).get('level',
                     actors.get('denmark_nato',    {}).get('escalation_level', 0))
    greenland_level = actors.get('greenland_inuit', {}).get('level',
                      actors.get('greenland_inuit', {}).get('escalation_level', 0))

    russia_opportunism = scan_data.get('russia_opportunism', False)
    theatre_score  = scan_data.get('theatre_score', 0)

    # Derived booleans for matching
    nato_invoked      = denmark_level >= 4
    unilateral_action = us_level >= 4
    sovereignty_defense = max(denmark_level, greenland_level)
    seller_willing    = False  # Greenland has not signaled willingness to be sold
    multilateral      = denmark_level >= 2  # NATO/EU engagement = multilateral frame

    matches = []

    for precedent in HISTORICAL_PRECEDENTS:
        sigs = precedent['signals']
        score = 0
        max_score = 0
        matched_signals = []
        missed_signals  = []

        def check(condition, label, weight=1):
            nonlocal score, max_score
            max_score += weight
            if condition:
                score += weight
                matched_signals.append(label)
            else:
                missed_signals.append(label)

        if 'us_pressure_min' in sigs:
            check(
                us_level >= sigs['us_pressure_min'],
                f'US pressure L{us_level} >= L{sigs["us_pressure_min"]}',
                weight=3
            )
        if 'sovereignty_defense_min' in sigs:
            check(
                sovereignty_defense >= sigs['sovereignty_defense_min'],
                f'Sovereignty defense L{sovereignty_defense} >= L{sigs["sovereignty_defense_min"]}',
                weight=2
            )
        if 'nato_invoked' in sigs:
            check(
                nato_invoked == sigs['nato_invoked'],
                f'NATO invoked: {nato_invoked}',
                weight=2
            )
        if 'unilateral_action' in sigs:
            check(
                unilateral_action == sigs['unilateral_action'],
                f'Unilateral action: {unilateral_action}',
                weight=3
            )
        if 'seller_willing' in sigs:
            check(
                seller_willing == sigs['seller_willing'],
                f'Greenland willing to negotiate: {seller_willing}',
                weight=2
            )
        if 'multilateral' in sigs:
            check(
                multilateral == sigs['multilateral'],
                f'Multilateral engagement: {multilateral}',
                weight=1
            )

        if max_score == 0:
            continue

        similarity = round((score / max_score) * 100)
        if similarity >= 50:
            matches.append({
                'id':              precedent['id'],
                'label':           precedent['label'],
                'description':     precedent['description'],
                'source':          precedent['source'],
                'outcome':         precedent['outcome'],
                'window_hours':    precedent['window_hours'],
                'confidence':      precedent['confidence'],
                'similarity':      similarity,
                'matched_signals': matched_signals,
                'missed_signals':  missed_signals,
            })

    matches.sort(key=lambda x: x['similarity'], reverse=True)
    return matches[:3]


# ============================================================
# SO WHAT BUILDER
# ============================================================

def _build_so_what(scan_data, red_lines_triggered, historical_matches):
    """
    Generate Greenland strategic assessment.
    Frame: Three-question analysis --
      1. US escalation trajectory
      2. Alliance cohesion under pressure
      3. Russian Arctic opportunism and GIUK/SSBN implications
    """
    actors = scan_data.get('actors', {})

    us_level        = actors.get('us_pressure',     {}).get('level',
                      actors.get('us_pressure',     {}).get('escalation_level', 0))
    greenland_level = actors.get('greenland_inuit', {}).get('level',
                      actors.get('greenland_inuit', {}).get('escalation_level', 0))
    denmark_level   = actors.get('denmark_nato',    {}).get('level',
                      actors.get('denmark_nato',    {}).get('escalation_level', 0))
    russia_level    = actors.get('russia_arctic',   {}).get('level',
                      actors.get('russia_arctic',   {}).get('escalation_level', 0))

    theatre_score      = scan_data.get('theatre_score', 0)
    russia_opportunism = scan_data.get('russia_opportunism', False)
    convergence_signal = scan_data.get('convergence_signal', '')
    delta              = scan_data.get('delta', {}) or {}
    delta_dir          = delta.get('direction', 'stable')
    score_change       = delta.get('score_change', 0)

    breached_count   = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    approaching_count = sum(1 for r in red_lines_triggered if r['status'] == 'APPROACHING')
    top_match = historical_matches[0] if historical_matches else None

    # ── Derived signals ──
    sovereignty_hardening = greenland_level >= 3 or denmark_level >= 3
    nato_cohesion_risk    = us_level >= 3 and denmark_level >= 2
    russia_exploiting     = russia_opportunism or russia_level >= 3
    alliance_fracture_risk = us_level >= 4 and denmark_level >= 3

    # ── Scenario label ──
    if us_level >= 4 and denmark_level >= 4:
        scenario       = 'CONFRONTATION -- U.S. vs. NATO Ally, Alliance at Risk'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif us_level >= 4 or (us_level >= 3 and russia_exploiting):
        scenario       = 'CRISIS -- Coercive Pressure + Russian Opportunism Active'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif us_level >= 3 and sovereignty_hardening:
        scenario       = 'ELEVATED -- Active Coercion, Sovereignty Defense Engaged'
        scenario_color = '#f59e0b'
        scenario_icon  = '🟡'
    elif us_level >= 2 and (denmark_level >= 2 or russia_level >= 2):
        scenario       = 'PRESSURE -- U.S. Coercion Active, Responses Forming'
        scenario_color = '#3b82f6'
        scenario_icon  = '🔵'
    elif us_level >= 1:
        scenario       = 'MONITORING -- U.S. Rhetoric, Below Coercion Threshold'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'
    else:
        scenario       = 'BASELINE -- Diplomatic Noise, No Active Pressure'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'

    # ── Situation ──
    situation_parts = []

    if us_level >= 1:
        situation_parts.append(
            f'U.S. pressure on Greenland at L{us_level} -- '
            f'{"operational coercion signals beyond rhetoric" if us_level >= 3 else "rhetorical pressure, no operational signals yet"}. '
            f'Pituffik Space Base (formerly Thule AFB) and Arctic mineral access are the '
            f'primary stated US strategic interests.'
        )

    if sovereignty_hardening:
        situation_parts.append(
            f'Sovereignty defense hardening: Greenland/Inuit at L{greenland_level}, '
            f'Denmark/NATO at L{denmark_level}. '
            f'Key dynamic: U.S. pressure is paradoxically accelerating Greenlandic independence '
            f'sentiment -- Greenlanders want freedom from Copenhagen, not a new flag from Washington.'
        )

    if nato_cohesion_risk:
        situation_parts.append(
            f'NATO alliance cohesion at risk: U.S. at L{us_level} vs. Danish ally at L{denmark_level}. '
            f'Every European capital is watching this as a signal of future U.S. reliability under Article 5. '
            f'Alliance credibility is the broader strategic stake beyond Greenland itself.'
        )

    if russia_exploiting:
        situation_parts.append(
            f'Russia Arctic opportunism at L{russia_level} -- '
            f'Kremlin is exploiting U.S.-NATO friction. Critical sub-text: '
            f'Russian Northern Fleet SSBNs patrol through the GIUK Gap '
            f'(Greenland-Iceland-UK), NATO\'s primary anti-submarine chokepoint. '
            f'Greenland access directly affects U.S. ability to track Russian nuclear submarine '
            f'approaches to the East Coast and Caribbean.'
        )

    if delta_dir == 'rising' and score_change >= 8:
        situation_parts.append(
            f'Trajectory accelerating -- score up +{round(score_change)} from recent average.'
        )

    if not situation_parts:
        situation_parts.append(
            'Baseline conditions. U.S. rhetorical interest in Greenland predates Trump -- '
            'monitoring for shift from stated interest to operational pressure signals.'
        )

    # ── Key indicators ──
    indicators = []

    if nato_cohesion_risk:
        indicators.append(
            'NATO COHESION SIGNAL: Track whether European allies (France, UK, Germany) '
            'are formally coordinating with Denmark or staying silent. Silent allies = '
            'US pressure is working; coordinated rebuke = alliance is holding against pressure.'
        )

    if russia_exploiting:
        indicators.append(
            'RUSSIA ARCTIC WATCH: Northern Fleet exercise tempo + SSBN departure signals '
            'from Severomorsk are the key intelligence indicators. Russian basing expansion '
            'in Svalbard, Franz Josef Land, or Arctic Canada approaches is the tripwire. '
            'Any Russian "offer" to Greenland is a wedge diplomacy signal, not altruism.'
        )

    if us_level >= 2:
        indicators.append(
            'US ESCALATION LADDER: Rhetoric (L1) -> Economic coercion (L2-3) -> '
            'Formal ultimatum / unilateral action (L4-5). Watch for Pentagon operational '
            'planning signals and Congressional legislation as escalation leading indicators -- '
            'these move before presidential rhetoric shifts to action.'
        )

    if sovereignty_hardening:
        indicators.append(
            'INDEPENDENCE PARADOX: Greenlandic independence polling is rising under US pressure. '
            'An independent Greenland would be harder for the US to acquire than '
            'Danish-administered Greenland -- monitor Naalakkersuisut referendum signals '
            'as a counter-leverage mechanism by Nuuk.'
        )

    if breached_count >= 1:
        indicators.append(
            f'{breached_count} red line(s) currently breached -- '
            f'signals that historically precede escalation from rhetorical to operational pressure.'
        )

    # ── Assessment ──
    assessment_parts = []

    if top_match and top_match['similarity'] >= 55:
        assessment_parts.append(
            f'Current signal pattern shows {top_match["similarity"]}% similarity to '
            f'{top_match["label"]}. In that case: {top_match["outcome"].lower()}'
        )
        assessment_parts.append(
            f'Confidence: {top_match["confidence"]}. Analytical estimate only.'
        )
    else:
        if us_level >= 2:
            assessment_parts.append(
                'Pattern below historical escalation threshold. '
                'Closest analog: Trump Panama Canal rhetoric (2024-25) -- '
                'maximum-pressure language without operational follow-through. '
                'Watch for Pentagon/EUCOM signals, not just White House statements.'
            )

    # ── Watch list ──
    watch_items = [
        'Pentagon/EUCOM operational planning signals re: Greenland basing -- '
        'military movement precedes diplomatic ultimatum historically',
        'Danish parliamentary unity -- coalition fracture under US pressure '
        'would signal Copenhagen\'s resolve weakening',
        'Greenlandic election signals -- early elections or coalition shifts '
        'in Nuuk could indicate independence referendum path accelerating',
        'Russian Northern Fleet exercise tempo -- surge activity timed to '
        'US-NATO friction is deliberate GIUK exploitation signal',
        'EU/European Commission formal response -- Brussels silence = '
        'US pressure working; formal EU statement = multilateral resistance forming',
    ]
    if russia_level >= 3:
        watch_items.insert(0,
            'PRIORITY WATCH: Russian Arctic basing expansion or SSBN surge -- '
            'Kremlin is using US-NATO friction to reposition for GIUK chokepoint advantage'
        )

    return {
        'scenario':                scenario,
        'scenario_color':          scenario_color,
        'scenario_icon':           scenario_icon,
        'situation':               ' '.join(situation_parts),
        'key_indicators':          indicators,
        'assessment':              ' '.join(assessment_parts),
        'watch_list':              watch_items[:5],
        'nato_cohesion_risk':      nato_cohesion_risk,
        'russia_exploiting':       russia_exploiting,
        'alliance_fracture_risk':  alliance_fracture_risk,
        'generated_at':            datetime.now(timezone.utc).isoformat(),
        'confidence_note': (
            'Greenland assessment generated from open-source signal data. '
            'Not a prediction. Analytical estimates only -- verify through official channels. '
            'Russia GIUK/SSBN context reflects publicly documented strategic geography. '
            'Historical pattern matching is illustrative, not deterministic.'
        ),
    }


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def interpret_signals(scan_data):
    """
    Main entry point. Called from rhetoric_tracker_greenland.py with full scan_data.
    Returns interpretation dict embedded as result['interpretation'].
    Mirrors lebanon_signal_interpreter.py pattern exactly.
    """
    try:
        red_lines  = _score_red_lines(scan_data)
        historical = _match_historical(scan_data)
        so_what    = _build_so_what(scan_data, red_lines, historical)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']

        return {
            'so_what':             so_what,
            'red_lines': {
                'triggered':         red_lines,
                'breached_count':    len(breached),
                'approaching_count': len(approaching),
                'highest_severity':  max((r['severity'] for r in red_lines), default=0),
            },
            'historical_matches':  historical,
            'interpreter_version': '1.0.0',
            'interpreted_at':      datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f'[Greenland Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what':            {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines':          {'triggered': [], 'breached_count': 0, 'approaching_count': 0, 'highest_severity': 0},
            'historical_matches': [],
            'interpreter_version': '1.0.0',
            'error':              str(e)[:200],
        }


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    test_data = {
        'theatre_score': 55,
        'russia_opportunism': True,
        'convergence_signal': 'US pressure meets sovereignty defense',
        'delta': {'direction': 'rising', 'score_change': 12},
        'actors': {
            'us_pressure': {'level': 3, 'escalation_level': 3, 'top_articles': [
                {'title': 'Trump says US will take Greenland one way or another', 'published': ''},
                {'title': 'Pentagon reviewing Arctic basing options including Pituffik expansion', 'published': ''},
            ]},
            'greenland_inuit': {'level': 2, 'escalation_level': 2, 'top_articles': [
                {'title': 'Egede: Greenland is not for sale to anyone', 'published': ''},
                {'title': 'Greenland independence poll hits record high amid US pressure', 'published': ''},
            ]},
            'denmark_nato': {'level': 3, 'escalation_level': 3, 'top_articles': [
                {'title': 'Danish PM calls emergency NATO consultations on Greenland', 'published': ''},
                {'title': 'Denmark sends additional naval patrol to Greenland waters', 'published': ''},
            ]},
            'russia_arctic': {'level': 3, 'escalation_level': 3, 'top_articles': [
                {'title': 'Russia Northern Fleet conducts Arctic exercise as NATO tensions rise', 'published': ''},
                {'title': 'Kremlin offers to discuss Arctic cooperation with Greenland', 'published': ''},
            ]},
            'china_observer': {'level': 1, 'escalation_level': 1, 'top_articles': []},
        },
    }

    result = interpret_signals(test_data)

    print('\n' + '='*65)
    print('SCENARIO:', result['so_what']['scenario'])
    print('NATO COHESION RISK:', result['so_what'].get('nato_cohesion_risk'))
    print('RUSSIA EXPLOITING:', result['so_what'].get('russia_exploiting'))
    print('='*65)
    print('\nSITUATION:')
    print(result['so_what']['situation'][:600])
    print('\nKEY INDICATORS:')
    for ind in result['so_what']['key_indicators']:
        print(f'  -- {ind[:120]}')
    print('\nWATCH LIST:')
    for item in result['so_what']['watch_list']:
        print(f'  -> {item[:100]}')
    print('\nRED LINES:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} (Sev {rl["severity"]}) [{rl["category"]}]')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% -- {hm["label"]} | Confidence: {hm["confidence"]}')


# ============================================================
# v2.0+ — TOP SIGNALS (BLUF / GPI consumable)
# ============================================================
# Greenland is an INVERTED-rhetoric tracker — the threat language is
# inbound from the US, not outbound from Greenland. Categories reflect
# this asymmetry: us_pressure_high (escalation), nato_cohesion_risk,
# russia_exploiting (cross-theater opportunism), sovereignty_crisis.

GREENLAND_FLAG = '\U0001f1ec\U0001f1f1'  # 🇬🇱

def build_top_signals(scan_data):
    """
    Build Greenland's top_signals[] for BLUF/GPI consumption.
    Greenland tracker writes interpreter output under 'interpretation' (ME pattern).
    Returns sorted list (descending priority).
    """
    signals = []

    # ME pattern: interpreter output lives under 'interpretation' wrapper
    interp = scan_data.get('interpretation', {}) or {}
    so_what   = interp.get('so_what', {}) or {}
    red_lines = interp.get('red_lines', {}) or {}

    # Theatre-level fields at top of scan_data
    theatre_level = scan_data.get('theatre_level', 0) or 0
    theatre_score = scan_data.get('theatre_score', 0) or 0

    # Actor levels
    us_level        = scan_data.get('us_pressure_level', 0) or 0
    greenland_level = scan_data.get('greenland_level', 0) or 0
    denmark_level   = scan_data.get('denmark_level', 0) or 0
    russia_level    = scan_data.get('russia_level', 0) or 0

    # Special signals
    convergence_signal = scan_data.get('convergence_signal', '') or ''
    defence_intensity  = scan_data.get('defence_intensity', 0) or 0
    russia_opportunism = scan_data.get('russia_opportunism', 0) or 0

    # Red lines
    rl_triggered = red_lines.get('triggered', []) or []
    breached = [r for r in rl_triggered if isinstance(r, dict) and r.get('status') == 'BREACHED']
    approaching = [r for r in rl_triggered if isinstance(r, dict) and r.get('status') == 'APPROACHING']

    # ============================================
    # 1. RED LINES BREACHED
    # ============================================
    for rl in breached[:3]:
        label    = rl.get('label', 'Sovereignty red line')
        severity = rl.get('severity', 5) or 5
        signals.append({
            'priority':   12,
            'category':   'red_line_breached',
            'theatre':    'greenland',
            'level':      max(theatre_level, 4),
            'icon':       rl.get('icon', '🚨'),
            'color':      '#dc2626',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: BREACH — {label[:55]}',
            'long_text':  f'GREENLAND sovereignty red line breached (severity {severity}): {label}',
        })

    for rl in approaching[:2]:
        label = rl.get('label', 'Sovereignty red line')
        signals.append({
            'priority':   8,
            'category':   'red_line_approaching',
            'theatre':    'greenland',
            'level':      theatre_level,
            'icon':       '🟠',
            'color':      '#f97316',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: Approaching — {label[:50]}',
            'long_text':  f'GREENLAND approaching red line: {label}',
        })

    # ============================================
    # 2. THEATRE-HIGH (sovereignty crisis at L3+)
    # ============================================
    if theatre_level >= 4:
        signals.append({
            'priority':   9 + theatre_level,
            'category':   'theatre_high',
            'theatre':    'greenland',
            'level':      theatre_level,
            'icon':       '🔴',
            'color':      '#dc2626' if theatre_level >= 5 else '#ef4444',
            'short_text': f'{GREENLAND_FLAG} GREENLAND L{theatre_level} — Sovereignty crisis',
            'long_text':  f'GREENLAND at L{theatre_level} sovereignty crisis (score {theatre_score}/100). '
                          f'Inbound US pressure L{us_level}, Russia opportunism L{russia_level}.',
        })
    elif theatre_level >= 3:
        signals.append({
            'priority':   8,
            'category':   'theatre_high',
            'theatre':    'greenland',
            'level':      theatre_level,
            'icon':       '🟠',
            'color':      '#f97316',
            'short_text': f'{GREENLAND_FLAG} GREENLAND L{theatre_level} — Sovereignty pressure',
            'long_text':  f'GREENLAND at L{theatre_level} sovereignty pressure (score {theatre_score}/100). '
                          f'US rhetoric L{us_level} vs. Greenland posture L{greenland_level}.',
        })

    # ============================================
    # 3. US PRESSURE HIGH (Greenland's KEY inbound signal)
    # ============================================
    if us_level >= 4:
        signals.append({
            'priority':   11,
            'category':   'us_pressure_high',
            'theatre':    'greenland',
            'level':      us_level,
            'icon':       '🦅',
            'color':      '#dc2626',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: US pressure L{us_level}',
            'long_text':  f'GREENLAND inbound US sovereignty pressure L{us_level} — explicit acquisition '
                          f'or coercive language from the US administration.',
        })
    elif us_level >= 3:
        signals.append({
            'priority':   8,
            'category':   'us_pressure_high',
            'theatre':    'greenland',
            'level':      us_level,
            'icon':       '🦅',
            'color':      '#f97316',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: US pressure L{us_level}',
            'long_text':  f'GREENLAND inbound US pressure L{us_level} — direct rhetoric from US administration.',
        })

    # ============================================
    # 4. NATO COHESION RISK / ALLIANCE FRACTURE
    # ============================================
    nato_risk = so_what.get('nato_cohesion_risk', False)
    alliance_fracture = so_what.get('alliance_fracture_risk', False)
    if nato_risk or alliance_fracture:
        signals.append({
            'priority':   10,
            'category':   'nato_cohesion_risk',
            'theatre':    'greenland',
            'level':      max(us_level, denmark_level, 3),
            'icon':       '⚠️',
            'color':      '#dc2626',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: NATO cohesion at risk',
            'long_text':  f'GREENLAND NATO cohesion risk active — US-Denmark alliance friction over '
                          f'Greenland sovereignty signals could fracture allied posture.',
        })
    elif denmark_level >= 3:
        signals.append({
            'priority':   6,
            'category':   'denmark_pushback',
            'theatre':    'greenland',
            'level':      denmark_level,
            'icon':       '🇩🇰',
            'color':      '#3b82f6',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: Denmark pushback L{denmark_level}',
            'long_text':  f'GREENLAND: Denmark sovereignty defense L{denmark_level} — Copenhagen '
                          f'asserting sovereignty against US pressure.',
        })

    # ============================================
    # 5. RUSSIA EXPLOITATION (cross-theater opportunism)
    # ============================================
    russia_exploiting = so_what.get('russia_exploiting', False)
    if russia_exploiting or russia_level >= 3:
        signals.append({
            'priority':   9,
            'category':   'russia_exploiting',
            'theatre':    'greenland',
            'level':      max(russia_level, 3),
            'icon':       '🇷🇺',
            'color':      '#7c3aed',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: Russia exploiting Arctic L{russia_level}',
            'long_text':  f'GREENLAND: Russia exploiting US-Greenland friction L{russia_level} — '
                          f'GIUK gap, Northern Fleet posture, or sub-cable interference signaling.',
        })

    # ============================================
    # 6. GREENLAND POSTURE (defensive sovereignty)
    # ============================================
    if greenland_level >= 4:
        signals.append({
            'priority':   8,
            'category':   'greenland_posture',
            'theatre':    'greenland',
            'level':      greenland_level,
            'icon':       '🛡️',
            'color':      '#3b82f6',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: Sovereignty posture L{greenland_level}',
            'long_text':  f'GREENLAND defensive sovereignty rhetoric L{greenland_level} — Nuuk asserting '
                          f'self-determination, possible election or referendum signals.',
        })

    # ============================================
    # 7. CONVERGENCE SIGNAL (special semantic flag)
    # ============================================
    if convergence_signal:
        signals.append({
            'priority':   7,
            'category':   'convergence_signal',
            'theatre':    'greenland',
            'level':      theatre_level,
            'icon':       '📡',
            'color':      '#f59e0b',
            'short_text': f'{GREENLAND_FLAG} GREENLAND: {convergence_signal[:55]}',
            'long_text':  f'GREENLAND convergence: {convergence_signal}',
        })

    # Sort descending; BLUF will dedupe + globally rank
    signals.sort(key=lambda s: s['priority'], reverse=True)
    return signals
