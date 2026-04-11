"""
russia_signal_interpreter.py
Asifah Analytics -- Europe Backend Module
v1.0.0 -- April 2026

Signal interpretation engine for the Russia Rhetoric Tracker.

Russia's analytical frame is FIVE-WAY:

  1. Is Russia signaling conventional escalation on NATO's eastern flank?
     (Baltic, Poland, Kaliningrad, Finland, Suwalki Gap)
  2. Is nuclear rhetoric coercive posturing vs. genuine doctrinal signal?
     (Medvedev/Putin language ladder, Iskander, SSBN, doctrine shifts)
  3. Is the Ukraine war trajectory shifting?
     (Russian gains = emboldened; losses = desperate escalation)
     (Ukrainian diplomatic posture = off-ramp or entrenchment)
  4. Is Russia coordinating cross-theater pressure simultaneously?
     (Iran weapons, DPRK ammunition, Cuba/Venezuela WHA, Arctic)
  5. Are Arctic / GIUK Gap signals above baseline?
     (Northern Fleet, SSBN patrols, Svalbard, GIUK, Greenland convergence)

KEY ANALYTICAL INSIGHT:
Russia's escalation ladder is multi-flank. Unlike China (Taiwan-focused)
or Iran (ME-focused), Russia can pressure NATO via ALL five vectors
simultaneously. Maximum pressure scenario = all five elevated at once.
Partial pressure = coercion without commitment to kinetics.

The Ukraine war creates a paradox:
  - Russian gains → emboldened, more aggressive NATO posture signals
  - Russian losses → desperate, more likely to escalate with nuclear rhetoric
  - Ukrainian diplomatic openness → green line (off-ramp possible)
  - Ukrainian entrenchment + US aid suspension → Russian opportunity window

CROSS-THEATER NOTE:
Russia's fingerprint is written to shared Redis key and is readable by:
  - ME backend (Iran-Russia strategic partnership)
  - WHA backend (Cuba, Venezuela, Nicaragua)
  - Europe backend (Ukraine, Baltic, Arctic)
Russia is the ONLY theater actor that directly affects ALL other theaters.

Author: RCGG / Asifah Analytics
"""

from datetime import datetime, timezone


# ============================================================
# RED LINE DEFINITIONS (escalation triggers)
# ============================================================
RED_LINES = [

    # ── Category A: Nuclear signals ───────────────────────────
    {
        'id':       'nuclear_rhetoric_escalation',
        'label':    'Nuclear Rhetoric Above Doctrinal Baseline',
        'detail':   'Putin/Medvedev/Kremlin uses nuclear language beyond routine deterrence -- '
                    'specific threat language, deployment signals, or doctrine change',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '☢️',
        'category': 'nuclear',
        'source':   'Russian nuclear doctrine: rhetoric escalation historically precedes '
                    'deployment posture changes. Medvedev is the designated nuclear coercion instrument.',
    },
    {
        'id':       'tactical_nuclear_deployment',
        'label':    'Tactical Nuclear Deployment Signal',
        'detail':   'Credible signal of tactical nuclear weapons deployment -- '
                    'Iskander nuclear warheads, Belarus deployment, submarine surge',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '💣',
        'category': 'nuclear',
        'source':   'NATO doctrine: tactical nuclear deployment is the threshold before use. '
                    'Belarus deployment (2023) established precedent.',
    },

    # ── Category B: NATO Flank triggers ───────────────────────
    {
        'id':       'kaliningrad_escalation',
        'label':    'Kaliningrad Military Escalation',
        'detail':   'Unusual military buildup or Iskander deployment in Kaliningrad -- '
                    'threatens Baltic states and Suwalki Gap connectivity',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🗺️',
        'category': 'nato_flank',
        'source':   'Strategic geography: Kaliningrad is Russia\'s NATO flank pressure point. '
                    'Suwalki Gap closure would isolate Baltic states from NATO.',
    },
    {
        'id':       'article5_trigger_language',
        'label':    'Article 5 Trigger Language / NATO Attack Signal',
        'detail':   'Russian actions or statements that could trigger NATO Article 5 collective defense -- '
                    'attack on NATO member territory, infrastructure, or personnel',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🔴',
        'category': 'nato_flank',
        'source':   'NATO founding document: Article 5 invocation would be unprecedented. '
                    'Baltic cable attacks, airspace violations, proxy attacks approach this threshold.',
    },
    {
        'id':       'suwalki_gap_threat',
        'label':    'Suwalki Gap Closure Threat',
        'detail':   'Russian/Belarusian signals suggesting intent to close the Suwalki Gap -- '
                    'would physically isolate Estonia, Latvia, Lithuania from NATO',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🚪',
        'category': 'nato_flank',
        'source':   'NATO strategic vulnerability: Suwalki Corridor is 65km between '
                    'Kaliningrad and Belarus -- the single land connection to Baltic NATO members.',
    },

    # ── Category C: Ukraine war trajectory ───────────────────
    {
        'id':       'russian_major_advance',
        'label':    'Russian Major Territorial Advance in Ukraine',
        'detail':   'Russia achieves significant territorial gain -- signals military momentum '
                    'and emboldens further NATO pressure signals',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '⚔️',
        'category': 'ukraine_front',
        'source':   'Pattern: Russian territorial gains historically correlate with '
                    'increased Kremlin risk appetite on NATO pressure signals.',
    },
    {
        'id':       'ukraine_collapse_signal',
        'label':    'Ukrainian Military Cohesion Collapse Signal',
        'detail':   'Credible signals of Ukrainian front collapse, major city loss, '
                    'or morale/supply breakdown -- creates Russian opportunity window',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🏳️',
        'category': 'ukraine_front',
        'source':   'Strategic: Ukrainian collapse would remove the primary NATO '
                    'pressure absorption point and shift Russian attention to NATO directly.',
    },
    {
        'id':       'us_aid_suspension',
        'label':    'US Ukraine Aid Suspension',
        'detail':   'United States suspends or significantly reduces military aid to Ukraine -- '
                    'creates Russian opportunity window and emboldens pressure on NATO',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '💰',
        'category': 'ukraine_front',
        'source':   'Pattern: Russian offensive tempo historically correlates with '
                    'Western aid uncertainty. Trump administration creates structural uncertainty.',
    },

    # ── Category D: Arctic signals ───────────────────────────
    {
        'id':       'ssbn_unusual_deployment',
        'label':    'Russian SSBN Unusual Deployment Pattern',
        'detail':   'Russian ballistic missile submarine deployment above normal patrol pattern -- '
                    'GIUK Gap surge, Mediterranean deployment, or simultaneous multi-boat patrol',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🌊',
        'category': 'arctic',
        'source':   'NATO ASWRG doctrine: SSBN surge is the most significant nuclear '
                    'alert signal short of weapons deployment. Historically precedes '
                    'major political pressure campaigns.',
    },
    {
        'id':       'arctic_territorial_escalation',
        'label':    'Arctic Territorial Escalation',
        'detail':   'Russia makes aggressive move on Arctic territorial claims -- '
                    'Svalbard militarization, Arctic shelf dispute force, '
                    'or Northern Sea Route closure threat',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🧊',
        'category': 'arctic',
        'source':   'Arctic Council breakdown (post-2022) removed diplomatic channel. '
                    'Svalbard Treaty gives Russia access rights -- Norway is the trip wire.',
    },
    {
        'id':       'giuk_gap_surge',
        'label':    'GIUK Gap Russian Submarine Surge',
        'detail':   'Multiple Russian submarines detected in GIUK Gap simultaneously -- '
                    'threatens NATO Atlantic LOCs and signals strategic positioning',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '🔱',
        'category': 'arctic',
        'source':   'Cold War precedent: GIUK surge historically preceded major pressure campaigns. '
                    'Also threatens undersea cables and pipeline infrastructure.',
    },

    # ── Category E: Cross-theater coordination ───────────────
    {
        'id':       'cross_theater_coordination',
        'label':    'Multi-Theater Russian Pressure Coordination',
        'detail':   'Russia coordinating pressure across 3+ theaters simultaneously -- '
                    'Iran/ME + DPRK/Asia + Cuba/WHA + Arctic = maximum pressure scenario',
        'severity': 3,
        'color':    '#dc2626',
        'icon':     '🌐',
        'category': 'cross_theater',
        'source':   'Analytical: simultaneous multi-theater Russian pressure has no Cold War analog. '
                    'Iran weapons + DPRK ammunition + Cuba SIGINT = structured alliance.',
    },
    {
        'id':       'hybrid_infrastructure_attack',
        'label':    'Confirmed Hybrid Attack on NATO Infrastructure',
        'detail':   'Confirmed Russian-attributed cyberattack, undersea cable cutting, '
                    'or sabotage of NATO/European critical infrastructure',
        'severity': 2,
        'color':    '#f97316',
        'icon':     '💻',
        'category': 'hybrid',
        'source':   'Baltic cable incidents (2023-2024) established the pattern. '
                    'European power grid, internet exchange, and pipeline attacks '
                    'are below Article 5 threshold but escalatory.',
    },

    # ── Category F: De-escalation signals ────────────────────
    {
        'id':       'trump_putin_diplomatic_engagement',
        'label':    'Trump-Putin Direct Diplomatic Engagement',
        'detail':   'Active US-Russia diplomatic engagement on Ukraine -- '
                    'meetings, phone calls, or framework negotiations',
        'severity': 1,
        'color':    '#10b981',
        'icon':     '🤝',
        'category': 'deescalation',
        'source':   'Trump administration diplomatic opening to Russia creates '
                    'potential off-ramp. Watch for: Ukraine territorial concessions, '
                    'sanctions relief, NATO expansion pause.',
    },
    {
        'id':       'ukraine_ceasefire_framework',
        'label':    'Ukraine Ceasefire Framework Emerging',
        'detail':   'Credible ceasefire framework with named conditions and parties -- '
                    'beyond general calls for peace',
        'severity': 1,
        'color':    '#10b981',
        'icon':     '📋',
        'category': 'deescalation',
        'source':   'Any Ukraine ceasefire would reduce the primary Russian military '
                    'pressure absorption point and shift focus to diplomatic settlement.',
    },
]


# ============================================================
# GREEN LINE DEFINITIONS (diplomatic off-ramp signals)
# ============================================================
GREEN_LINES = [
    {
        'id':       'trump_putin_talks_active',
        'label':    'Trump-Putin Direct Talks Active',
        'detail':   'US-Russia direct engagement at presidential level -- '
                    'the only channel with leverage to produce Ukraine settlement',
        'momentum': 3,
        'color':    '#10b981',
        'icon':     '🤝',
        'category': 'us_russia_diplomacy',
        'source':   'Trump has stated intent to end Ukraine war quickly. '
                    'Direct Putin engagement is the prerequisite for any deal.',
    },
    {
        'id':       'ukraine_ceasefire_active',
        'label':    'Ukraine Ceasefire Negotiations Active',
        'detail':   'Formal ceasefire talks with named parties, conditions, and timeline',
        'momentum': 3,
        'color':    '#10b981',
        'icon':     '🕊️',
        'category': 'ukraine_peace',
        'source':   'Ukraine ceasefire is the primary de-escalation signal for '
                    'the Russia tracker. All other pressure vectors reduce if war ends.',
    },
    {
        'id':       'russia_military_pullback',
        'label':    'Russian Military Pullback Signal',
        'detail':   'Credible Russian military drawdown from NATO border or Ukraine front -- '
                    'genuine de-escalation vs. tactical repositioning',
        'momentum': 2,
        'color':    '#22c55e',
        'icon':     '↩️',
        'category': 'military_deescalation',
        'source':   'Pattern: Russian military pullback signals (2022 pre-invasion feint) '
                    'require verification. Genuine drawdown is a strong de-escalation signal.',
    },
    {
        'id':       'ukraine_diplomatic_openness',
        'label':    'Ukraine Signals Openness to Negotiations',
        'detail':   'Zelenskyy or Ukrainian government signals willingness to negotiate -- '
                    'distinct from military posture',
        'momentum': 2,
        'color':    '#22c55e',
        'icon':     '🇺🇦',
        'category': 'ukraine_peace',
        'source':   'Ukrainian diplomatic flexibility is a necessary condition for settlement. '
                    'Trump pressure on Zelenskyy to negotiate is the key variable.',
    },
    {
        'id':       'nato_russia_hotline_active',
        'label':    'NATO-Russia Hotline / Deconfliction Active',
        'detail':   'NATO-Russia Council or military deconfliction channels reactivated -- '
                    'reduces risk of miscalculation escalation',
        'momentum': 1,
        'color':    '#4ade80',
        'icon':     '📞',
        'category': 'nato_russia_diplomacy',
        'source':   'NATO-Russia Council suspended post-2022. Reactivation would be '
                    'significant confidence-building measure.',
    },
    {
        'id':       'arctic_council_reengagement',
        'label':    'Arctic Council Re-engagement Signal',
        'detail':   'Russia or NATO members signal willingness to re-engage in '
                    'Arctic Council -- reduces Arctic militarization risk',
        'momentum': 1,
        'color':    '#4ade80',
        'icon':     '🧊',
        'category': 'arctic_diplomacy',
        'source':   'Arctic Council suspended after 2022 invasion. '
                    'Re-engagement would signal broader diplomatic opening.',
    },
]


# ============================================================
# HISTORICAL PRECEDENTS
# ============================================================
HISTORICAL_PRECEDENTS = [
    {
        'id':          'ukraine_2022_invasion',
        'label':       'Russian Full-Scale Invasion of Ukraine (Feb 2022)',
        'description': 'Russia launched full-scale invasion after months of buildup and diplomatic ultimatums',
        'source':      'ISW; IISS; NATO; multiple open source',
        'signals': {
            'russia_military_min': 4,
            'russia_gov_min':      4,
            'nato_pressure':       True,
            'nuclear_rhetoric':    True,
            'belarus_active':      True,
        },
        'outcome':      'Full invasion failed to take Kyiv. War of attrition followed. '
                        'NATO expanded (Finland, Sweden). Russian economy under severe sanctions.',
        'window_hours': 72,
        'confidence':   'High',
    },
    {
        'id':          'crimea_2014',
        'label':       'Crimea Annexation (2014)',
        'description': 'Russia annexed Crimea and supported Donbas separatists under "little green men" model',
        'source':      'IISS; ISW; Chatham House',
        'signals': {
            'russia_military_min': 3,
            'russia_gov_min':      3,
            'hybrid_active':       True,
            'nato_pressure':       False,
            'ukraine_weak':        True,
        },
        'outcome':      'Crimea annexed. Donbas frozen conflict. NATO slow response. '
                        'Established precedent for hybrid + conventional combination.',
        'window_hours': 168,
        'confidence':   'High',
    },
    {
        'id':          'nuclear_coercion_2022_2023',
        'label':       'Russian Nuclear Coercion Campaign (2022-2023)',
        'description': 'Systematic nuclear rhetoric campaign by Medvedev/Putin to deter Western Ukraine aid',
        'source':      'Carnegie; RAND; Belfer Center nuclear coercion analysis',
        'signals': {
            'nuclear_rhetoric':    True,
            'russia_gov_min':      3,
            'ukraine_aid_context': True,
        },
        'outcome':      'Rhetoric did not prevent Western aid but delayed heavy weapons. '
                        'Established Medvedev as designated nuclear signaling instrument. '
                        'NATO absorbed signals without Article 5 response.',
        'window_hours': 0,
        'confidence':   'High',
    },
    {
        'id':          'belarus_nuclear_2023',
        'label':       'Tactical Nuclear Weapons to Belarus (2023)',
        'description': 'Russia deployed tactical nuclear weapons to Belarus -- first non-Russian territory since Soviet era',
        'source':      'Putin statement June 2023; Lukashenko confirmation; IAEA monitoring',
        'signals': {
            'nuclear_rhetoric':    True,
            'belarus_active':      True,
            'russia_gov_min':      3,
        },
        'outcome':      'Deployment completed without NATO kinetic response. '
                        'Established precedent for forward nuclear deployment. '
                        'NATO Article 5 guarantee not invoked despite deployment to neighbor.',
        'window_hours': 0,
        'confidence':   'High',
    },
    {
        'id':          'arctic_cold_war_patrols',
        'label':       'Soviet/Russian Arctic SSBN Surge Precedents',
        'description': 'Cold War and post-Cold War SSBN surge deployments correlating with political pressure campaigns',
        'source':      'IISS Military Balance; US Navy ASWRG historical; Submariner Association archives',
        'signals': {
            'arctic_elevated':     True,
            'nuclear_rhetoric':    True,
            'russia_military_min': 3,
        },
        'outcome':      'Historical pattern: SSBN surges preceded major Soviet/Russian '
                        'diplomatic pressure campaigns by 2-4 weeks. '
                        'GIUK gap remains NATO\'s primary Atlantic vulnerability.',
        'window_hours': 336,
        'confidence':   'Medium',
    },
]


# ============================================================
# CORE SCORING FUNCTIONS
# ============================================================

def _score_red_lines(scan_data):
    """Evaluate Russia signal state against red lines."""
    actors = scan_data.get('actors', {})

    russia_mil_level = actors.get('russia_military',  {}).get('escalation_level', 0)
    russia_gov_level = actors.get('russia_government',{}).get('escalation_level', 0)
    ukraine_level    = actors.get('ukraine',          {}).get('escalation_level', 0)
    nato_level       = actors.get('nato_alliance',    {}).get('escalation_level', 0)
    us_level         = actors.get('united_states',    {}).get('escalation_level', 0)
    baltic_level     = actors.get('baltic_flank',     {}).get('escalation_level', 0)
    arctic_level_a   = actors.get('arctic_watch',     {}).get('escalation_level', 0)
    belarus_level    = actors.get('belarus',          {}).get('escalation_level', 0)

    nuclear_level    = scan_data.get('nuclear_level',    0)
    gnd_level        = scan_data.get('ground_ops_level', 0)
    nato_flank_level = scan_data.get('nato_flank_level', 0)
    arctic_level     = scan_data.get('arctic_level',     max(arctic_level_a, 0))
    hybrid_level     = scan_data.get('hybrid_level',     0)

    def _scan_articles(actor_ids, keywords):
        for aid in actor_ids:
            for art in actors.get(aid, {}).get('top_articles', []):
                title = art.get('title', '').lower()
                if any(kw.lower() in title for kw in keywords):
                    return True
        return False

    # Signal detection
    nuclear_signal = _scan_articles(
        ['russia_government', 'russia_military'],
        ['nuclear', 'ядерн', 'medvedev nuclear', 'sarmat', 'poseidon',
         'nuclear threat', 'nuclear warning', 'nuclear doctrine']
    )
    kaliningrad_signal = _scan_articles(
        ['russia_military', 'baltic_flank'],
        ['kaliningrad', 'iskander', 'suwalki', 'baltic escalation']
    )
    ssbn_signal = _scan_articles(
        ['arctic_watch', 'russia_military'],
        ['ssbn', 'submarine deployment', 'northern fleet surge',
         'ballistic missile submarine', 'giuk gap']
    )
    svalbard_signal = _scan_articles(
        ['arctic_watch'],
        ['svalbard', 'svalbard military', 'spitsbergen military',
         'arctic territorial', 'arctic claim force']
    )
    hybrid_signal = _scan_articles(
        ['russia_military', 'russia_government'],
        ['cyber attack', 'undersea cable', 'sabotage', 'infrastructure attack',
         'pipeline attack', 'disinformation campaign']
    )
    ukraine_collapse = _scan_articles(
        ['ukraine'],
        ['ukraine collapse', 'ukraine retreats', 'ukraine falls',
         'ukraine loses city', 'ukraine front broken']
    )
    us_aid_suspend = _scan_articles(
        ['united_states'],
        ['us suspends aid', 'aid pause', 'halt aid ukraine',
         'trump stops ukraine', 'aid cut ukraine']
    )
    cross_theater = _scan_articles(
        ['russia_military', 'russia_government'],
        ['dprk russia', 'iran russia weapons', 'north korea russia',
         'cuba russia military', 'cross theater', 'axis resistance russia']
    )
    trump_putin_talks = _scan_articles(
        ['united_states', 'russia_government'],
        ['trump putin', 'trump russia talks', 'trump ukraine deal',
         'us russia negotiations', 'peace talks ukraine']
    )
    ceasefire_signal = _scan_articles(
        ['ukraine', 'united_states', 'russia_government'],
        ['ceasefire ukraine', 'ukraine peace deal', 'ukraine negotiations',
         'ukraine peace talks', 'ukraine ceasefire framework']
    )

    triggered = []

    # ── Nuclear rhetoric escalation ──
    if nuclear_level >= 3 or (nuclear_signal and russia_gov_level >= 2):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'nuclear_rhetoric_escalation'),
            'status':  'BREACHED' if nuclear_level >= 4 else 'APPROACHING',
            'trigger': f'Nuclear rhetoric L{nuclear_level} -- Kremlin/Medvedev nuclear language above baseline',
        })

    # ── Tactical nuclear deployment ──
    if nuclear_level >= 4 or ssbn_signal:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'tactical_nuclear_deployment'),
            'status':  'BREACHED' if nuclear_level >= 5 else 'APPROACHING',
            'trigger': f'SSBN/deployment signals detected + nuclear L{nuclear_level}',
        })

    # ── Kaliningrad escalation ──
    if kaliningrad_signal or (nato_flank_level >= 3 and belarus_level >= 2):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'kaliningrad_escalation'),
            'status':  'BREACHED' if nato_flank_level >= 5 else 'APPROACHING',
            'trigger': f'Kaliningrad/Suwalki language + NATO flank L{nato_flank_level}',
        })

    # ── Article 5 trigger language ──
    if nato_flank_level >= 4 or baltic_level >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'article5_trigger_language'),
            'status':  'BREACHED' if (nato_flank_level >= 5 or baltic_level >= 5) else 'APPROACHING',
            'trigger': f'NATO flank L{nato_flank_level}, Baltic L{baltic_level} -- approaching Article 5 territory',
        })

    # ── Suwalki Gap threat ──
    if nato_flank_level >= 4 and belarus_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'suwalki_gap_threat'),
            'status':  'APPROACHING',
            'trigger': f'NATO flank L{nato_flank_level} + Belarus L{belarus_level} -- Suwalki gap pressure pattern',
        })

    # ── Russian major advance ──
    if gnd_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'russian_major_advance'),
            'status':  'BREACHED' if gnd_level >= 4 else 'APPROACHING',
            'trigger': f'Ground ops L{gnd_level} -- Russian advance signals in Ukraine',
        })

    # ── Ukraine collapse signal ──
    if ukraine_collapse or (gnd_level >= 4 and ukraine_level <= 1):
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'ukraine_collapse_signal'),
            'status':  'APPROACHING',
            'trigger': 'Ukrainian military cohesion signals weakening -- front pressure',
        })

    # ── US aid suspension ──
    if us_aid_suspend:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'us_aid_suspension'),
            'status':  'APPROACHING',
            'trigger': 'US aid suspension signals detected -- Russian opportunity window opening',
        })

    # ── SSBN unusual deployment ──
    if ssbn_signal or arctic_level >= 4:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'ssbn_unusual_deployment'),
            'status':  'BREACHED' if arctic_level >= 5 else 'APPROACHING',
            'trigger': f'SSBN/Northern Fleet signals + Arctic L{arctic_level}',
        })

    # ── Arctic territorial escalation ──
    if svalbard_signal or arctic_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'arctic_territorial_escalation'),
            'status':  'BREACHED' if arctic_level >= 4 else 'APPROACHING',
            'trigger': f'Arctic L{arctic_level} -- territorial/Svalbard signals',
        })

    # ── GIUK Gap surge ──
    if ssbn_signal and arctic_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'giuk_gap_surge'),
            'status':  'APPROACHING',
            'trigger': 'SSBN + Arctic elevated -- GIUK Gap surge pattern',
        })

    # ── Cross-theater coordination ──
    high_vectors = sum(1 for lvl in [
        nuclear_level, nato_flank_level, arctic_level, hybrid_level, gnd_level
    ] if lvl >= 3)
    if cross_theater or high_vectors >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'cross_theater_coordination'),
            'status':  'BREACHED' if high_vectors >= 4 else 'APPROACHING',
            'trigger': f'{high_vectors} vectors at L3+ simultaneously -- maximum pressure pattern',
        })

    # ── Hybrid infrastructure attack ──
    if hybrid_signal or hybrid_level >= 3:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'hybrid_infrastructure_attack'),
            'status':  'BREACHED' if hybrid_level >= 4 else 'APPROACHING',
            'trigger': f'Hybrid attack signals detected + hybrid L{hybrid_level}',
        })

    # ── De-escalation signals ──
    if trump_putin_talks:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'trump_putin_diplomatic_engagement'),
            'status':  'APPROACHING',
            'trigger': 'Trump-Putin diplomatic engagement signals detected',
        })

    if ceasefire_signal:
        triggered.append({
            **next(r for r in RED_LINES if r['id'] == 'ukraine_ceasefire_framework'),
            'status':  'APPROACHING',
            'trigger': 'Ukraine ceasefire/negotiations language detected',
        })

    # Sort: BREACHED first, then by severity desc, deescalation last
    triggered.sort(key=lambda x: (
        0 if x['status'] == 'BREACHED' else 1,
        -x['severity'],
        0 if x['category'] != 'deescalation' else 1
    ))
    return triggered


def _score_green_lines(scan_data):
    """Evaluate Russia diplomatic off-ramp signals."""
    actors = scan_data.get('actors', {})
    nuclear_level = scan_data.get('nuclear_level', 0)
    arctic_level  = scan_data.get('arctic_level', 0)

    def _scan_articles(actor_ids, keywords):
        for aid in actor_ids:
            for art in actors.get(aid, {}).get('top_articles', []):
                title = art.get('title', '').lower()
                if any(kw.lower() in title for kw in keywords):
                    return True
        return False

    trump_putin = _scan_articles(
        ['united_states', 'russia_government'],
        ['trump putin meeting', 'trump putin call', 'trump putin talks',
         'us russia summit', 'trump ukraine deal', 'trump russia negotiate']
    )
    ceasefire = _scan_articles(
        ['ukraine', 'united_states', 'russia_government'],
        ['ceasefire ukraine', 'ukraine peace deal', 'peace framework ukraine',
         'ukraine negotiations', 'ukraine peace talks', 'ukraine ceasefire']
    )
    russia_pullback = _scan_articles(
        ['russia_military', 'ukraine', 'russia_government'],
        ['russia withdraws', 'russia pulls back', 'russia reduces troops',
         'russian drawdown', 'russia military reduction',
         'putin ceasefire', 'easter ceasefire', 'russia ceasefire ukraine',
         'putin orders halt', 'putin pause', 'russian troops halt',
         'пасхальное перемирие', 'перемирие путин']
    )
    ukraine_openness = _scan_articles(
        ['ukraine'],
        ['zelenskyy open to talks', 'ukraine willing to negotiate',
         'ukraine ceasefire terms', 'zelenskyy peace proposal',
         'ukraine accepts negotiations', 'ukraine peace conditions',
         'optimistic about talks', 'talks with russia', 'peace talks russia',
         'zelensky office optimistic', 'will not take long', 'compromise sought',
         'us involvement talks', 'negotiations progress']
    )
    nato_russia_dialog = _scan_articles(
        ['nato_alliance', 'russia_government'],
        ['nato russia meeting', 'nato russia talks', 'nato russia dialogue',
         'nato russia deconfliction', 'nato russia hotline']
    )
    arctic_diplomacy = _scan_articles(
        ['arctic_watch', 'nato_alliance'],
        ['arctic council', 'arctic diplomacy', 'arctic cooperation russia',
         'arctic forum russia', 'norway russia arctic talks']
    )

    triggered = []

    if trump_putin:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'trump_putin_talks_active'),
            'status': 'ACTIVE',
            'trigger': 'Trump-Putin direct engagement signals detected',
        })

    if ceasefire:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'ukraine_ceasefire_active'),
            'status': 'ACTIVE' if trump_putin else 'SIGNALED',
            'trigger': 'Ukraine ceasefire/negotiations framework signals detected',
        })

    if russia_pullback:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'russia_military_pullback'),
            'status': 'SIGNALED',
            'trigger': 'Russian military pullback language detected -- verify vs. tactical repositioning',
        })

    if ukraine_openness:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'ukraine_diplomatic_openness'),
            'status': 'SIGNALED',
            'trigger': 'Ukrainian government signals openness to negotiations',
        })

    if nato_russia_dialog:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'nato_russia_hotline_active'),
            'status': 'SIGNALED',
            'trigger': 'NATO-Russia dialogue/deconfliction signals detected',
        })

    if arctic_diplomacy:
        triggered.append({
            **next(g for g in GREEN_LINES if g['id'] == 'arctic_council_reengagement'),
            'status': 'SIGNALED',
            'trigger': 'Arctic Council re-engagement signals detected',
        })

    triggered.sort(key=lambda x: -x['momentum'])
    return triggered


def _score_diplomatic_track(scan_data, green_lines_triggered):
    """Compute diplomatic momentum score 0-100 and detect key conditions."""
    nuclear_level  = scan_data.get('nuclear_level',    0)
    gnd_level      = scan_data.get('ground_ops_level', 0)
    nat_level      = scan_data.get('nato_flank_level', 0)
    arctic_level   = scan_data.get('arctic_level',     0)
    hybrid_level   = scan_data.get('hybrid_level',     0)

    active_lines   = [g for g in green_lines_triggered if g['status'] == 'ACTIVE']
    signaled_lines = [g for g in green_lines_triggered if g['status'] == 'SIGNALED']

    momentum = sum(g['momentum'] * 20 for g in active_lines)
    momentum += sum(g['momentum'] * 10 for g in signaled_lines)
    score = min(100, momentum)

    if score >= 75:
        scenario       = 'BREAKTHROUGH — Active Peace Framework, Settlement Possible'
        scenario_color = '#10b981'
    elif score >= 50:
        scenario       = 'ACTIVE NEGOTIATION — US-Russia Engagement, Momentum Building'
        scenario_color = '#22c55e'
    elif score >= 30:
        scenario       = 'DIPLOMATIC SIGNALS — Off-Ramp Visible, Not Yet Real'
        scenario_color = '#84cc16'
    elif score >= 15:
        scenario       = 'LOW MOMENTUM — Peace Calls, No Framework'
        scenario_color = '#f59e0b'
    else:
        scenario       = 'NO DIPLOMATIC TRACK — Military Logic Dominates'
        scenario_color = '#6b7280'

    # Multi-vector escalation with no diplomatic track = maximum danger
    high_vectors = sum(1 for lvl in [nuclear_level, gnd_level, nat_level, arctic_level, hybrid_level]
                       if lvl >= 3)
    maximum_pressure = high_vectors >= 3 and len(active_lines) == 0

    return {
        'score':            score,
        'scenario':         scenario,
        'scenario_color':   scenario_color,
        'maximum_pressure': maximum_pressure,
        'high_vector_count': high_vectors,
        'active_count':     len(active_lines),
        'signaled_count':   len(signaled_lines),
    }


def _match_historical(scan_data):
    """Match current Russia signals against historical precedents."""
    actors = scan_data.get('actors', {})

    russia_mil_level = actors.get('russia_military',  {}).get('escalation_level', 0)
    russia_gov_level = actors.get('russia_government',{}).get('escalation_level', 0)
    belarus_level    = actors.get('belarus',          {}).get('escalation_level', 0)
    nuclear_level    = scan_data.get('nuclear_level',    0)
    nato_flank_level = scan_data.get('nato_flank_level', 0)
    arctic_level     = scan_data.get('arctic_level',     0)
    hybrid_level     = scan_data.get('hybrid_level',     0)
    gnd_level        = scan_data.get('ground_ops_level', 0)

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

        if 'russia_military_min' in sigs:
            check(russia_mil_level >= sigs['russia_military_min'],
                  f'Russia military L{russia_mil_level} >= L{sigs["russia_military_min"]}', weight=3)
        if 'russia_gov_min' in sigs:
            check(russia_gov_level >= sigs['russia_gov_min'],
                  f'Russia gov L{russia_gov_level} >= L{sigs["russia_gov_min"]}', weight=2)
        if 'nuclear_rhetoric' in sigs:
            check(nuclear_level >= 2,
                  'Nuclear rhetoric elevated', weight=3)
        if 'nato_pressure' in sigs:
            check(nato_flank_level >= 2 == sigs['nato_pressure'],
                  'NATO flank pressure', weight=2)
        if 'belarus_active' in sigs:
            check(belarus_level >= 2 == sigs['belarus_active'],
                  'Belarus active', weight=1)
        if 'hybrid_active' in sigs:
            check(hybrid_level >= 2 == sigs['hybrid_active'],
                  'Hybrid active', weight=1)
        if 'arctic_elevated' in sigs:
            check(arctic_level >= 2, 'Arctic elevated', weight=2)
        if 'ukraine_weak' in sigs:
            check(gnd_level >= 3, 'Ukraine front under pressure', weight=1)

        if max_score == 0:
            continue

        similarity = round((score / max_score) * 100)
        if similarity >= 40:
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


def _build_so_what(scan_data, red_lines_triggered, historical_matches,
                   green_lines_triggered, diplomatic_track):
    """
    Generate Russia command node assessment.
    Five-way analysis: conventional, nuclear, Ukraine, cross-theater, Arctic.
    """
    actors = scan_data.get('actors', {})

    russia_mil_level = actors.get('russia_military',  {}).get('escalation_level', 0)
    russia_gov_level = actors.get('russia_government',{}).get('escalation_level', 0)
    ukraine_level    = actors.get('ukraine',          {}).get('escalation_level', 0)
    nato_level       = actors.get('nato_alliance',    {}).get('escalation_level', 0)
    us_level         = actors.get('united_states',    {}).get('escalation_level', 0)
    baltic_level     = actors.get('baltic_flank',     {}).get('escalation_level', 0)
    arctic_actor     = actors.get('arctic_watch',     {}).get('escalation_level', 0)
    belarus_level    = actors.get('belarus',          {}).get('escalation_level', 0)

    nuclear_level    = scan_data.get('nuclear_level',    0)
    gnd_level        = scan_data.get('ground_ops_level', 0)
    nato_flank_level = scan_data.get('nato_flank_level', 0)
    arctic_level     = scan_data.get('arctic_level',     max(arctic_actor, 0))
    hybrid_level     = scan_data.get('hybrid_level',     0)

    theatre_score = scan_data.get('rhetoric_score', scan_data.get('theatre_score', 0))
    delta = scan_data.get('delta', {}) or {}

    breached_count    = sum(1 for r in red_lines_triggered if r['status'] == 'BREACHED')
    approaching_count = sum(1 for r in red_lines_triggered if r['status'] == 'APPROACHING')
    top_match         = historical_matches[0] if historical_matches else None

    diplomatic_score  = diplomatic_track.get('score', 0)
    maximum_pressure  = diplomatic_track.get('maximum_pressure', False)
    high_vector_count = diplomatic_track.get('high_vector_count', 0)

    # ── Scenario label ──
    if nuclear_level >= 4 or nato_flank_level >= 5:
        scenario       = 'CRITICAL — Nuclear Signaling or NATO Flank Active Threat'
        scenario_color = '#dc2626'
        scenario_icon  = '🔴'
    elif nuclear_level >= 3 or nato_flank_level >= 4 or high_vector_count >= 3:
        scenario       = 'ELEVATED — Multi-Vector Pressure, Escalation Signals Present'
        scenario_color = '#f97316'
        scenario_icon  = '🟠'
    elif russia_mil_level >= 3 or gnd_level >= 3 or nato_flank_level >= 3:
        scenario       = 'WARNING — Russian Military Posture Above Baseline'
        scenario_color = '#f59e0b'
        scenario_icon  = '🟡'
    elif diplomatic_score >= 50:
        scenario       = 'MONITORING — Diplomatic Activity, Military Below Threshold'
        scenario_color = '#3b82f6'
        scenario_icon  = '🔵'
    else:
        scenario       = 'MONITORING — Below Escalation Threshold'
        scenario_color = '#6b7280'
        scenario_icon  = '⚪'

    # ── Situation ──
    situation_parts = []

    if russia_mil_level >= 2 or gnd_level >= 2:
        situation_parts.append(
            f'Russian military posture at L{russia_mil_level} -- '
            f'{"active operations in Ukraine with offensive pressure" if gnd_level >= 3 else "elevated but below major offensive threshold"}. '
            f'Ground ops vector at L{gnd_level}.'
        )

    if nuclear_level >= 2:
        situation_parts.append(
            f'Nuclear signaling at L{nuclear_level} -- '
            f'{"above baseline, Kremlin/Medvedev escalatory language detected" if nuclear_level >= 3 else "routine deterrence language, monitor for escalation"}. '
            f'Note: Medvedev is the designated nuclear coercion instrument; his statements are deliberate signals, not noise.'
        )

    if nato_flank_level >= 2:
        situation_parts.append(
            f'NATO eastern flank pressure at L{nato_flank_level} -- '
            f'{"Baltic/Kaliningrad signals above baseline, Suwalki Gap watch active" if nato_flank_level >= 3 else "routine NATO-Russia friction"}. '
            f'Baltic flank actor at L{baltic_level}.'
        )

    if arctic_level >= 2:
        situation_parts.append(
            f'Arctic signals at L{arctic_level} -- '
            f'{"Northern Fleet/SSBN activity above baseline" if arctic_level >= 3 else "elevated above quiet baseline"}. '
            f'GIUK Gap is NATO\'s primary Atlantic vulnerability -- watch for submarine surge.'
        )

    if high_vector_count >= 3:
        situation_parts.append(
            f'MAXIMUM PRESSURE PATTERN: {high_vector_count} vectors simultaneously at L3+ -- '
            f'Russia coordinating pressure across multiple domains. '
            f'This pattern has no post-Cold War precedent at this vector count.'
        )

    if diplomatic_score >= 30:
        situation_parts.append(
            f'DIPLOMATIC TRACK ACTIVE (score {diplomatic_score}/100): '
            f'{diplomatic_track.get("scenario", "")}. '
            f'Trump-Putin engagement is the primary off-ramp variable. '
            f'Watch Ukraine territorial concessions language as the key indicator.'
        )

    # ── Key indicators ──
    indicators = []

    if nuclear_level >= 3:
        indicators.append(
            'NUCLEAR SIGNALING WATCH: Russia nuclear rhetoric above baseline. '
            'Key distinction: coercive posturing (Medvedev) vs. doctrinal shift (Putin direct). '
            'Watch for: Iskander nuclear warhead movement, SSBN deployment orders, '
            'strategic force readiness changes.'
        )

    if maximum_pressure:
        indicators.append(
            f'MAXIMUM PRESSURE: {high_vector_count} vectors at L3+ with no diplomatic track -- '
            'this is the most dangerous configuration. Russia is applying simultaneous pressure '
            'across nuclear, conventional, NATO flank, Arctic, and hybrid domains '
            'with no diplomatic channel absorbing the pressure.'
        )

    if arctic_level >= 3:
        indicators.append(
            'ARCTIC ELEVATED: Northern Fleet/SSBN signals above quiet baseline. '
            'Historical pattern: SSBN surges preceded major Soviet/Russian diplomatic pressure '
            'campaigns by 2-4 weeks. Cross-reference with Greenland tracker for convergence. '
            'GIUK Gap submarine activity threatens NATO Atlantic LOCs.'
        )

    if hybrid_level >= 3:
        indicators.append(
            'HYBRID WARFARE SIGNALS: Cross-theater coordination detected -- '
            'Iran weapons supply to Russia, DPRK ammunition transfers, '
            'Cuba/Venezuela WHA presence signals. '
            'Russia is building a structured counter-NATO alliance across all theaters.'
        )

    if breached_count >= 1:
        indicators.append(
            f'{breached_count} red line(s) currently breached -- '
            f'signals that historically precede Russian kinetic or escalatory action.'
        )

    if diplomatic_score >= 50:
        indicators.append(
            'DIPLOMATIC OFF-RAMP: Trump-Putin engagement creates potential Ukraine settlement path. '
            'Watch: Ukraine territorial concessions language, US sanctions relief signals, '
            'Zelenskyy NATO membership demands softening. '
            'Any Ukraine ceasefire would fundamentally reduce Russia threat posture to NATO.'
        )

    # ── Assessment ──
    assessment_parts = []

    if top_match and top_match['similarity'] >= 50:
        assessment_parts.append(
            f'Signal pattern shows {top_match["similarity"]}% similarity to '
            f'{top_match["label"]}. Outcome: {top_match["outcome"].lower()}'
        )
        assessment_parts.append(
            f'Confidence: {top_match["confidence"]}. '
            f'Historical response window: {top_match["window_hours"]}h.'
        )

    if diplomatic_score >= 30:
        assessment_parts.append(
            f'However: diplomatic track at {diplomatic_score}/100 introduces off-ramp potential. '
            f'Unlike 2022, Trump-Putin engagement creates structural possibility of Ukraine settlement. '
            f'If settlement emerges, Russian pressure on NATO flanks reduces significantly.'
        )

    # ── Watch list ──
    watch_items = []

    if diplomatic_score >= 30:
        watch_items.append(
            'Trump-Putin engagement -- watch for: Ukraine territorial deal language, '
            'Zelenskyy NATO membership demand softening, US sanctions relief signals'
        )

    watch_items += [
        'Medvedev nuclear language escalation -- specific threat vs. routine deterrence (key distinction)',
        f'Northern Fleet/SSBN deployment patterns -- Arctic L{arctic_level}, watch for surge above baseline',
        'Kaliningrad Iskander deployment signals -- Suwalki Gap is the NATO Baltic connectivity tripwire',
        'DPRK ammunition + Iran weapons transfers to Russia -- cross-theater coordination building',
        'Ukrainian front cohesion -- Russian gains embolden NATO pressure; losses trigger desperation signals',
        'Belarus military buildup near Polish/Lithuanian border -- Suwalki Gap secondary indicator',
    ]

    return {
        'scenario':                scenario,
        'scenario_color':          scenario_color,
        'scenario_icon':           scenario_icon,
        'situation':               ' '.join(situation_parts),
        'key_indicators':          indicators,
        'assessment':              ' '.join(assessment_parts),
        'watch_list':              watch_items[:6],
        'nuclear_elevated':        nuclear_level >= 3,
        'arctic_elevated':         arctic_level >= 3,
        'maximum_pressure':        maximum_pressure,
        'high_vector_count':       high_vector_count,
        'diplomatic_score':        diplomatic_score,
        'diplomatic_scenario':     diplomatic_track.get('scenario', ''),
        'diplomatic_scenario_color': diplomatic_track.get('scenario_color', '#6b7280'),
        'generated_at':            datetime.now(timezone.utc).isoformat(),
        'confidence_note': (
            'Russia assessment generated from open-source signal data. '
            'Not a prediction. Verify through official channels. '
            'Nuclear signaling distinction (coercion vs. doctrine) and '
            'Arctic baseline judgments are analytical estimates. '
            'Cross-theater coordination signals require multi-source verification.'
        ),
    }


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def interpret_signals(scan_data):
    """
    Main entry point. Called from rhetoric_tracker_russia.py or app.py.
    Returns interpretation dict.
    """
    try:
        red_lines   = _score_red_lines(scan_data)
        green_lines = _score_green_lines(scan_data)
        diplomatic  = _score_diplomatic_track(scan_data, green_lines)
        historical  = _match_historical(scan_data)
        so_what     = _build_so_what(scan_data, red_lines, historical,
                                     green_lines, diplomatic)

        breached    = [r for r in red_lines if r['status'] == 'BREACHED']
        approaching = [r for r in red_lines if r['status'] == 'APPROACHING']
        active_gl   = [g for g in green_lines if g['status'] == 'ACTIVE']

        return {
            'so_what':             so_what,
            'red_lines': {
                'triggered':         red_lines,
                'breached_count':    len(breached),
                'approaching_count': len(approaching),
                'highest_severity':  max((r['severity'] for r in red_lines), default=0),
            },
            'green_lines': {
                'triggered':         green_lines,
                'active_count':      len(active_gl),
                'signaled_count':    len(green_lines) - len(active_gl),
                'diplomatic_score':  diplomatic['score'],
            },
            'diplomatic_track':    diplomatic,
            'historical_matches':  historical,
            'interpreter_version': '1.0.0',
            'interpreted_at':      datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f'[Russia Interpreter] Error: {str(e)[:120]}')
        return {
            'so_what':            {'scenario': 'Interpreter error', 'assessment': str(e)[:200]},
            'red_lines':          {'triggered': [], 'breached_count': 0, 'approaching_count': 0, 'highest_severity': 0},
            'green_lines':        {'triggered': [], 'active_count': 0, 'signaled_count': 0, 'diplomatic_score': 0},
            'diplomatic_track':   {'score': 0, 'scenario': 'Unknown', 'maximum_pressure': False},
            'historical_matches': [],
            'interpreter_version': '1.0.0',
            'error':              str(e)[:200],
        }


# ============================================================
# STANDALONE TEST
# ============================================================
if __name__ == '__main__':
    # Simulate current conditions: Ukraine war ongoing, nuclear rhetoric
    # present, Trump-Putin talks emerging, Arctic at baseline
    test_data = {
        'rhetoric_score':    55,
        'nuclear_level':     3,
        'ground_ops_level':  3,
        'nato_flank_level':  2,
        'arctic_level':      1,
        'hybrid_level':      3,
        'delta': {'direction': 'stable', 'score_change': 0},
        'actors': {
            'russia_military': {'escalation_level': 3, 'statement_count': 45, 'top_articles': [
                {'title': 'Russian forces advance in Zaporizhzhia region, capturing two villages', 'published': ''},
                {'title': 'Russia launches massive drone attack on Ukraine energy infrastructure', 'published': ''},
            ]},
            'russia_government': {'escalation_level': 3, 'statement_count': 30, 'top_articles': [
                {'title': 'Medvedev nuclear warning if NATO intervenes directly in Ukraine', 'published': ''},
                {'title': 'Putin warns consequences for countries supplying long-range missiles to Ukraine', 'published': ''},
            ]},
            'ukraine': {'escalation_level': 2, 'statement_count': 20, 'top_articles': [
                {'title': 'Zelenskyy open to peace negotiations if security guarantees provided', 'published': ''},
                {'title': 'Ukrainian forces hold line in Donbas despite Russian pressure', 'published': ''},
            ]},
            'nato_alliance': {'escalation_level': 2, 'statement_count': 15, 'top_articles': [
                {'title': 'NATO reinforces eastern flank with additional battle groups', 'published': ''},
            ]},
            'united_states': {'escalation_level': 2, 'statement_count': 18, 'top_articles': [
                {'title': 'Trump Putin direct talks on Ukraine peace deal scheduled', 'published': ''},
                {'title': 'US considers Ukraine minerals deal as part of ceasefire framework', 'published': ''},
            ]},
            'baltic_flank': {'escalation_level': 2, 'statement_count': 8, 'top_articles': [
                {'title': 'Estonia Latvia Lithuania boost defense spending amid Russian threats', 'published': ''},
            ]},
            'arctic_watch': {'escalation_level': 1, 'statement_count': 2, 'top_articles': [
                {'title': 'Russian Northern Fleet conducts routine patrol exercise in Barents Sea', 'published': ''},
            ]},
            'belarus': {'escalation_level': 2, 'statement_count': 5, 'top_articles': [
                {'title': 'Russia deploys additional troops to Belarus for joint exercises', 'published': ''},
            ]},
        },
    }

    result = interpret_signals(test_data)

    print('\n' + '='*70)
    print('MILITARY SCENARIO:', result['so_what']['scenario'])
    print('DIPLOMATIC SCENARIO:', result['so_what'].get('diplomatic_scenario', 'None'))
    print(f'DIPLOMATIC SCORE: {result["so_what"].get("diplomatic_score", 0)}/100')
    print(f'NUCLEAR ELEVATED: {result["so_what"].get("nuclear_elevated", False)}')
    print(f'ARCTIC ELEVATED: {result["so_what"].get("arctic_elevated", False)}')
    print(f'MAXIMUM PRESSURE: {result["so_what"].get("maximum_pressure", False)}')
    print(f'HIGH VECTOR COUNT: {result["so_what"].get("high_vector_count", 0)}')
    print('='*70)
    print('\nSITUATION (excerpt):')
    print(result['so_what']['situation'][:400])
    print('\nKEY INDICATORS:')
    for ind in result['so_what']['key_indicators']:
        print(f'  -- {ind[:120]}')
    print('\nWATCH LIST:')
    for item in result['so_what']['watch_list']:
        print(f'  -> {item[:100]}')
    print('\nRED LINES:')
    for rl in result['red_lines']['triggered']:
        print(f'  {rl["icon"]} [{rl["status"]}] {rl["label"]} (Sev {rl["severity"]}) [{rl["category"]}]')
    print('\nGREEN LINES:')
    for gl in result['green_lines']['triggered']:
        print(f'  {gl["icon"]} [{gl["status"]}] {gl["label"]} (Momentum {gl["momentum"]})')
    print('\nHISTORICAL MATCHES:')
    for hm in result['historical_matches']:
        print(f'  {hm["similarity"]}% -- {hm["label"]} | Confidence: {hm["confidence"]}')
    print(f'\nDIPLOMATIC TRACK: score={result["diplomatic_track"]["score"]}, '
          f'max_pressure={result["diplomatic_track"]["maximum_pressure"]}')
