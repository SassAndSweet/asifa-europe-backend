# Asifah Analytics — Europe Backend

Flask backend powering the European Conflict Probability Dashboard at [asifahanalytics.com](https://asifahanalytics.com).

## Overview

Real-time OSINT aggregation and threat probability scoring for European geopolitical flashpoints. Monitors four active targets:

- 🇬🇱 **Greenland** — US acquisition rhetoric, Arctic sovereignty tensions
- 🇺🇦 **Ukraine** — Active war zone, Russia-Ukraine conflict
- 🇷🇺 **Russia** — Aggressor state monitoring, NATO tensions, nuclear posture
- 🇵🇱 **Poland** — NATO frontline state, border incursions, hybrid threats

## Data Sources

| Source | Coverage |
|--------|----------|
| NewsAPI | English-language global news aggregation |
| GDELT | Multilingual (English, Russian, French, Ukrainian) |
| Reddit | r/ukraine, r/europe, r/geopolitics, r/Greenland, r/poland |
| Kyiv Independent | Ukraine-focused independent journalism (RSS) |
| Meduza | Independent Russian media, English edition (RSS) |
| ISW | Institute for the Study of War daily assessments (RSS) |
| Arctic Today | Arctic/Greenland-focused reporting (RSS) |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/europe/threat/<target>` | Threat assessment (greenland, ukraine, russia, poland) |
| `GET /api/europe/notams` | European NOTAM monitoring across 8 regions |
| `GET /api/europe/flights` | European flight disruption tracking |
| `GET /rate-limit` | Rate limit status |
| `GET /health` | Health check |

## Deployment

Deployed on [Render.com](https://render.com) as a web service.

**Build Command:** `pip install -r requirements.txt`  
**Start Command:** `gunicorn app:app`  
**Environment Variable:** `NEWSAPI_KEY`

## Scoring Algorithm

Identical to the Middle East backend (v2.1.0):
- Source credibility weighting (premium → social tiers)
- Keyword severity detection (critical → moderate)
- Exponential time decay (2-day half-life)
- De-escalation signal detection
- Momentum analysis (increasing/stable/decreasing)
- Target-specific baseline adjustments

## License

See [LICENSE](LICENSE) file.

---

© 2026 Asifah Analytics. All rights reserved.
