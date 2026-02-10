"""
LSD.law Admission Wave Notifier
================================
Scrapes https://lsd.law/recent-decisions for new law school admission waves
and sends push notifications via ntfy.sh.

The recent-decisions page uses a Phoenix LiveView AG Grid component that stores
decision data as compressed JSON in a hidden input (#decisions-grid-grid-data).
The data is double-wrapped: {"compressed": true, "data": {"compressed": true,
"data": "<base64-encoded zlib>"}}. Inside the compressed payload is a dict with
"schema" (column names) and "data" (rows as arrays).

This script uses Playwright to load the page (allowing LiveView to hydrate),
extracts the compressed grid data, decompresses it, converts to dicts, then
diffs against the previous run to detect new admission waves.
"""

import base64
import json
import sys
import zlib
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

import config

STATE_FILE = Path(__file__).parent / "state.json"


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load the previous run's state from state.json."""
    if STATE_FILE.exists():
        text = STATE_FILE.read_text().strip()
        if text:
            return json.loads(text)
    return {}


def save_state(state: dict) -> None:
    """Write the current state to state.json."""
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_decisions() -> tuple[list[dict], dict]:
    """
    Load the recent-decisions page with Playwright, wait for the AG Grid
    to populate, and extract decision data.

    Returns:
        decisions: list of dicts with keys: count, school_name, school_slug,
                   result, date, school_search_terms, etc.
        summary:   dict with today's top-line counts, e.g.
                   {"accepted": 5, "rejected": 2, "waitlisted": 1, "withdrawn": 0}
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        print(f"  Loading {config.CHECK_URL} ...")
        page.goto(config.CHECK_URL, wait_until="domcontentloaded", timeout=30000)

        # Wait for LiveView to hydrate and the AG Grid data to appear.
        # The hidden input #decisions-grid-grid-data holds the JSON rows.
        # If it stays "[]" after the timeout, there are genuinely no decisions
        # right now (off-hours or start of day).
        try:
            page.wait_for_function(
                """() => {
                    const el = document.getElementById('decisions-grid-grid-data');
                    return el && el.value && el.value !== '[]';
                }""",
                timeout=20000,
            )
            print("  Grid data loaded.")
        except PlaywrightTimeout:
            print("  Grid data still empty after 20s (likely no decisions right now).")

        # ---- Extract AG Grid JSON data ----
        grid_data_raw = page.evaluate(
            """() => {
                const el = document.getElementById('decisions-grid-grid-data');
                return el ? el.value : '[]';
            }"""
        )

        # ---- Extract today's summary counts ----
        summary = {}
        for decision_type in ["Accepted", "Rejected", "Waitlisted", "Withdrawn"]:
            count = page.evaluate(
                """(dtype) => {
                    const spans = document.querySelectorAll(
                        '#recent-updates-component span'
                    );
                    for (const span of spans) {
                        const text = span.textContent.trim();
                        if (text.endsWith(dtype)) {
                            const num = parseInt(text.replace(dtype, '').trim(), 10);
                            return isNaN(num) ? 0 : num;
                        }
                    }
                    return 0;
                }""",
                decision_type,
            )
            summary[decision_type.lower()] = count

        browser.close()

    decisions = _decompress_grid_data(grid_data_raw)
    return decisions, summary


def _decompress_grid_data(raw_json: str) -> list[dict]:
    """
    Decompress the AG Grid hidden-input value into a list of dicts.

    The site stores grid data as:
        {"compressed": true, "data": {"compressed": true, "data": "<b64-zlib>"}}
    Inside the decompressed payload:
        {"schema": ["count", "school_name", ...], "data": [[1, "Harvard", ...], ...]}
    """
    if not raw_json:
        return []

    outer = json.loads(raw_json)

    # Handle non-compressed case (e.g. plain "[]")
    if isinstance(outer, list):
        return outer

    if not isinstance(outer, dict) or not outer.get("compressed"):
        return outer if isinstance(outer, list) else []

    # Unwrap outer compressed envelope
    inner = outer.get("data", {})
    if isinstance(inner, dict) and inner.get("compressed"):
        # Base64-decode then zlib-decompress
        compressed_b64 = inner["data"]
        decoded_bytes = base64.b64decode(compressed_b64)
        decompressed = zlib.decompress(decoded_bytes)
        payload = json.loads(decompressed)
    else:
        payload = inner

    # payload should be {"schema": [...], "data": [[...], ...]}
    if isinstance(payload, dict) and "schema" in payload and "data" in payload:
        schema = payload["schema"]  # e.g. ["count", "school_name", "result", "date", ...]
        rows = payload["data"]
        return [dict(zip(schema, row)) for row in rows]

    # Fallback: if it's already a list of dicts
    if isinstance(payload, list):
        return payload

    return []


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_decisions(decisions: list[dict]) -> list[dict]:
    """Keep only decisions for schools listed in config.SCHOOLS."""
    if not config.POLL_SCHOOLS_ONLY:
        return decisions

    watched = {name.lower() for name in config.SCHOOLS}
    return [
        d for d in decisions
        if d.get("school_name", "").lower() in watched
    ]


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

def make_key(d: dict) -> str:
    """Create a unique key for a decision row."""
    return f"{d.get('school_name', '')}|{d.get('result', '')}|{d.get('date', '')}"


def diff_decisions(current: list[dict], prev_decisions: dict) -> list[dict]:
    """
    Compare current decisions against previous state.

    A change is detected when:
      - A (school, result, date) combo doesn't exist in the previous state, OR
      - The count for that combo has increased.
    """
    changes = []

    for d in current:
        key = make_key(d)
        cur_count = int(d.get("count", 0))
        prev = prev_decisions.get(key)

        if prev is None:
            # Entirely new decision wave
            changes.append({
                "school_name": d.get("school_name", "Unknown"),
                "result": d.get("result", "Unknown"),
                "date": d.get("date", ""),
                "count": cur_count,
                "delta": cur_count,
                "is_new": True,
            })
        else:
            prev_count = int(prev.get("count", 0))
            if cur_count > prev_count:
                # Count increased — more decisions in this wave
                changes.append({
                    "school_name": d.get("school_name", "Unknown"),
                    "result": d.get("result", "Unknown"),
                    "date": d.get("date", ""),
                    "count": cur_count,
                    "delta": cur_count - prev_count,
                    "is_new": False,
                })

    return changes


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def build_message(changes: list[dict]) -> str:
    """Build a human-readable notification message from the list of changes."""
    lines = []
    for c in changes:
        result = c["result"]
        school = c["school_name"]
        delta = c["delta"]
        total = c["count"]
        date = c.get("date", "")

        if c["is_new"]:
            lines.append(f"{school}: {total} {result} ({date})")
        else:
            lines.append(f"{school}: +{delta} {result} (now {total}, {date})")

    return "\n".join(lines)


def send_notification(message: str) -> None:
    """Send a push notification via ntfy.sh."""
    resp = requests.post(
        f"https://ntfy.sh/{config.NTFY_TOPIC}",
        headers={
            "Title": "New Law School Wave!",
            "Priority": "high",
            "Tags": "scales",
            "Click": config.CHECK_URL,
        },
        data=message.encode("utf-8"),
        timeout=10,
    )
    resp.raise_for_status()
    print(f"  Notification sent (HTTP {resp.status_code}).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    now = datetime.now()
    print(f"[{now.isoformat()}] LSD Wave Notifier — checking for new decisions...")

    # 1. Scrape
    try:
        decisions, summary = scrape_decisions()
    except Exception as exc:
        print(f"  ERROR scraping: {exc}", file=sys.stderr)
        sys.exit(1)

    total_today = sum(summary.values())
    print(f"  Today's summary: {summary} (total: {total_today})")
    print(f"  Aggregated rows in grid: {len(decisions)}")

    # 2. Filter to watched schools
    filtered = filter_decisions(decisions)
    print(f"  Rows matching watched schools: {len(filtered)}")

    # 3. Load previous state and diff
    state = load_state()
    prev_decisions = state.get("decisions", {})
    changes = diff_decisions(filtered, prev_decisions)

    # 4. Notify if anything new
    if changes:
        print(f"  {len(changes)} new/updated wave(s) detected!")
        message = build_message(changes)
        print(f"  Message:\n    {message.replace(chr(10), chr(10) + '    ')}")
        try:
            send_notification(message)
        except Exception as exc:
            print(f"  ERROR sending notification: {exc}", file=sys.stderr)
    else:
        print("  No new waves. All quiet.")

    # 5. Save updated state
    new_decisions = {}
    for d in filtered:
        key = make_key(d)
        new_decisions[key] = {
            "school_name": d.get("school_name", ""),
            "result": d.get("result", ""),
            "date": d.get("date", ""),
            "count": int(d.get("count", 0)),
        }

    save_state({
        "last_check": now.isoformat(),
        "summary": summary,
        "decisions": new_decisions,
    })
    print(f"  State saved to {STATE_FILE}. Done.\n")


if __name__ == "__main__":
    main()
