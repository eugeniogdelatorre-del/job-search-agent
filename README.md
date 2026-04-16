# Job Search Scoring Configurator

A config-driven, real-time job scoring dashboard paired with an optimized staggered scraper. Built to maximize free tier limits on GitHub Actions and Vercel.

## Architecture

```
Bot (GitHub Actions)          Artifact (Vercel)
 |                              |
 |  5 groups, 5x/day           |  React dashboard
 |  ~85 career sources         |  6-dimension scoring
 |  -> jobs.json               |  Real-time weight tuning
 |  -> git push                |  A/B comparison
 |  -> auto-deploy             |  Config export
```

## Quick Start

### 1. Fork this repo

Make it **public** to get unlimited GitHub Actions minutes (private = 2,000 min/month cap).

### 2. Set up Vercel

```bash
npm i -g vercel
vercel login
vercel link  # Link to this project
```

Copy the values from `.vercel/project.json` and add these GitHub Secrets:
- `VERCEL_TOKEN` - Get from vercel.com/account/tokens
- `VERCEL_ORG_ID` - From `.vercel/project.json`
- `VERCEL_PROJECT_ID` - From `.vercel/project.json`

### 3. Customize your config

Edit `config.json` to match your profile:
- `target_roles` - Job titles you want
- `target_verticals` - Web3 sectors you prefer
- `salary_floor_usd` - Minimum annual salary
- `scoring.dimensions` - Adjust default weights
- `exclude_keywords` - Titles to skip

### 4. Run the first scrape

Trigger manually from GitHub Actions > "Staggered Career Scraper" > Run workflow > group: "all"

## Free Tier Budget

| Platform | Limit | Our Usage | Headroom |
|----------|-------|-----------|----------|
| GitHub Actions (public repo) | Unlimited | 5 runs/day (~25 min) | Unlimited |
| Vercel deploys/day | 100 | 5 | 95% buffer |
| Vercel bandwidth/month | 100 GB | ~500 MB | 99.5% buffer |
| Vercel build minutes/month | 6,000 | ~150 | 97.5% buffer |

## Scraping Schedule (UTC)

| Time | Group | Sources | Focus |
|------|-------|---------|-------|
| 06:00 | 1 | 17 | Mega-cap L1s, L2s, CEXs |
| 10:00 | 2 | 17 | DeFi, exchanges, custody, RWA |
| 14:00 | 3 | 16 | Gaming, AI, infra, dev tools |
| 18:00 | 4 | 16 | Job boards & aggregators |
| 22:00 | 5 | 20 | VCs, niche, user-added sources |
| 22:30 | 6 | 5 | X / Twitter handles via Nitter RSS |

## Multi-Tenant Usage

Other job seekers can fork and customize by editing only `config.json`:

1. Fork the repo
2. Edit `config.json` with your profile
3. Optionally add/remove sources in `scraper/career_sources.json`
4. Set up Vercel (3 secrets)
5. Done - your personal job radar is running

## Project Structure

```
.github/workflows/
  scrape.yml           # Main staggered scraper + deploy workflow
  keepalive.yml        # Prevents 60-day auto-disable on public repos
scraper/
  scrape.py            # Python scraper with group-based execution
  career_sources.json  # All 85 career page URLs in 5 groups
  requirements.txt     # Python dependencies
public/
  index.html           # React scoring configurator (standalone)
  data/jobs.json       # Scraped job data (auto-updated)
config.json            # User-configurable scoring & preferences
vercel.json            # Vercel deployment config
```

## Dashboard Features

- **6-dimension weight sliders** - Tune role fit, vertical, channel quality, team stage, geo, and metrics clarity
- **Real-time re-scoring** - Scores update instantly as you drag
- **A/B compare mode** - Save a snapshot, adjust weights, see the delta
- **Category filters** - Filter by L1, DeFi, CEX, Gaming, etc.
- **Score distribution** - See hot/warm/cold/skip breakdown
- **Config export** - Download your weight configuration as JSON

## License

MIT
