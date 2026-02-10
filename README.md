# LSD.law Wave Notifier

Get push notifications on your phone when new law school admission waves drop on [lsd.law/recent-decisions](https://lsd.law/recent-decisions).

## How it works

1. A GitHub Actions cron job runs every 15 minutes during business hours (9 AM–6 PM EST, Mon–Fri)
2. It loads the recent-decisions page with a headless browser (Playwright)
3. Extracts the structured decision data from the AG Grid component
4. Filters to only the schools you care about (configured in `config.py`)
5. Compares against the last known state (`state.json`)
6. If new waves are detected, sends a push notification via [ntfy.sh](https://ntfy.sh)

## Setup

### 1. Configure your schools

Edit `config.py` and set the `SCHOOLS` list to the exact school names your friend applied to:

```python
SCHOOLS = [
    "Harvard University",
    "Columbia University",
    "Stanford University",
    # ... add your schools here
]
```

School names must match exactly as they appear on the site. Check the dropdown on [lsd.law/recent-decisions](https://lsd.law/recent-decisions).

### 2. Set your ntfy topic

In `config.py`, change `NTFY_TOPIC` to a unique, hard-to-guess string:

```python
NTFY_TOPIC = "my-secret-law-waves-xyz123"
```

### 3. Install ntfy on your phone

1. Install the **ntfy** app ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy))
2. Open the app, tap **+** to subscribe to a topic
3. Type the exact topic name from `config.py`
4. Done — you'll receive push notifications when waves happen

### 4. Deploy to GitHub

1. Create a new GitHub repository
2. Push this code to it
3. The cron workflow starts automatically — check the **Actions** tab to verify

### 5. (Optional) Test manually

From the Actions tab, click **"Check LSD Decisions"** → **"Run workflow"** to trigger a test run.

Or run locally:

```bash
pip install -r requirements.txt
playwright install chromium
python scraper.py
```

## Configuration

| Setting | File | Description |
|---------|------|-------------|
| `SCHOOLS` | `config.py` | List of school names to watch |
| `NTFY_TOPIC` | `config.py` | Your private ntfy.sh channel name |
| `POLL_SCHOOLS_ONLY` | `config.py` | `True` = only watched schools, `False` = all schools |
| `CHECK_URL` | `config.py` | URL to scrape (default: recent-decisions page) |
| Cron schedule | `.github/workflows/check.yml` | When the scraper runs (default: every 15 min, business hours) |

## Cost

**$0.** GitHub Actions free tier (2,000 min/month) and ntfy.sh are both free.
