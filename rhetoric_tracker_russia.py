"""
Asifah Analytics -- Russia Rhetoric & Pressure Tracker
Europe Backend Module
v1.0.0 -- April 2026

ANALYTICAL FRAME:
This tracker answers five questions simultaneously:


  1. Is Russia signaling conventional escalation on NATO's eastern flank?
     (Baltic states, Poland, Finland, Kaliningrad, Belarus)
  2. Is nuclear rhetoric coercive posturing vs. genuine doctrinal signal?
     (Medvedev/Putin language ladder, Iskander deployments, SSBN signals)
  3. Is the Ukraine war trajectory shifting?
     (Russian gains = emboldened; Russian losses = desperate escalation)
  4. Is Russia coordinating cross-theater pressure?
     (Iran weapons supply, DPRK ammunition, Cuba/Venezuela WHA, Arctic)
  5. Are Arctic / GIUK Gap signals above baseline?
     (Northern Fleet, SSBN patrols, Svalbard, undersea infrastructure)

INVERTED MODEL NOTE:
Unlike standard outbound trackers (China, Iran), Russia requires tracking
BOTH outbound pressure signals AND inbound NATO/partner responses.
Russia's escalation ladder is multi-flank -- it can pressure NATO via:
  - Ukraine kinetics
  - Baltic/Kaliningrad threats
  - Arctic/GIUK posturing
  - Hybrid (cyber, energy, disinformation)
  - Nuclear signaling
  - Cross-theater coordination (Iran, DPRK, Cuba)

All five simultaneously is the maximum pressure scenario.

ACTORS (8):
  russia_military      -- MoD, Gerasimov, General Staff operational signals
  russia_government    -- Putin/Kremlin/Lavrov political rhetoric
  ukraine              -- Resistance signals + diplomatic posture (dual)
  nato_alliance        -- Collective NATO response signals
  united_states        -- US-Russia bilateral, Ukraine aid, sanctions
  baltic_flank         -- Estonia/Latvia/Lithuania/Poland/Finland threat reception
  arctic_watch         -- Northern Fleet, SSBN, Svalbard, GIUK (quiet baseline)
  belarus              -- Lukashenko, force multiplier, Suwalki Gap

VECTORS (5):
  nuclear    -- Rhetoric ladder, Iskander, SSBN, doctrinal shifts
  ground_ops -- Ukraine front movement, Russian advance/retreat
  nato_flank -- Baltic/Poland/Finland pressure signals
  arctic     -- Northern Fleet, SSBN patrols, Arctic territorial claims
  hybrid     -- Cyber, energy weaponization, disinformation, Wagner/Africa

REDIS KEYS:
  Cache:         rhetoric:russia:latest
  History:       rhetoric:russia:history
  Cross-theater: rhetoric:crosstheater:fingerprints (WRITES)
  Summary:       rhetoric:russia:summary

ENDPOINTS:
  GET /api/rhetoric/russia
  GET /api/rhetoric/russia/summary
  GET /api/rhetoric/russia/history

SOURCE STRATEGY:
  Primary RSS:  MoD Russia (EN), RT (archived/GDELT only -- banned in EU),
                Kyiv Independent, UAWire, Meduza EN, Bellingcat,
                USNI News, ISW, RFERL, The Insider
  GDELT:        eng, rus, ukr -- multi-language
  Telegram:     routed through telegram_signals_europe shared cache
  Nitter:       ISW, MoD Ukraine, NATO, SecDef, StateDept, OSINTdefender

CHANGELOG:
  v1.0.0 (2026-04-10): Initial build -- five-vector, multi-flank architecture

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
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

# Telegram signals (optional — graceful fallback if unavailable)
try:
    from telegram_signals_europe import fetch_russia_telegram_signals
    TELEGRAM_AVAILABLE = True
    print("[Russia Rhetoric] ✅ Telegram signals available")
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[Russia Rhetoric] ⚠️ Telegram signals not available -- RSS/GDELT only")

# ============================================
# CONFIG
# ============================================from flask import jsonify, request

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
GDELT_BASE_URL      = 'https://api.gdeltproject.org/api/v2/doc/doc'

RHETORIC_CACHE_KEY  = 'rhetoric:russia:latest'
HISTORY_KEY         = 'rhetoric:russia:history'
SUMMARY_KEY         = 'rhetoric:russia:summary'
CROSSTHEATER_KEY    = 'rhetoric:crosstheater:fingerprints'

RHETORIC_CACHE_TTL  = 12 * 3600
SCAN_INTERVAL_HOURS = 12

_rhetoric_running = False
_rhetoric_lock    = threading.Lock()


# ============================================
# ESCALATION LEVELS
# ============================================
ESCALATION_LEVELS = {
    0: {'label': 'Baseline',        'color': '#6b7280', 'description': 'Routine statements, no significant signals above noise'},
    1: {'label': 'Rhetoric',        'color': '#3b82f6', 'description': 'Standard sovereignty / NATO threat language, formulaic warnings'},
    2: {'label': 'Warning',         'color': '#f59e0b', 'description': 'Elevated exercise tempo, escalatory Kremlin/MoD language'},
    3: {'label': 'Confrontation',   'color': '#f97316', 'description': 'Named exercises, explicit threat signals, nuclear rhetoric above baseline'},
    4: {'label': 'Coercion',        'color': '#ef4444', 'description': 'Active nuclear signaling, Baltic/Arctic incident, hybrid attack confirmed'},
    5: {'label': 'Active Conflict', 'color': '#dc2626', 'description': 'Confirmed military action, Article 5 trigger, nuclear use threatened directly'},
}


# ============================================
# ACTORS
# ============================================
ACTORS = {

    # ── OUTBOUND: RUSSIAN PRESSURE ACTORS ────────────────────────

    'russia_military': {
        'name': 'Russia (Military)',
        'flag': '🇷🇺',
        'icon': '⚔️',
        'color': '#dc2626',
        'role': 'MoD / General Staff — Operational Pressure',
        'description': (
            'Russian MoD, Gerasimov, General Staff operational signals. '
            'Watch for: named exercises near NATO flanks, Iskander deployments, '
            'Northern Fleet activity, SSBN patrol signals, Ukraine advance language.'
        ),
        'keywords': [
            # Core military operations
            'russian military', 'russian forces', 'russian army',
            'gerasimov', 'russian general staff', 'russian mod',
            'russian defense ministry', 'russian ministry of defense',
            'russian troops', 'russian soldiers', 'russian army',
            # Ukraine operations
            'russian advance ukraine', 'russian offensive ukraine',
            'russian strike ukraine', 'russian attack ukraine',
            'russian bombardment', 'russian missile strike',
            'russian drone attack ukraine', 'shahed drone',
            'russian artillery ukraine', 'russian tank ukraine',
            'zaporizhzhia front', 'kherson front', 'donbas front',
            'bakhmut', 'avdiivka', 'kursk', 'zaporizhzhia',
            'russian gains ukraine', 'russian captures',
            # NATO flank pressure
            'russian exercise nato', 'russian drill nato border',
            'zapad exercise', 'kavkaz exercise', 'vostok exercise',
            'russian forces kaliningrad', 'kaliningrad military',
            'iskander deployment', 'iskander kaliningrad',
            'russian troops belarus', 'russian military belarus',
            'russian forces finland border', 'murmansk military',
            # Nuclear signals
            'nuclear doctrine russia', 'russia nuclear threat',
            'russia nuclear warning', 'nuclear weapons russia',
            'sarmat missile', 'poseidon torpedo', 'kinzhal missile',
            'russia launches nuclear drill', 'nuclear exercise russia',
            'strategic missile forces russia',
            # Arctic
            'northern fleet russia', 'russian arctic military',
            'russian ssbn patrol', 'russian submarine arctic',
            'russian icebreaker military', 'arctic exercises russia',
            'svalbard russia military', 'giuk gap russia',
            # Russian
            'Министерство обороны России', 'Генеральный штаб',
            'Герасимов', 'российская армия', 'вооружённые силы России',
            'российские войска', 'российский удар',
        ],
        'baseline_statements_per_week': 25,
        'tripwires': [
            'iskander deployment nato',
            'nuclear drill russia',
            'northern fleet deployment',
            'russian forces enter',
            'russia fires missiles nato',
            'russia attacks nato',
        ],
    },

    'russia_government': {
        'name': 'Russia (Government)',
        'flag': '🇷🇺',
        'icon': '🏛️',
        'color': '#b91c1c',
        'role': 'Putin / Kremlin / Lavrov — Political Rhetoric',
        'description': (
            'Putin statements, Kremlin readouts, Lavrov/MFA rhetoric, Medvedev. '
            'The key signal is ESCALATORY LANGUAGE above Kremlin baseline. '
            'Medvedev nuclear rhetoric is deliberate signaling, not noise. '
            'Putin red line language historically precedes kinetic action.'
        ),
        'keywords': [
            # Putin direct
            'putin says', 'putin warns', 'putin threatens',
            'putin speech', 'putin address', 'putin statement',
            'putin ukraine', 'putin nato', 'putin nuclear',
            'putin red line', 'putin orders', 'putin demands',
            'putin ultimatum', 'putin security guarantee',
            # Kremlin
            'kremlin warns', 'kremlin says', 'kremlin threatens',
            'kremlin statement', 'kremlin ukraine', 'kremlin nato',
            'kremlin red line', 'peskov says', 'peskov warns',
            'dmitry peskov', 'kremlin spokesperson',
            # Lavrov / MFA
            'lavrov warns', 'lavrov says', 'lavrov ukraine',
            'lavrov nato', 'russian foreign ministry',
            'russian mfa warns', 'russia foreign ministry',
            # Medvedev -- nuclear coercion instrument
            'medvedev nuclear', 'medvedev warns', 'medvedev threatens',
            'medvedev nato', 'medvedev ukraine',
            'medvedev says', 'medvedev statement',
            # Specific rhetoric patterns
            'existential threat russia', 'russia red line',
            'russia will respond', 'russia will not tolerate',
            'consequences for russia', 'russia security guarantee',
            'nato expansion red line', 'nato threat russia',
            'collective west russia', 'russia sovereignty',
            'special military operation', 'denazification ukraine',
            'russia defeats nato', 'russia wins ukraine',
            'ukraine peace terms russia', 'ceasefire terms russia',
            'trump putin talks', 'russia us negotiations',
            'minerals deal russia ukraine', 'ukraine resources russia',
            # Russian
            'Путин', 'Кремль', 'Лавров', 'Медведев',
            'ядерное оружие', 'красная линия', 'НАТО угроза',
            'специальная военная операция', 'коллективный Запад',
        ],
        'baseline_statements_per_week': 20,
        'tripwires': [
            'putin red line nato',
            'medvedev nuclear use',
            'russia will use nuclear',
            'existential threat justifies',
            'putin ultimatum ukraine',
            'russia demands nato withdrawal',
        ],
    },

    # ── INBOUND: TARGET / RESPONSE ACTORS ────────────────────────

    'ukraine': {
        'name': 'Ukraine',
        'flag': '🇺🇦',
        'icon': '🛡️',
        'color': '#2563eb',
        'role': 'Resistance + Diplomatic Signals (dual)',
        'description': (
            'Ukraine tracked on TWO dimensions: '
            '(1) MILITARY RESISTANCE -- front signals, Zelenskyy defense posture; '
            '(2) DIPLOMATIC POSTURE -- Ukraine position on negotiations, Trump pressure, '
            'ceasefire terms, territorial concessions language. '
            'Military signals → escalation vector. Diplomatic signals → green lines.'
        ),
        'keywords': [
            # Military resistance
            'ukraine military', 'ukrainian forces', 'ukrainian army',
            'zelenskyy', 'zelensky', 'ukraine defense',
            'ukraine counterattack', 'ukraine advance',
            'ukraine holds line', 'ukraine repels',
            'ukraine drone attack russia', 'ukraine strikes russia',
            'ukraine hits russia', 'ukraine long range strike',
            'ukraine f-16', 'ukraine air defense',
            'ukraine patriot', 'ukraine missile defense',
            'ukraine mobilization', 'ukraine conscription',
            'ukrainian casualties', 'ukraine losses',
            'ukraine ammunition', 'ukraine weapons',
            # Diplomatic posture
            'zelenskyy peace', 'ukraine peace talks',
            'ukraine ceasefire', 'ukraine negotiations',
            'ukraine territorial', 'ukraine concessions',
            'ukraine nato membership', 'ukraine security guarantees',
            'zelenskyy trump', 'ukraine minerals deal',
            'ukraine us aid', 'ukraine europe aid',
            'zelenskyy nato', 'ukraine eu',
            # Domestic signals
            'ukraine elections', 'ukraine stability',
            'zelenskyy approval', 'ukraine parliament',
            'ukraine reconstruction', 'ukraine economy',
            # Ukrainian
            'Зеленський', 'Україна', 'ЗСУ', 'Збройні сили України',
        ],
        'baseline_statements_per_week': 15,
        'tripwires': [
            'ukraine strikes moscow',
            'ukraine hits russian territory',
            'ukraine activates full mobilization',
            'zelenskyy declares war emergency',
        ],
    },

    'nato_alliance': {
        'name': 'NATO Alliance',
        'flag': '🌐',
        'icon': '🛡️',
        'color': '#1d4ed8',
        'role': 'Collective NATO Response',
        'description': (
            'NATO SecGen, Supreme Allied Commander Europe (SACEUR), '
            'collective alliance response signals. '
            'Watch for: Article 5 invocations, enhanced forward presence changes, '
            'VJTF activation, NATO emergency meetings.'
        ),
        'keywords': [
            'nato russia', 'nato warns russia', 'nato responds russia',
            'nato ukraine', 'nato aid ukraine', 'nato support ukraine',
            'nato article 5', 'nato collective defense',
            'nato eastern flank', 'nato eastern europe',
            'nato enhanced presence', 'nato forward presence',
            'nato battle group', 'nato reinforcement',
            'nato exercises', 'nato drill russia',
            'nato secretary general', 'rutte nato',
            'mark rutte russia', 'saceur', 'nato supreme commander',
            'nato summit', 'nato emergency', 'nato meeting russia',
            'nato response russia', 'nato condemns russia',
            'nato vjtf', 'nato rapid response',
            'nato air policing', 'nato baltic air policing',
            'nato black sea', 'nato arctic', 'nato arctic strategy',
            'nato finland', 'nato sweden', 'nato enlargement',
            'nato ukraine membership', 'nato article 4',
            'nato intelligence russia', 'nato sanctions russia',
        ],
        'baseline_statements_per_week': 10,
        'tripwires': [
            'nato article 5 invoked',
            'nato vjtf activated',
            'nato emergency session russia',
            'nato combat operations russia',
            'nato declares russia aggressor',
        ],
    },

    'united_states': {
        'name': 'United States',
        'flag': '🇺🇸',
        'icon': '🦅',
        'color': '#1e40af',
        'role': 'Primary Adversary / Ukraine Patron',
        'description': (
            'US-Russia bilateral signals, Ukraine aid, sanctions, Trump-Putin diplomacy. '
            'Trump administration posture toward Russia is analytically complex: '
            'simultaneously potential Ukraine peace broker AND sanctions lever. '
            'Watch for: US aid suspension signals, Trump-Putin meeting language, '
            'US sanctions escalation/rollback.'
        ),
        'keywords': [
            'us russia', 'united states russia', 'america russia',
            'trump russia', 'trump putin', 'trump ukraine',
            'trump zelenskyy', 'trump ceasefire ukraine',
            'us ukraine aid', 'us weapons ukraine',
            'us military aid ukraine', 'us sanctions russia',
            'us treasury russia', 'sanctions russia',
            'us nato russia', 'pentagon russia',
            'secretary defense russia', 'hegseth russia',
            'state department russia', 'rubio russia',
            'us ambassador russia', 'us embassy russia',
            'us intelligence russia', 'us warns russia',
            'us red line russia', 'us response russia',
            'us missile defense russia', 'us troops europe',
            'us reinforces europe', 'us troops nato',
            'us nuclear posture russia', 'us nuclear russia',
            'us minerals ukraine', 'ukraine minerals deal us',
            'us peace deal ukraine', 'us broker ukraine',
        ],
        'baseline_statements_per_week': 12,
        'tripwires': [
            'us suspends ukraine aid',
            'trump lifts russia sanctions',
            'us troops engage russia',
            'us nuclear posture elevated',
            'trump recognizes russian territory',
        ],
    },

    'baltic_flank': {
        'name': 'Baltic / Eastern Flank',
        'flag': '🏰',
        'icon': '🚨',
        'color': '#7c3aed',
        'role': 'Estonia / Latvia / Lithuania / Poland / Finland — Threat Reception',
        'description': (
            'Baltic states, Poland, and Finland are the primary targets of Russian '
            'pressure on NATO\'s eastern flank. Track: military buildup on borders, '
            'Suwalki Gap signals, Kaliningrad threats, Finnish border incidents, '
            'Baltic air defense activations, underground infrastructure threats.'
        ),
        'keywords': [
            # Baltic states
            'estonia russia', 'latvia russia', 'lithuania russia',
            'estonia military', 'latvia military', 'lithuania military',
            'baltic russia threat', 'baltic security',
            'estonia nato', 'latvia nato', 'lithuania nato',
            'tallinn russia', 'riga russia', 'vilnius russia',
            # Poland
            'poland russia', 'poland military', 'poland nato',
            'polish forces', 'poland border russia',
            'warsaw russia', 'poland defense',
            # Finland
            'finland russia border', 'finland military russia',
            'helsinki russia', 'finland nato russia',
            'finland border incident', 'finland air defense',
            # Kaliningrad / Suwalki
            'kaliningrad', 'suwalki gap', 'suwalki corridor',
            'kaliningrad military', 'kaliningrad iskander',
            'kaliningrad nuclear', 'russia kaliningrad',
            # Hybrid threats
            'baltic cable cut', 'undersea cable russia',
            'baltic pipeline russia', 'infrastructure attack baltic',
            'russian sabotage baltic', 'russian spy baltic',
            'russian hybrid baltic', 'russian disinformation baltic',
            # Air / border incidents
            'russian aircraft baltic', 'russian jet estonia',
            'russian drone finland', 'russian missile finland',
            'russian border provocations', 'nato air policing',
            'russian violation airspace', 'russian fighter nato',
        ],
        'baseline_statements_per_week': 8,
        'tripwires': [
            'russian forces cross into nato',
            'kaliningrad nuclear deployment',
            'suwalki gap closed',
            'baltic cable severed russia',
            'estonia latvia lithuania attack',
            'finland border incident armed',
        ],
    },

    'arctic_watch': {
        'name': 'Arctic Watch',
        'flag': '🧊',
        'icon': '🧊',
        'color': '#0891b2',
        'role': 'Northern Fleet / SSBN / GIUK Gap — Baseline Monitor',
        'description': (
            'Arctic signals are QUIET BASELINE -- the tracker watches for spikes. '
            'Key signals: Northern Fleet unusual activity, SSBN deployments above normal, '
            'Svalbard territorial claims, GIUK Gap submarine activity, '
            'Russian Arctic military buildup, undersea infrastructure threats. '
            'When Greenland rhetoric rises simultaneously, this is a convergence signal.'
        ),
        'keywords': [
            # Northern Fleet
            'northern fleet russia', 'russian northern fleet',
            'northern fleet deployment', 'northern fleet exercise',
            'murmansk military', 'severomorsk',
            # SSBN / submarines
            'russian ssbn', 'russian submarine arctic',
            'russian ballistic missile submarine',
            'russian submarine deployment', 'russian sub patrol',
            'russian nuclear submarine', 'borei submarine',
            'russian submarine north atlantic', 'ssbn patrol',
            # GIUK Gap
            'giuk gap', 'greenland iceland uk gap',
            'russian submarine atlantic', 'nato sub hunting',
            'p-8 russia patrol', 'russian submarine nato',
            # Arctic territorial
            'russia arctic claim', 'russia arctic territory',
            'russia arctic shelf', 'arctic sovereignty russia',
            'russia north pole', 'russia arctic base',
            'russian arctic troops', 'russian arctic exercise',
            'russia svalbard', 'svalbard russia',
            'svalbard military', 'svalbard tensions',
            # Arctic infrastructure
            'russia arctic pipeline', 'russia arctic lng',
            'arctic shipping russia', 'northern sea route russia',
            'russia arctic icebreaker', 'russia nuclear icebreaker',
            # Cross-theater with Greenland
            'greenland russia', 'russia greenland military',
            'greenland giuk', 'arctic nato russia',
        ],
        'baseline_statements_per_week': 3,
        'silence_alert': False,
        'tripwires': [
            'russian ssbn deployment unusual',
            'northern fleet full deployment',
            'russia closes arctic airspace',
            'russia svalbard military action',
            'giuk gap russian submarine surge',
        ],
    },

    'belarus': {
        'name': 'Belarus',
        'flag': '🇧🇾',
        'icon': '⚠️',
        'color': '#f59e0b',
        'role': 'Russian Force Multiplier / Suwalki Gap',
        'description': (
            'Lukashenko as Russian force multiplier. '
            'Belarus is the northern flank threat to Ukraine AND '
            'the Suwalki Gap threat to NATO Baltic connectivity. '
            'Watch for: Russian troops massing in Belarus, '
            'Belarusian military exercises near Polish/Lithuanian border, '
            'nuclear weapons in Belarus signals.'
        ),
        'keywords': [
            'lukashenko', 'belarus russia', 'belarusian military',
            'russia troops belarus', 'russian forces belarus',
            'russia deploys belarus', 'russian military belarus',
            'russia nuclear belarus', 'nuclear weapons belarus',
            'belarus nato threat', 'belarus ukraine border',
            'russia belarus joint', 'union state military',
            'lukashenko russia', 'lukashenko military',
            'lukashenko threatens', 'lukashenko ukraine',
            'belarus exercises', 'belarus military exercise',
            'belarus troops border', 'belarusian forces',
            'minsk russia', 'belarus security',
        ],
        'baseline_statements_per_week': 4,
        'tripwires': [
            'russian nuclear belarus deployed',
            'belarus troops enter ukraine',
            'russia launches from belarus',
            'lukashenko authorizes attack',
        ],
    },

    # ============================================
    # v1.1.0 (April 2026) — Russia-Iran Axis actor
    # Split from generic hybrid vector into dedicated actor
    # for accurate attribution. Mirrors the China-Iran split
    # on the Iran tracker. Russia's role is distinct from China's:
    # Russia = launch partner, strategic arms, intelligence sharing.
    # China = ISR enabler, dual-use logistics. Both real, different.
    # ============================================
    'russia_iran_axis': {
        'name': 'Russia → Iran (Axis Support)',
        'flag': '🇮🇷',
        'icon': '🚀',
        'color': '#dc2626',
        'role': 'External Support to Iran — Launch / Arms / Coordination / Mediation',
        'description': (
            'Russia as active supporter of Iran. '
            'Sub-categorized across: launch partnership (Russian rockets '
            'carrying Iranian satellites), arms transfers, intelligence '
            'sharing (incl. satellite targeting data for IRGC strikes on '
            'US installations), strategic coordination, and diplomatic / '
            'mediation cover (top-level meetings, UN Security Council '
            'vetoes, mediation channel substitution when other tracks stall). '
            'Watch for: Russian targeting-data allegations, joint defense '
            'announcements, Iranian satellite launches via Soyuz, '
            'Putin-Araghchi-level coordination, UN Hormuz vetoes, '
            'uranium handover offers (JCPOA pattern).'
        ),
        'keywords': [
            # Launch partnership / space
            'russia launches iranian satellite', 'russian rocket iran',
            'russia iran satellite launch', 'soyuz iran satellite',
            'iranian satellite russian launch', 'noor russia launch',
            # Intelligence / targeting
            'russia satellite iran', 'russia targeting iran',
            'russia intelligence iran', 'russia iran targeting us',
            'russian targeting data iran', 'russia satellite irgc',
            'russia satellite imagery iran', 'satellite imagery warship iran',
            'russia warship locations iran',
            # Arms / hardware
            'russia arms iran', 'russia weapons iran',
            'russia supplies iran', 'russian s-400 iran',
            'russian jets iran', 'sukhoi iran', 'russia air defense iran',
            'advanced drones russia iran', 'shahed russia iran',
            'russia drone delivery iran',
            # Strategic coordination
            'moscow tehran military', 'russia iran defense pact',
            'russia backs iran war', 'russia iran cooperation war',
            'comprehensive partnership iran russia',
            'russia iran military coordination',
            # ── v2.1 — TOP-LEVEL DIPLOMATIC COORDINATION (Apr 2026) ──
            # Single-word + short-phrase triggers that match real article text.
            'araghchi',
            'mojtaba khamenei',
            'mojtaba',
            'iran foreign minister',
            'iranian foreign minister',
            'iran fm',
            'foreign minister moscow',
            'foreign minister putin',
            'foreign minister russia',
            'received iran message', 'message from mojtaba',
            'message from khamenei', 'received a message',
            # ── v2.1 — UN / DIPLOMATIC COVER ──
            'russia veto', 'russia vetoes', 'russia vetoed',
            'hormuz resolution', 'hormuz veto',
            'vetoing a resolution', 'diplomatic cover for iran',
            'russia un cover', 'russia security council iran',
            # ── v2.1 — URANIUM / NUCLEAR HANDOVER ──
            'take iranian uranium', 'take that uranium',
            'iranian uranium', 'uranium russia',
            'kremlin uranium', 'iranian stockpile',
            'enriched uranium russia', 'readiness to take',
            # ── v2.1 — CASPIAN TRADE WORKAROUND ──
            'caspian sea', 'caspian trade', 'caspian shipping',
            'caspian transit', 'via the caspian',
            # ── v2.1 — MEDIATION SUBSTITUTION ──
            'moscow mediation', 'putin mediates',
            'russia mediation', 'russia broker',
            'phased approach hormuz', 'reopening the strait of hormuz',
            'phased hormuz', 'mediation channel',
            'witkoff', 'kushner pakistan',
            'called off the trip', 'cancelled the trip',
            'trump abruptly called', 'trump cancels iran',
            'pakistan and oman', 'pakistan talks',
            # ── v2.1 — INTELLIGENCE / WEAPONS SUPPLY (specific) ──
            'satellite imagery showing', 'warships and military',
            'advanced drones to iran', 'deliver advanced drones',
            'shahed flow', 'uranium and shahed',
            # Cross-language
            'روسيا تدعم إيران', 'روسیه ایران حمایت',
            'پرتاب ماهواره ایرانی روسیه',
            'عراقچی', 'مجتبی خامنه‌ای',
            'وتو روسيا',
        ],
        'baseline_statements_per_week': 3,
        'tripwires': [
            'russia launches iranian spy satellite',
            'russia provides targeting data iran strike',
            'russia delivers s-400 iran',
            'russia iran defense pact signed',
            # v2.1 — diplomatic / nuclear tripwires
            'putin araghchi summit',
            'mojtaba khamenei direct message putin',
            'russia veto un hormuz resolution',
            'russia accepts iranian uranium handover',
            'russia signs iran drone supply',
        ],
    },
}


# ============================================
# VECTOR TRIGGER LADDERS
# ============================================

# ── Vector 1: Nuclear Rhetoric ────────────────────────────────
NUCLEAR_TRIGGERS = {
    5: [
        'russia uses nuclear weapon', 'nuclear detonation russia',
        'tactical nuclear strike', 'russia nuclear attack',
        'nuclear weapon used ukraine', 'dirty bomb russia confirmed',
        'russia launches nuclear', 'nuclear explosion russia',
    ],
    4: [
        'russia raises nuclear alert', 'nuclear forces combat readiness',
        'russia deploys nuclear weapons', 'tactical nuclear deployment',
        'russia moves nuclear warheads', 'nuclear submarine surge',
        'dead hand system activated', 'perimeter system russia',
        'russia places nuclear on alert', 'strategic forces alert',
        'nuclear weapons belarus deployed', 'sarmat test launch',
        'poseidon torpedo deployment', 'russia nuclear doctrine change',
    ],
    3: [
        'medvedev nuclear warning', 'russia nuclear threat nato',
        'russia considers nuclear', 'nuclear option russia',
        'russia nuclear if nato intervenes', 'nuclear weapons as option',
        'russia escalate to nuclear', 'nuclear blackmail russia',
        'kinzhal nuclear capable', 'iskander nuclear russia',
        'russia nuclear exercise', 'strategic missile forces exercise',
        'russia warns nuclear response', 'nuclear deterrence russia',
        'russia hypersonic nuclear', 'russia nuclear rhetoric',
        'ядерное оружие НАТО', 'ядерный удар',
    ],
    2: [
        'russia nuclear', 'nuclear warning russia',
        'russia nuclear deterrent', 'nuclear capability russia',
        'russia strategic weapons', 'medvedev nuclear',
        'russia warns nuclear', 'nuclear signaling russia',
        'ядерное оружие', 'ядерное сдерживание',
    ],
    1: [
        'nuclear russia', 'russia deterrent',
        'strategic weapons', 'ядерный',
    ],
}

# ── Vector 2: Ground Operations (Ukraine front) ───────────────
GROUND_OPS_TRIGGERS = {
    5: [
        'russia captures kyiv', 'russian forces kyiv',
        'russia overruns ukraine', 'ukrainian collapse',
        'russia takes zaporizhzhia city', 'russia captures kharkiv',
        'ukraine surrenders', 'ukraine government flees',
        'russia occupies ukraine capital',
    ],
    4: [
        'russia major offensive', 'russian breakthrough ukraine',
        'russia advances rapidly', 'ukraine lines collapse',
        'russia takes strategic city', 'russian forces encircle',
        'ukraine loses major city', 'russia captures key town',
        'russian surge ukraine', 'russia mass attack ukraine',
        'russia crosses dnieper', 'russia odesa landing',
    ],
    3: [
        'russian advance ukraine', 'russia gains ground ukraine',
        'russian forces push', 'ukraine retreats',
        'ukraine loses territory', 'russia offensive ukraine',
        'russian attack succeeds', 'russia captures village',
        'kursk incursion russia', 'russia counterattack ukraine',
        'ukraine front pressure', 'russian artillery advance',
    ],
   2: [
        'russia ukraine front', 'ukraine fighting',
        'ukraine battle', 'russia ukraine war',
        'russia strikes ukraine', 'russian missile ukraine',
        'russian drone ukraine', 'shahed ukraine',
        'fpv drone ukraine', 'fpv attack ukraine',
        'nikopol', 'kherson shelling', 'mykolaiv attack',
        'russian drone kills', 'russian attack kills',
        'russia bombs ukraine', 'russia hits civilian',
    ], 2: [
        'russia ukraine front', 'ukraine fighting',
        'ukraine battle', 'russia ukraine war',
        'russia strikes ukraine', 'russian missile ukraine',
        'russian drone ukraine', 'shahed ukraine',
    ],
    1: [
        'ukraine war', 'russia ukraine', 'ukraine conflict',
        'ukraine russia fighting', 'donbas',
    ],
}

# ── Vector 3: NATO Flank Pressure ────────────────────────────
NATO_FLANK_TRIGGERS = {
    5: [
        'russia attacks nato country', 'russia fires at nato',
        'russian forces cross nato border', 'article 5 invoked',
        'nato at war russia', 'russia invades nato territory',
        'russia hits poland', 'russia attacks estonia',
    ],
    4: [
        'russia threatens nato attack', 'russia ultimatum nato',
        'russia deploy troops nato border', 'kaliningrad escalation',
        'suwalki gap closure', 'russia encircles baltic',
        'russia cuts baltic', 'iskander aimed nato',
        'russia threatens poland', 'russia threatens baltics',
        'russia military border poland', 'russia troops finland',
        'nuclear weapons kaliningrad', 'russia deploys kaliningrad',
    ],
    3: [
        'russia nato confrontation', 'russian aircraft nato',
        'russian jet scramble nato', 'russia drills nato border',
        'kaliningrad military buildup', 'russia exercises nato flank',
        'russia patrols nato border', 'russian ships nato',
        'russia hybrid nato', 'russian cyber nato',
        'russia sabotage europe', 'undersea cable russia',
        'russian spy nato', 'russia infiltrates nato',
        'russia threatens finland', 'russia threatens sweden',
    ],
    2: [
        'russia nato tension', 'nato russia confrontation',
        'russia baltic', 'russia poland tension',
        'russia finland', 'russia sweden',
        'russian aircraft nato airspace', 'nato intercept russia',
    ],
    1: [
        'russia nato', 'nato russia', 'eastern flank',
        'nato eastern europe', 'russia europe threat',
        'nato summit', 'nato defense', 'nato secretary',
        'rutte nato', 'nato meeting', 'nato response',
        'nato ukraine support', 'nato weapons ukraine',
    ],
}

# ── Vector 4: Arctic Signals ──────────────────────────────────
ARCTIC_TRIGGERS = {
    5: [
        'russia seizes arctic territory', 'russia svalbard invasion',
        'russia closes arctic to nato', 'arctic war russia',
        'russia sinks nato vessel arctic', 'russia attacks arctic',
    ],
    4: [
        'northern fleet full deployment', 'ssbn surge russia',
        'russia arctic military buildup', 'russia closes arctic airspace',
        'russia svalbard military action', 'giuk gap blocked russia',
        'russia arctic territorial claim force',
        'russia arctic exercise full scale',
    ],
    3: [
        'northern fleet exercise', 'russian ssbn deployment',
        'russia arctic exercise', 'russia svalbard tensions',
        'giuk gap russian submarine', 'russia arctic patrol',
        'russian submarine north atlantic surge',
        'arctic infrastructure russia military',
        'russia greenland military signal',
        'norway russia arctic incident',
    ],
    2: [
        'northern fleet', 'russian arctic', 'russia submarine patrol',
        'russia svalbard', 'giuk gap russia',
        'arctic russia exercise', 'russian submarine atlantic',
    ],
    1: [
        'russia arctic', 'northern fleet', 'ssbn russia',
        'arctic military', 'giuk',
    ],
}

# ── Vector 5: Hybrid / Cross-Theater ─────────────────────────
HYBRID_TRIGGERS = {
    5: [
        'russia cyberattack nato infrastructure',
        'russia disables power grid nato',
        'russia cuts undersea internet cables',
        'russia election interference confirmed nato',
        'wagner nato country', 'russia proxy nato attack',
    ],
    4: [
        'russia cyber attack europe', 'russia attacks energy europe',
        'russia cuts gas europe', 'russia energy weapon',
        'russia pipeline sabotage', 'undersea cable russia severed',
        'russian sabotage confirmed europe', 'russia disinformation campaign',
        'dprk troops russia ukraine', 'north korea ammunition russia',
        'iran weapons russia ukraine', 'russia iran military',
        'cuba russia military base', 'russia cuba espionage',
        'wagner africa expand', 'russia africa coup',
    ],
    3: [
        'russia hybrid warfare', 'russia cyber europe',
        'russia disinformation', 'russian propaganda europe',
        'russia energy pressure europe', 'russia lng europe',
        'russia gas europe', 'russia sanctions evade',
        'iran supplies russia', 'dprk supplies russia',
        'north korea russia weapons', 'russia dprk ammunition',
        'cuba russia signals intelligence', 'russia venezuela',
        'russia nicaragua', 'russia latin america',
        'wagner russia', 'africa coup russia',
    ],
    2: [
        'russia hybrid', 'russia cyber', 'russia energy europe',
        'russia dprk', 'russia iran', 'russia cuba',
        'russian sabotage', 'russia disinformation',
        'north korea russia', 'iran russia weapons',
        'russia africa', 'wagner africa',
        'russia venezuela', 'russia nicaragua',
        'russian spy', 'russian intelligence europe',
        'russia shadow fleet', 'russia sanctions evade',
    ],
    1: [
        'russia hybrid', 'wagner', 'russia proxy',
        'russia iran', 'russia dprk',
    ],
}


# ============================================
# RSS SOURCES
# ============================================
RSS_SOURCES = {
    # ── Ukrainian / pro-Ukraine sources ──
    'kyiv_independent': {
        'url': 'https://kyivindependent.com/feed/',
        'name': 'Kyiv Independent',
        'weight': 1.0,
        'note': 'Primary English Ukraine war reporting -- ground truth for front signals',
    },
    'uawire': {
        'url': 'https://uawire.org/feed',
        'name': 'UAWire',
        'weight': 0.95,
        'note': 'Ukraine/Russia focused news wire',
    },
    'ukraine_pravda_en': {
        'url': 'https://www.pravda.com.ua/eng/rss/',
        'name': 'Ukrainska Pravda (EN)',
        'weight': 0.95,
    },
    # ── v2.0 — Ukrainian-language native sources (May 6, 2026) ──
    # Ukraine is the primary battlefield; native-language coverage is denser.
    'ukraine_pravda_ua': {
        'url': 'https://www.pravda.com.ua/rss/',
        'name': 'Ukrainska Pravda (UA)',
        'weight': 0.95,
        'note': 'Ukraine\'s leading independent newspaper — native Ukrainian-language coverage',
    },
    'liga_ua': {
        'url': 'https://news.liga.net/all/rss.xml',
        'name': 'Liga.net (UA)',
        'weight': 0.85,
        'note': 'Ukrainian business + politics — front signals + domestic stability',
    },
    'nv_ua': {
        'url': 'https://nv.ua/rss/all.xml',
        'name': 'NV.ua (UA)',
        'weight': 0.85,
        'note': 'Ukrainian news outlet — native-language ground truth',
    },
    'ukrinform_en': {
        'url': 'https://www.ukrinform.net/rss/block-lastnews',
        'name': 'Ukrinform (EN)',
        'weight': 0.85,
        'note': 'Ukrainian state news agency — Kyiv official line',
    },
    'the_insider': {
        'url': 'https://theins.ru/feed',
        'name': 'The Insider (Russia investigative)',
        'weight': 0.9,
        'note': 'Russian investigative journalism -- Kremlin internal signals',
    },
    'meduza_en': {
        'url': 'https://meduza.io/rss/en/all',
        'name': 'Meduza (EN)',
        'weight': 0.9,
        'note': 'Independent Russian journalism -- Kremlin/domestic signals',
    },
    # ── v2.0 — Russian-language native sources (May 6, 2026) ──
    # Catches Kremlin/domestic signals invisible to English coverage.
    # State media included as official-line baseline (TASS/RIA reflect Kremlin policy).
    'meduza_ru': {
        'url': 'https://meduza.io/rss/all',
        'name': 'Meduza (RU)',
        'weight': 0.9,
        'note': 'Independent Russian journalism — original Russian-language signals',
    },
    'novaya_gazeta_europe_ru': {
        'url': 'https://novayagazeta.eu/feed',
        'name': 'Novaya Gazeta Europe (RU)',
        'weight': 0.9,
        'note': 'Russian opposition journalism in exile — domestic dissent signals',
    },
    'tass_en': {
        'url': 'https://tass.com/rss/v2.xml',
        'name': 'TASS (EN)',
        'weight': 0.7,
        'note': 'Russian state news agency — official Kremlin-line baseline (READ AS PROPAGANDA)',
    },
    'ria_novosti_ru': {
        'url': 'https://ria.ru/export/rss2/archive/index.xml',
        'name': 'RIA Novosti (RU)',
        'weight': 0.7,
        'note': 'Russian state media — official Kremlin baseline (READ AS PROPAGANDA)',
    },
    'rt_en': {
        'url': 'https://www.rt.com/rss/',
        'name': 'RT (EN)',
        'weight': 0.6,
        'note': 'Russian state-funded English — propaganda baseline (handle accordingly)',
    },
    # ── Western defense / OSINT ──
    'isw': {
        'url': 'https://www.understandingwar.org/rss.xml',
        'name': 'Institute for the Study of War',
        'weight': 1.0,
        'note': 'Daily Ukraine war assessment -- essential for front signals',
    },
    'bellingcat': {
        'url': 'https://www.bellingcat.com/feed/',
        'name': 'Bellingcat',
        'weight': 0.95,
        'note': 'OSINT -- Russian military equipment, locations, disinformation',
    },
    'usni_news': {
        'url': 'https://news.usni.org/feed',
        'name': 'USNI News',
        'weight': 1.0,
        'note': 'Northern Fleet, SSBN, Arctic naval signals',
    },
    'war_on_rocks': {
        'url': 'https://warontherocks.com/feed/',
        'name': 'War on the Rocks',
        'weight': 0.95,
    },
    'the_diplomat': {
        'url': 'https://thediplomat.com/feed/',
        'name': 'The Diplomat',
        'weight': 0.85,
    },
    'rferl': {
        'url': 'https://www.rferl.org/api/z-mq-eqvou',
        'name': 'Radio Free Europe / Radio Liberty',
        'weight': 0.9,
        'note': 'Key for Russian domestic signals, Kremlin internal',
    },
    # ── Baltic / Eastern Europe ──
    'lsm_en': {
        'url': 'https://eng.lsm.lv/rss/',
        'name': 'LSM Latvia (EN)',
        'weight': 0.85,
        'note': 'Latvian state broadcaster -- Baltic threat reception',
    },
    'err_en': {
        'url': 'https://news.err.ee/rss',
        'name': 'ERR Estonia (EN)',
        'weight': 0.85,
        'note': 'Estonian state broadcaster -- Baltic threat reception',
    },
    'lrt_en': {
        'url': 'https://www.lrt.lt/en/rss',
        'name': 'LRT Lithuania (EN)',
        'weight': 0.85,
    },
    'yle_en': {
        'url': 'https://feeds.yle.fi/uutiset/v1/majorHeadlines/YLE_UUTISET.rss',
        'name': 'YLE Finland (EN)',
        'weight': 0.85,
        'note': 'Finnish state broadcaster -- Finland/Russia border signals',
    },
    # ── v2.0 — Belarus opposition/exile coverage (May 6, 2026) ──
    # Belarus is in actor list; deserves dedicated coverage from independent sources.
    'belsat_en': {
        'url': 'https://belsat.eu/en/feed/',
        'name': 'Belsat (EN)',
        'weight': 0.85,
        'note': 'Polish-funded Belarusian-language outlet — Belarus opposition + Lukashenko signals',
    },
    'reform_by': {
        'url': 'https://reform.by/feed',
        'name': 'Reform.by',
        'weight': 0.8,
        'note': 'Belarusian independent news in exile — domestic Belarus signals',
    },
    # ── Nordic / Arctic ──
    'high_north_news': {
        'url': 'https://www.highnorthnews.com/en/rss.xml',
        'name': 'High North News',
        'weight': 0.9,
        'note': 'Arctic-focused -- Svalbard, Northern Fleet, GIUK',
    },
    'barents_observer': {
        'url': 'https://thebarentsobserver.com/en/rss.xml',
        'name': 'Barents Observer',
        'weight': 0.9,
        'note': 'Norwegian Arctic reporting -- Svalbard, Russia Arctic military',
    },
    # ── Broader European / NATO ──
    'politico_eu': {
        'url': 'https://www.politico.eu/feed/',
        'name': 'Politico EU',
        'weight': 0.85,
    },
    'euractiv': {
        'url': 'https://www.euractiv.com/feed/',
        'name': 'Euractiv',
        'weight': 0.8,
    },
    # ── v2.1 — Targeted Iran-Russia diplomatic coordination ──
    # Catches NYT/Reuters analytical framing on top-level meetings,
    # mediation substitution, UN cover, uranium handover.
    'gnews_russia_iran_diplomatic': {
        'url': 'https://news.google.com/rss/search?q=Putin+Araghchi+OR+%22Russia+Iran%22+mediation+OR+%22Iran+foreign+minister%22+Moscow+2026&hl=en&gl=US&ceid=US:en',
        'name': 'Google News — Russia-Iran diplomatic',
        'weight': 1.0,
        'note': 'Top-level coordination, UN vetoes, mediation channel substitution',
    },
    'gnews_russia_iran_uranium': {
        'url': 'https://news.google.com/rss/search?q=Russia+uranium+Iran+OR+%22Hormuz+veto%22+OR+%22Caspian%22+Iran+2026&hl=en&gl=US&ceid=US:en',
        'name': 'Google News — Russia-Iran uranium/Hormuz',
        'weight': 0.95,
        'note': 'Material support and diplomatic cover signals',
    },
}


# ============================================
# GDELT QUERIES
# ============================================
GDELT_QUERIES = {
    'eng': [
        # Core Russia-NATO/Ukraine
        'Russia Ukraine war military attack strike',
        'Russia NATO threat military exercise warning',
        'Putin Kremlin Ukraine statement threat',
        'Russia nuclear threat warning NATO Ukraine',
        # Baltic / Eastern Flank
        'Russia Baltic Estonia Latvia Lithuania threat military',
        'Kaliningrad Iskander Russia military NATO',
        'Suwalki gap Russia military Belarus',
        'Russia Finland border military threat',
        # Arctic
        'Russia Arctic Northern Fleet SSBN submarine NATO',
        'Russia Svalbard Arctic military claim',
        'GIUK gap Russia submarine NATO patrol',
        # Hybrid / cross-theater
        'Russia cyber attack Europe NATO infrastructure',
        'Russia energy weapon Europe gas pipeline',
        'North Korea DPRK ammunition Russia Ukraine',
        'Iran weapons supply Russia Ukraine war',
        'Russia Cuba military espionage',
        # Diplomatic / Ukraine peace
        'Trump Putin Ukraine peace talks ceasefire',
        'Ukraine ceasefire negotiations Russia terms',
        'Russia Ukraine minerals deal peace',
        # Domestic Russia signals
        'Russia military morale desertion soldiers',
        'Russia Wagner mercenary Africa',
        'Russia internal dissent military opposition',
        # ── v2.0 (May 6, 2026) — additional Ukraine front battlespaces ──
        'Sumy front Russia attack',
        'Pokrovsk front Russia advance',
        'Toretsk Russia capture Ukraine',
        'Vovchansk Kharkiv front Russia',
        'Robotyne Zaporizhzhia front',
        'Kupyansk Russia Ukraine',
        # ── v2.0 — Russia-China convergence (English-language) ──
        'Russia China military cooperation Putin Xi',
        'Russia China dual-use components Ukraine weapons',
        'Power of Siberia gas China Russia',
        'Russia China Northern Sea Route Arctic',
        'Russia China BRICS sanctions evasion',
    ],
    # ── v2.0 — Mandarin (zho) Russia-China convergence (May 6, 2026) ──
    # Captures Chinese-language framing of Russia-China relations,
    # Power of Siberia coverage, and Putin-Xi diplomatic signals
    # invisible to English-language sources.
    'zho': [
        '俄罗斯 中国 军事合作',          # Russia China military cooperation
        '普京 习近平 会晤',              # Putin Xi meeting
        '俄乌战争 中国立场',             # Russia-Ukraine war China position
        '西伯利亚力量 天然气',           # Power of Siberia gas
        '俄罗斯 北方航道 中国',          # Russia Northern Sea Route China
        '金砖国家 俄罗斯 制裁',          # BRICS Russia sanctions
        '俄罗斯 伊朗 中国',              # Russia Iran China
        '俄朝合作 弹药',                 # Russia DPRK ammunition cooperation
    ],
    'rus': [
        # Russian-language MoD / Kremlin
        'Россия НАТО военные учения угроза',
        'Путин Украина специальная военная операция',
        'ядерное оружие Россия НАТО предупреждение',
        'Северный флот учения Арктика',
        'Россия Калининград военные',
        # Russian domestic signals
        'мобилизация Россия армия',
        'потери России Украина фронт',
        'Вагнер Россия военные',
        'дезертирство наказание солдаты Россия',
        # Diplomatic
        'переговоры Россия Украина мир',
        'Путин Трамп переговоры',
        # ── v2.0 (May 6, 2026) — Russia-China convergence (Russian-language) ──
        'Россия Китай военное сотрудничество',
        'Путин Си Цзиньпин встреча',
        'Сила Сибири газ Китай',
        'БРИКС Россия санкции',
        # ── v2.0 — Russia-Iran axis (Russian-language) ──
        'Россия Иран военные поставки',
        'Путин Пезешкиан соглашение',
        'российские ракеты Иран',
        # ── v2.0 — Russia-DPRK axis (Russian-language) ──
        'Россия КНДР боеприпасы',
        'российско-северокорейское сотрудничество',
    ],
    # ── v2.0 — Farsi (fas) Russia-Iran axis (May 6, 2026) ──
    # Captures Iranian-language framing of Russia-Iran weapons transfers,
    # satellite cooperation, and diplomatic coordination invisible to
    # English/Russian sources.
    'fas': [
        'روسیه ایران همکاری نظامی',          # Russia Iran military cooperation
        'پوتین پزشکیان توافق',                # Putin Pezeshkian agreement
        'پرتاب ماهواره ایرانی روسیه',         # Russia launches Iranian satellite
        'روسیه شاهد پهپاد',                  # Russia Shahed drone
        'عراقچی مسکو',                       # Araghchi Moscow
        'مجتبی خامنه‌ای',                    # Mojtaba Khamenei (succession signal)
        'دریای خزر تجارت',                   # Caspian Sea trade
        'وتو روسیه شورای امنیت',             # Russia veto UN Security Council
    ],
    # ── v2.0 — Arabic (ara) MENA spillover + Africa (May 6, 2026) ──
    # Lighter-touch — Russia diplomatic mediation in MENA, Wagner/Africa Corps,
    # arms deals to Gulf, Russia-Syria continuity signals.
    'ara': [
        'روسيا إيران تعاون عسكري',            # Russia Iran military cooperation
        'بوتين الشرق الأوسط وساطة',           # Putin Middle East mediation
        'فاغنر أفريقيا',                      # Wagner Africa
        'الفيلق الأفريقي روسيا',              # Africa Corps Russia
        'روسيا سوريا قاعدة',                 # Russia Syria base
        'روسيا الخليج أسلحة',                # Russia Gulf weapons
    ],
    # ── v2.0 — Belarusian (bel) — Lukashenko/border signals (May 6, 2026) ──
    'bel': [
        'Беларусь Расея вайскова',           # Belarus Russia military
        'Лукашэнка Пуцін',                    # Lukashenko Putin
        'ядзерная зброя Беларусь',            # nuclear weapons Belarus
    ],
    'ukr': [
        # Ukrainian-language signals
        'Росія НАТО загроза',
        'Зеленський Україна оборона',
        'фронт Україна наступ Росія',
        'Росія ракетний удар Україна',
        'переговори мир Україна',
        # ── v2.0 (May 6, 2026) — Ukrainian-language battlefield + diplomatic depth ──
        'Покровськ фронт російський наступ',          # Pokrovsk front Russian offensive
        'Курська область українські сили',            # Kursk region Ukrainian forces
        'Сумська область обстріл',                    # Sumy region shelling
        'українські дрони далекобійні Росія',         # Ukrainian long-range drones Russia
        'Зеленський Трамп переговори',                # Zelenskyy Trump negotiations
        'мобілізація Україна',                        # mobilization Ukraine
        'українські БпЛА Москва',                     # Ukrainian drones Moscow
        'Шахед атака Україна',                        # Shahed attack Ukraine
    ],
}


# ============================================
# NITTER ACCOUNTS
# ============================================
NITTER_ACCOUNTS_RUSSIA = [
    # ── ISW / Analysis ──────────────────────────────────────────
    ('TheStudyofWar',       1.2, 'ISW -- daily Ukraine war assessment'),
    ('RALee85',             1.1, 'ISW analyst Ryan Lee -- front signal analysis'),
    # ── Ukrainian official ───────────────────────────────────────
    ('DefenceU',            1.2, 'Ukrainian MoD EN -- official ops announcements'),
    ('ZelenskyyUa',         1.1, 'Zelenskyy -- diplomatic + military posture'),
    ('GeneralStaffUA',      1.1, 'Ukrainian General Staff -- front signals'),
    # ── NATO / Western official ──────────────────────────────────
    ('NATO',                1.0, 'NATO official -- alliance response signals'),
    ('SecDef',              1.0, 'US SecDef -- aid, posture, Russia warnings'),
    ('StateDept',           1.0, 'US State Dept -- diplomacy, sanctions'),
    ('CENTCOM',             0.9, 'CENTCOM -- broader ME/Russia cross-theater'),
    # ── OSINT / Monitoring ───────────────────────────────────────
    ('OSINTdefender',       1.1, 'OSINT Defender -- Russian military open source'),
    ('GirkinGirkin',        0.9, 'Strelkov/Girkin -- Russian nationalist signals'),
    ('ChristopherJM',       1.0, 'Chris Miller -- Russia analyst'),
    # ── Baltic / Arctic ─────────────────────────────────────────
    ('IlvesToomas',         0.9, 'Toomas Ilves former Estonia President -- Baltic signals'),
    ('HighNorthNews',       0.9, 'High North News -- Arctic signals'),
]


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
        print(f"[Russia Rhetoric] Redis GET error: {str(e)[:80]}")
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
        print(f"[Russia Rhetoric] Redis SET error: {str(e)[:80]}")
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
        print(f"[Russia Rhetoric] Redis LPUSH error: {str(e)[:80]}")


# ============================================
# ARTICLE FETCHING
# ============================================

def _parse_pub_date(pub_str):
    if not pub_str:
        return None
    try:
        return datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
    except Exception:
        pass
    try:
        return parsedate_to_datetime(pub_str).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        clean = pub_str.replace('T','').replace('Z','').replace('-','').replace(':','').replace(' ','')
        if len(clean) >= 14:
            return datetime.strptime(clean[:14], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
        elif len(clean) == 8:
            return datetime.strptime(clean[:8], '%Y%m%d').replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def _fetch_rss(url, source_name, weight=0.85, max_items=20):
    articles = []
    try:
        resp = requests.get(url, timeout=(5, 12),
                            headers={'User-Agent': 'Mozilla/5.0 AsifahAnalytics/1.0'})
        if resp.status_code != 200:
            print(f"[Russia RSS] {source_name}: HTTP {resp.status_code}")
            return []
        root = ET.fromstring(resp.content)
        for item in root.findall('.//item')[:max_items]:
            title_el = item.find('title')
            link_el  = item.find('link')
            pub_el   = item.find('pubDate')
            desc_el  = item.find('description')
            if title_el is None or not title_el.text:
                continue
            articles.append({
                'title':       title_el.text.strip(),
                'description': (desc_el.text or title_el.text or '')[:500] if desc_el is not None else '',
                'url':         link_el.text.strip() if link_el is not None and link_el.text else '',
                'publishedAt': pub_el.text if pub_el is not None else '',
                'source':      {'name': source_name},
                'content':     title_el.text.strip(),
                'source_weight_override': weight,
            })
        print(f"[Russia RSS] {source_name}: {len(articles)} articles")
    except ET.ParseError as e:
        print(f"[Russia RSS] {source_name}: XML parse error: {str(e)[:80]}")
    except Exception as e:
        print(f"[Russia RSS] {source_name}: {str(e)[:80]}")
    return articles


def _fetch_gdelt(query, language='eng', days=3, max_records=25):
    articles = []
    try:
        params = {
            'query':      query,
            'mode':       'artlist',
            'maxrecords': max_records,
            'timespan':   f'{days}d',
            'format':     'json',
            'sourcelang': language,
        }
        resp = requests.get(GDELT_BASE_URL, params=params, timeout=(5, 15))
        if resp.status_code == 429:
            print(f"[Russia GDELT] 429 rate limit -- skipping: {query[:40]}")
            return []
        if resp.status_code == 200:
            lang_map = {'eng': 'en', 'rus': 'ru', 'ukr': 'uk'}
            for art in resp.json().get('articles', []):
                articles.append({
                    'title':       art.get('title', ''),
                    'description': art.get('title', ''),
                    'url':         art.get('url', ''),
                    'publishedAt': art.get('seendate', ''),
                    'source':      {'name': f"GDELT ({language})"},
                    'content':     art.get('title', ''),
                    'language':    lang_map.get(language, language),
                })
        else:
            print(f"[Russia GDELT] {language}: HTTP {resp.status_code}")
        time.sleep(0.5)
    except Exception as e:
        print(f"[Russia GDELT] {language} error: {str(e)[:80]}")
    return articles


def _fetch_all_articles():
    """Fetch from all RSS sources, Telegram, and GDELT."""
    articles = []

    # Telegram signals (168h window for Russia -- catches slow-moving strategic signals)
    if TELEGRAM_AVAILABLE:
        try:
            tg_messages = fetch_russia_telegram_signals(hours_back=168)
            for msg in tg_messages:
                articles.append({
                    'title':       msg.get('title', ''),
                    'description': msg.get('title', ''),
                    'url':         msg.get('url', ''),
                    'publishedAt': msg.get('published', ''),
                    'source':      {'name': msg.get('source', 'Telegram')},
                    'content':     msg.get('title', ''),
                })
            print(f"[Russia Rhetoric] Telegram: {len(tg_messages)} messages ingested")
        except Exception as e:
            print(f"[Russia Rhetoric] Telegram error: {str(e)[:80]}")

    # RSS feeds
    for key, src in RSS_SOURCES.items():
        try:
            fetched = _fetch_rss(src['url'], src['name'], src.get('weight', 0.85))
            articles.extend(fetched)
        except Exception as e:
            print(f"[Russia RSS] {key} error: {str(e)[:80]}")

    # GDELT -- all language queues
    gdelt_count = 0
    for language, queries in GDELT_QUERIES.items():
        for query in queries:
            try:
                fetched = _fetch_gdelt(query, language=language)
                articles.extend(fetched)
                gdelt_count += len(fetched)
            except Exception as e:
                print(f"[Russia GDELT] {language} error: {str(e)[:80]}")

    print(f"[Russia Rhetoric] Total articles fetched: {len(articles)} ({gdelt_count} from GDELT)")

    # Deduplicate by URL
    seen = set()
    unique = []
    for art in articles:
        url = art.get('url', '')
        title = art.get('title', '')
        key = url or title
        if key and key not in seen:
            seen.add(key)
            unique.append(art)

    print(f"[Russia Rhetoric] After dedup: {len(unique)} articles")
    return unique


# ============================================
# ARTICLE CLASSIFICATION
# ============================================

def _score_article_for_actor(article, actor_key, actor_def):
    """Score an article for a specific actor. Returns (level, trigger_phrase)."""
    title = (article.get('title') or '').lower()
    desc  = (article.get('description') or '').lower()
    text  = f"{title} {desc}"

    for kw in actor_def.get('keywords', []):
        if kw.lower() in text:
            # Check tripwires first
            for tw in actor_def.get('tripwires', []):
                if tw.lower() in text:
                    return 4, tw
            return 1, kw
    return 0, None


def _score_vector(articles, trigger_dict):
    """Score all articles against a vector trigger ladder. Returns (max_level, trigger_phrase)."""
    max_level = 0
    trigger   = None
    for art in articles:
        title = (art.get('title') or '').lower()
        desc  = (art.get('description') or '').lower()
        text  = f"{title} {desc}"
        for level in sorted(trigger_dict.keys(), reverse=True):
            for phrase in trigger_dict[level]:
                if phrase.lower() in text:
                    if level > max_level:
                        max_level = level
                        trigger   = phrase
                    break
    return max_level, trigger


def _classify_articles(articles):
    """
    Classify all articles against actors and vectors.
    Returns actor_results dict and vector scores dict.
    """
    actor_results = {}
    for actor_key, actor_def in ACTORS.items():
        matched = []
        max_level = 0
        max_trigger = None

        for art in articles:
            level, trigger = _score_article_for_actor(art, actor_key, actor_def)
            if level > 0:
                art_copy = dict(art)
                art_copy['escalation_level'] = level
                art_copy['trigger_phrase']   = trigger
                matched.append(art_copy)
                if level > max_level:
                    max_level   = level
                    max_trigger = trigger

        matched.sort(key=lambda x: (
            -x.get('escalation_level', 0),
            x.get('publishedAt', '') or ''
        ), reverse=False)
        matched.sort(key=lambda x: -x.get('escalation_level', 0))

        actor_results[actor_key] = {
            'name':              actor_def['name'],
            'flag':              actor_def.get('flag', ''),
            'icon':              actor_def.get('icon', ''),
            'color':             actor_def.get('color', '#6b7280'),
            'role':              actor_def.get('role', ''),
            'escalation_level':  max_level,
            'escalation_label':  ESCALATION_LEVELS.get(max_level, {}).get('label', 'Monitoring'),
            'escalation_color':  ESCALATION_LEVELS.get(max_level, {}).get('color', '#6b7280'),
            'escalation_phrase': max_trigger,
            'statement_count':   len(matched),
            'top_articles':      matched[:5],
            'silence_alert':     actor_def.get('silence_alert', True) and len(matched) == 0,
        }

    # Vector scoring
    vectors = {
        'nuclear':    _score_vector(articles, NUCLEAR_TRIGGERS),
        'ground_ops': _score_vector(articles, GROUND_OPS_TRIGGERS),
        'nato_flank': _score_vector(articles, NATO_FLANK_TRIGGERS),
        'arctic':     _score_vector(articles, ARCTIC_TRIGGERS),
        'hybrid':     _score_vector(articles, HYBRID_TRIGGERS),
    }

    return actor_results, vectors


# ============================================
# THEATRE SCORE
# ============================================

def _compute_theatre_score(actor_results, vectors):
    """
    Compute the Russia theatre score 0-100.

    Weights:
      Russia Military:       3.0
      Russia Government:     2.5
      Nuclear vector:        4.0  (highest weight -- unique to Russia)
      Ground ops (Ukraine):  2.5
      NATO Flank vector:     2.5
      Arctic vector:         1.5
      Hybrid vector:         1.0
      Belarus:               1.0
      Convergence bonus:     +10 if 3+ vectors simultaneously at L3+
      Arctic convergence:    +5 if arctic L3+ AND Greenland signal
    """
    score = 0.0

    # Actor contributions
    mil_level  = actor_results.get('russia_military',  {}).get('escalation_level', 0)
    gov_level  = actor_results.get('russia_government',{}).get('escalation_level', 0)
    bel_level  = actor_results.get('belarus',          {}).get('escalation_level', 0)

    score += mil_level  * 3.0 * (100/5)
    score += gov_level  * 2.5 * (100/5)
    score += bel_level  * 1.0 * (100/5)

    # Vector contributions
    nuc_level, _  = vectors.get('nuclear',    (0, None))
    gnd_level, _  = vectors.get('ground_ops', (0, None))
    nat_level, _  = vectors.get('nato_flank', (0, None))
    arc_level, _  = vectors.get('arctic',     (0, None))
    hyb_level, _  = vectors.get('hybrid',     (0, None))

    score += nuc_level * 4.0 * (100/5)
    score += gnd_level * 2.5 * (100/5)
    score += nat_level * 2.5 * (100/5)
    score += arc_level * 1.5 * (100/5)
    score += hyb_level * 1.0 * (100/5)

    # Normalize by total weight (3.0+2.5+1.0+4.0+2.5+2.5+1.5+1.0 = 18.0)
    score = (score / (18.0 * (100/5))) * 100

    # Convergence bonus: 3+ vectors at L3+
    high_vectors = sum(1 for lvl in [nuc_level, gnd_level, nat_level, arc_level, hyb_level]
                       if lvl >= 3)
    if high_vectors >= 3:
        score += 10

    # Arctic convergence bonus (when Arctic signals rise with Greenland)
    if arc_level >= 3:
        score += 5

    score = max(0, min(100, round(score)))
    return score


# ============================================
# CONDITIONAL THREAT DETECTION
# ============================================

CONDITIONAL_THREAT_PHRASES = [
    'if nato intervenes', 'if nato escalates', 'if us deploys',
    'if ukraine attacks russia', 'if we are attacked',
    'in response to', 'unless nato withdraws', 'unless ukraine',
    'if provoked', 'defensive response', 'forced to respond',
    'will respond to', 'consequences will follow',
    'если НАТО', 'в ответ на', 'если нападут',
]


def _detect_conditional_threats(articles):
    threats = []
    for art in articles:
        title = (art.get('title') or '').lower()
        for phrase in CONDITIONAL_THREAT_PHRASES:
            if phrase.lower() in title:
                threats.append({
                    'article':   art.get('title', '')[:80],
                    'phrase':    phrase,
                    'published': art.get('publishedAt', ''),
                    'source':    art.get('source', {}).get('name', ''),
                    'url':       art.get('url', ''),
                })
                break
    return threats[:8]


# ============================================
# CROSS-THEATER FINGERPRINT
# ============================================

def _write_crosstheater_fingerprint(actor_results, vectors):
    """
    Write Russia signals to shared Redis cross-theater fingerprint key.
    Readable by ME, WHA, and Asia backends for convergence detection.
    """
    nuc_level, _ = vectors.get('nuclear',    (0, None))
    arc_level, _ = vectors.get('arctic',     (0, None))
    hyb_level, _ = vectors.get('hybrid',     (0, None))

    # v1.1.0 — Russia-Iran axis level from dedicated actor
    russia_iran_level = actor_results.get('russia_iran_axis', {}).get('escalation_level', 0)

    fingerprint = {
        'russia': {
            'updated_at':          datetime.now(timezone.utc).isoformat(),
            'russia_military_level': actor_results.get('russia_military',  {}).get('escalation_level', 0),
            'russia_gov_level':      actor_results.get('russia_government',{}).get('escalation_level', 0),
            'ukraine_level':         actor_results.get('ukraine',          {}).get('escalation_level', 0),
            'nato_level':            actor_results.get('nato_alliance',    {}).get('escalation_level', 0),
            'nuclear_level':         nuc_level,
            'arctic_level':          arc_level,
            'hybrid_level':          hyb_level,
            'belarus_level':         actor_results.get('belarus',          {}).get('escalation_level', 0),
            # ── v1.1.0 Russia-Iran axis (April 2026) ──
            # Written from Russia's perspective: what Russia is DOING.
            # Severity level (0-5) from dedicated russia_iran_axis actor:
            'russia_iran_perspective_level': russia_iran_level,
            # Cross-theater coordination signals (binary flags preserved):
            # iran_russia_active now prefers the dedicated axis actor level
            # over the generic hybrid vector — axis actor is the canonical signal.
            'iran_russia_active':    russia_iran_level >= 2 or hyb_level >= 3,
            'dprk_russia_active':    hyb_level >= 3,
            'arctic_elevated':       arc_level >= 3,
            'nuclear_signaling':     nuc_level >= 3,
        }
    }

    existing = _redis_get(CROSSTHEATER_KEY) or {}
    existing.update(fingerprint)
    _redis_set(CROSSTHEATER_KEY, existing)
    print(f"[Russia Rhetoric] Cross-theater fingerprint written")


# ============================================
# MAIN SCAN
# ============================================

def run_russia_rhetoric_scan(force=False):
    """Full Russia rhetoric scan. Returns result dict."""
    global _rhetoric_running

    with _rhetoric_lock:
        if _rhetoric_running and not force:
            print("[Russia Rhetoric] Scan already running -- returning cached")
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return cached
            return {'success': False, 'error': 'Scan in progress'}
        _rhetoric_running = True

    try:
        print("[Russia Rhetoric] Starting scan...")
        start = time.time()

        articles = _fetch_all_articles()
        actor_results, vectors = _classify_articles(articles)
        theatre_score = _compute_theatre_score(actor_results, vectors)
        conditional_threats = _detect_conditional_threats(articles)

        # Vector level labels
        nuc_level, nuc_trigger = vectors.get('nuclear',    (0, None))
        gnd_level, gnd_trigger = vectors.get('ground_ops', (0, None))
        nat_level, nat_trigger = vectors.get('nato_flank', (0, None))
        arc_level, arc_trigger = vectors.get('arctic',     (0, None))
        hyb_level, hyb_trigger = vectors.get('hybrid',     (0, None))

        def _lvl(n):
            return ESCALATION_LEVELS.get(n, {}).get('label', 'Monitoring')

        scan_time = round(time.time() - start, 1)

        result = {
            'success':              True,
            'theatre':              'Russia',
            'theatre_score':        theatre_score,
            'rhetoric_score':       theatre_score,
            'theatre_level':        max(
                actor_results.get('russia_military',  {}).get('escalation_level', 0),
                actor_results.get('russia_government',{}).get('escalation_level', 0),
                nuc_level
            ),
            'theatre_escalation_label': _lvl(max(
                actor_results.get('russia_military',  {}).get('escalation_level', 0),
                actor_results.get('russia_government',{}).get('escalation_level', 0),
                nuc_level
            )),
            'theatre_color':        '#dc2626',
            'actors':               actor_results,
            # Vectors
            'nuclear_level':        nuc_level,
            'nuclear_label':        _lvl(nuc_level),
            'ground_ops_level':     gnd_level,
            'ground_ops_label':     _lvl(gnd_level),
            'nato_flank_level':     nat_level,
            'nato_flank_label':     _lvl(nat_level),
            'arctic_level':         arc_level,
            'arctic_label':         _lvl(arc_level),
            'hybrid_level':         hyb_level,
            'hybrid_label':         _lvl(hyb_level),
            # Metadata
            'total_articles':       len(articles),
            'articles_classified':  sum(a.get('statement_count', 0) for a in actor_results.values()),
            'conditional_threats':  conditional_threats,
            'scan_time_seconds':    scan_time,
            'scanned_at':           datetime.now(timezone.utc).isoformat(),
            'timestamp':            datetime.now(timezone.utc).isoformat(),
            'from_cache':           False,
            'refresh_triggered':    True,
            'version':              '1.0.0',
        }

        # Wire signals interpreter
        try:
            from russia_signal_interpreter import interpret_signals as _interpret
            result['interpretation'] = _interpret(result)
            print("[Russia Rhetoric] Signals interpreter complete")
        except Exception as ie:
            print(f"[Russia Rhetoric] Interpreter error: {str(ie)[:80]}")

        # v2.0: Build top_signals[] for BLUF/GPI consumption
        try:
            from russia_signal_interpreter import build_top_signals
            result['top_signals'] = build_top_signals(result)
            print(f"[Russia Rhetoric] top_signals: {len(result['top_signals'])} emitted")
        except Exception as e:
            print(f"[Russia Rhetoric] build_top_signals error: {str(e)[:120]}")
            result['top_signals'] = []

        # Write to Redis
        _redis_set(RHETORIC_CACHE_KEY, result)
        _redis_lpush_trim(HISTORY_KEY, {
            'score':       theatre_score,
            'scanned_at':  result['scanned_at'],
            'nuc_level':   nuc_level,
            'gnd_level':   gnd_level,
            'nat_level':   nat_level,
            'arc_level':   arc_level,
            'hyb_level':   hyb_level,
        })
        _write_crosstheater_fingerprint(actor_results, vectors)

        print(f"[Russia Rhetoric] Scan complete: score={theatre_score}, "
              f"nuc=L{nuc_level}, gnd=L{gnd_level}, nato=L{nat_level}, "
              f"arctic=L{arc_level}, hybrid=L{hyb_level} "
              f"({scan_time}s, {len(articles)} articles)")
        return result

    except Exception as e:
        print(f"[Russia Rhetoric] Scan error: {str(e)[:200]}")
        return {'success': False, 'error': str(e)[:200]}
    finally:
        _rhetoric_running = False


# ============================================
# BACKGROUND REFRESH
# ============================================

def _background_refresh():
    """Background thread: refresh every SCAN_INTERVAL_HOURS hours."""
    time.sleep(90)  # Boot delay
    while True:
        try:
            print("[Russia Rhetoric] Background refresh starting...")
            run_russia_rhetoric_scan(force=True)
        except Exception as e:
            print(f"[Russia Rhetoric] Background refresh error: {str(e)[:80]}")
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print("[Russia Rhetoric] Background refresh thread started")


# ============================================
# FLASK ENDPOINTS
# ============================================

def register_russia_rhetoric_endpoints(app):

    @app.route('/api/rhetoric/russia', methods=['GET'])
    def russia_rhetoric():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        if not force:
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return jsonify(cached)

        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(run_russia_rhetoric_scan, True)
        executor.shutdown(wait=False)

        try:
            result = future.result(timeout=25)
            return jsonify(result)
        except Exception:
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                cached['scan_triggered'] = True
                return jsonify(cached)
            return jsonify({'success': False, 'error': 'Scan timeout, no cache available'}), 503

    @app.route('/api/rhetoric/russia/summary', methods=['GET'])
    def russia_rhetoric_summary():
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if not cached:
            return jsonify({'success': False, 'error': 'No data yet -- trigger a scan first'}), 404

        actors = cached.get('actors', {})
        # v1.1.0 (May 6 2026): surface interpretation block on /summary so stability
        # page rhetoric card can render full BLUF without round-tripping the heavy endpoint.
        interp = cached.get('interpretation', {}) or {}
        so_what = interp.get('so_what', {}) or {}
        red_lines = interp.get('red_lines', {}) or {}
        diplomatic_track = interp.get('diplomatic_track', {}) or {}
        # Top 3 red lines for card surface (full list available on /api/rhetoric/russia)
        top_red_lines = (red_lines.get('triggered') or [])[:3]
        return jsonify({
            'success':         True,
            'theatre_score':   cached.get('theatre_score', 0),
            'theatre_level':   cached.get('theatre_level', 0),
            'nuclear_level':   cached.get('nuclear_level', 0),
            'ground_ops_level': cached.get('ground_ops_level', 0),
            'nato_flank_level': cached.get('nato_flank_level', 0),
            'arctic_level':    cached.get('arctic_level', 0),
            'hybrid_level':    cached.get('hybrid_level', 0),
            'russia_military_level':  actors.get('russia_military',  {}).get('escalation_level', 0),
            'russia_gov_level':       actors.get('russia_government',{}).get('escalation_level', 0),
            'ukraine_level':          actors.get('ukraine',          {}).get('escalation_level', 0),
            'total_articles':         cached.get('total_articles', 0),
            # ── v1.1.0: Strategic Assessment surface ──
            'so_what_scenario':       so_what.get('scenario', ''),
            'so_what_scenario_color': so_what.get('scenario_color', '#6b7280'),
            'so_what_scenario_icon':  so_what.get('scenario_icon', '⚪'),
            'so_what_situation':      so_what.get('situation', ''),
            'so_what_assessment':     so_what.get('assessment', ''),
            'so_what_watch_list':     so_what.get('watch_list', [])[:5],
            # ── v1.1.0: Red Lines summary ──
            'red_lines_breached':     red_lines.get('breached_count', 0),
            'red_lines_approaching':  red_lines.get('approaching_count', 0),
            'top_red_lines':          top_red_lines,
            # ── v1.1.0: Diplomatic Track summary ──
            'diplomatic_score':       diplomatic_track.get('score', 0),
            'diplomatic_scenario':    diplomatic_track.get('scenario', ''),
            'diplomatic_color':       diplomatic_track.get('scenario_color', '#6b7280'),
            'maximum_pressure':       diplomatic_track.get('maximum_pressure', False),
            'scanned_at':      cached.get('scanned_at', ''),
            'from_cache':      True,
        })

    @app.route('/api/rhetoric/russia/history', methods=['GET'])
    def russia_rhetoric_history():
        history = _redis_get(HISTORY_KEY) or []
        return jsonify({'success': True, 'history': history, 'count': len(history)})

    print("[Russia Rhetoric] Endpoints registered: /api/rhetoric/russia, /summary, /history")
