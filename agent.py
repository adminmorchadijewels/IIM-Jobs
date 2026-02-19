#!/usr/bin/env python3
"""
IIM Jobs Agent
==============
Logs in to iimjobs.com and fetches all jobs posted in the last 7 days.
Results are saved as a JSON file in the output/ directory.

Usage:
    python agent.py

Requirements:
    - .env file with IIMJOBS_EMAIL and IIMJOBS_PASSWORD set
    - Playwright installed: pip install playwright && python -m playwright install chromium
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

load_dotenv()

# --- Configuration ---
BASE_URL = "https://www.iimjobs.com"
EMAIL = os.getenv("IIMJOBS_EMAIL")
PASSWORD = os.getenv("IIMJOBS_PASSWORD")
# Personalized feed URL — set IIMJOBS_FEED_URL in .env to use your own feed
# (e.g. https://www.iimjobs.com/jobfeed?minexp=2&maxexp=3&_r=fi72stfujq5)
FEED_URL = os.getenv("IIMJOBS_FEED_URL", f"{BASE_URL}/j/?freshness=7")
OUTPUT_DIR = Path("output")
DAYS_BACK = 7
REQUEST_DELAY = 1.5  # seconds between page requests (be respectful)


# ---------------------------------------------------------------------------
# Date Parsing
# ---------------------------------------------------------------------------

def parse_posted_date(date_text: str) -> datetime | None:
    """
    Parse various date formats used by iimjobs.com into a datetime object.
    Handles: "2 days ago", "today", "yesterday", "3 weeks ago", "15 Jan 2026", etc.
    """
    text = date_text.strip().lower()
    now = datetime.now()

    if not text:
        return None

    # "X minutes ago" / "X hours ago" / "just now"
    if "just now" in text or re.search(r"\d+\s+minute", text) or re.search(r"\d+\s+hour", text):
        return now

    # "today"
    if "today" in text:
        return now

    # "yesterday"
    if "yesterday" in text:
        return now - timedelta(days=1)

    # "X days ago"
    m = re.search(r"(\d+)\s+day", text)
    if m:
        return now - timedelta(days=int(m.group(1)))

    # "X weeks ago"
    m = re.search(r"(\d+)\s+week", text)
    if m:
        return now - timedelta(weeks=int(m.group(1)))

    # "X months ago"
    m = re.search(r"(\d+)\s+month", text)
    if m:
        return now - timedelta(days=int(m.group(1)) * 30)

    # Specific date strings like "15 Jan 2026", "January 15, 2026"
    for fmt in ["%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y", "%d-%m-%Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_text.strip(), fmt)
        except ValueError:
            continue

    return None


def is_within_last_n_days(date_text: str, days: int = DAYS_BACK) -> bool:
    """Return True if date_text represents a date within the last `days` days."""
    parsed = parse_posted_date(date_text)
    if parsed is None:
        return False
    cutoff = datetime.now() - timedelta(days=days)
    return parsed >= cutoff


def is_older_than_n_days(date_text: str, days: int = DAYS_BACK) -> bool:
    """Return True if the date is strictly older than `days` days."""
    parsed = parse_posted_date(date_text)
    if parsed is None:
        return False
    cutoff = datetime.now() - timedelta(days=days)
    return parsed < cutoff


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login(page) -> bool:
    """
    Navigate to iimjobs.com, find the login form, and authenticate.
    Returns True on success.
    """
    if not EMAIL or not PASSWORD:
        print("[ERROR] IIMJOBS_EMAIL and IIMJOBS_PASSWORD must be set in your .env file.")
        return False

    print(f"[*] Navigating to {BASE_URL} ...")
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)

    # Try clicking a Sign In / Login link to open the login form or redirect
    login_link_selectors = [
        "a[href*='login']",
        "a[href*='signin']",
        "a:text-is('Sign In')",
        "a:text-is('Login')",
        "button:text-is('Sign In')",
        "button:text-is('Login')",
        ".sign-in",
        "#sign-in",
    ]

    clicked = False
    for sel in login_link_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                clicked = True
                print(f"[*] Clicked login trigger: {sel}")
                break
        except Exception:
            continue

    if not clicked:
        # Fall back to the direct login page
        print("[*] No login link found on homepage, trying /login directly ...")
        page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=20000)

    # Wait for email field
    try:
        page.wait_for_selector(
            "input[type='email'], input[name='email'], input[placeholder*='email' i]",
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        # Maybe the login modal is elsewhere
        print("[!] Could not find email field. Trying /login URL ...")
        page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_selector(
            "input[type='email'], input[name='email'], input[placeholder*='email' i]",
            timeout=10000,
        )

    # Fill credentials
    email_field = page.locator(
        "input[type='email'], input[name='email'], input[placeholder*='email' i]"
    ).first
    email_field.fill(EMAIL)

    password_field = page.locator("input[type='password']").first
    password_field.fill(PASSWORD)

    # Submit
    submit_sel = (
        "button[type='submit'], "
        "input[type='submit'], "
        "button:text-is('Sign In'), "
        "button:text-is('Login'), "
        "button:text-is('Log In')"
    )
    page.locator(submit_sel).first.click()

    # Wait for page to settle after submit
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    time.sleep(2)

    # Verify login success
    post_url = page.url
    logout_visible = page.locator(
        "a:text-is('Logout'), a:text-is('Sign Out'), "
        "a[href*='logout'], a[href*='signout'], "
        "[class*='logout'], [class*='sign-out']"
    ).count()

    if logout_visible > 0 or "dashboard" in post_url or "profile" in post_url:
        print("[+] Login successful!")
        return True

    # Check for error banners
    error_el = page.locator(".error, .alert-danger, [class*='error-msg'], [class*='login-error']").first
    if error_el.count() > 0:
        try:
            if error_el.is_visible(timeout=2000):
                print(f"[ERROR] Login failed: {error_el.text_content().strip()}")
                return False
        except Exception:
            pass

    # Still on login page → failed
    if "login" in page.url.lower() or "signin" in page.url.lower():
        print("[ERROR] Login failed — still on login page after submit.")
        return False

    # Otherwise, assume success
    print(f"[*] Login status unclear (URL: {page.url}) — proceeding anyway.")
    return True


# ---------------------------------------------------------------------------
# Job Extraction from a Listing Card
# ---------------------------------------------------------------------------

def extract_card(card) -> dict | None:
    """Extract job details from a single job-card element on the listing page."""
    job = {}

    # Title + URL
    title_link = card.locator(
        "a.job-title, h2 a, h3 a, .title a, "
        "a[href*='/job/'], a[href*='/j/'], a[href*='iimjobs.com']"
    ).first
    if title_link.count() == 0:
        return None

    job["title"] = (title_link.text_content() or "").strip()
    href = title_link.get_attribute("href") or ""
    job["url"] = href if href.startswith("http") else f"{BASE_URL}{href}"

    if not job["title"]:
        return None

    # Posted date (first selector that resolves)
    date_selectors = [
        "[class*='date']",
        "[class*='posted']",
        "[class*='time']",
        "span:has-text(' ago')",
        "span:has-text('today')",
        "span:has-text('yesterday')",
    ]
    date_text = ""
    for sel in date_selectors:
        el = card.locator(sel).first
        if el.count() > 0:
            candidate = (el.text_content() or "").strip()
            if candidate:
                date_text = candidate
                break
    job["posted_date"] = date_text

    # Company
    company_el = card.locator("[class*='company'], [class*='employer'], .org-name, .comp-name").first
    if company_el.count() > 0:
        job["company"] = (company_el.text_content() or "").strip()

    # Experience
    exp_el = card.locator("[class*='exp'], [class*='experience'], [class*='yrs']").first
    if exp_el.count() > 0:
        job["experience"] = (exp_el.text_content() or "").strip()

    # Location
    loc_el = card.locator("[class*='loc'], [class*='location'], .city, .cities").first
    if loc_el.count() > 0:
        job["location"] = (loc_el.text_content() or "").strip()

    # Salary / CTC
    sal_el = card.locator("[class*='sal'], [class*='salary'], [class*='ctc'], [class*='lpa']").first
    if sal_el.count() > 0:
        job["salary"] = (sal_el.text_content() or "").strip()

    # Skills / Tags
    skill_els = card.locator("[class*='skill'], [class*='tag'], [class*='keyword']").all()
    if skill_els:
        job["skills"] = [s.text_content().strip() for s in skill_els if s.text_content().strip()]

    job["fetched_at"] = datetime.now().isoformat()
    return job


# ---------------------------------------------------------------------------
# Fetch Jobs (paginated)
# ---------------------------------------------------------------------------

def fetch_all_jobs(page) -> list[dict]:
    """
    Iterate through iimjobs.com job listing pages and collect jobs
    posted within the last DAYS_BACK days.
    Stops pagination once jobs older than DAYS_BACK are encountered.
    """
    jobs: list[dict] = []
    cutoff = datetime.now() - timedelta(days=DAYS_BACK)
    page_num = 1

    print(f"\n[*] Feed URL : {FEED_URL}")
    print(f"[*] Collecting jobs posted after {cutoff.strftime('%Y-%m-%d')} ...")
    print(f"[*] Starting pagination ...\n")

    while True:
        url = f"{FEED_URL}&page={page_num}" if page_num > 1 else FEED_URL
        print(f"[*] Page {page_num}: {url}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            # Give JS-rendered content time to appear
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass  # networkidle can be flaky; carry on
        except PlaywrightTimeoutError:
            print(f"[!] Timeout loading page {page_num}. Stopping.")
            break

        # Small extra wait for dynamic content
        time.sleep(2)

        # Collect job card elements — try multiple selector strategies
        card_selectors = [
            # iimjobs specific
            ".job-list-item",
            ".job-card",
            "[class*='job-item']",
            "[class*='jobItem']",
            "[class*='job_item']",
            "li.job",
            "div[data-job-id]",
            "div[data-jobid]",
            "article.job",
            ".jobs-list > li",
            ".result",
            ".jobTuple",
            ".jobTupleHeader",
            # Generic fallbacks — any list-item/div containing a job link
            "li:has(a[href*='/job/'])",
            "li:has(a[href*='/j/'])",
            "div:has(a[href*='/job/'])",
            "article:has(a[href*='/job/'])",
        ]
        cards = []
        for sel in card_selectors:
            found = page.locator(sel).all()
            if found:
                cards = found
                print(f"[*] Using card selector '{sel}' — found {len(cards)} cards")
                break

        if not cards:
            # Save debug snapshot so we can inspect the actual HTML
            debug_dir = OUTPUT_DIR / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = debug_dir / f"page{page_num}_screenshot.png"
            html_path = debug_dir / f"page{page_num}_source.html"
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
                html_path.write_text(page.content(), encoding="utf-8")
                print(f"[!] No job cards found. Debug files saved:")
                print(f"    Screenshot : {screenshot_path}")
                print(f"    HTML source: {html_path}")
                print("[!] Open the HTML file to inspect the actual page structure.")
            except Exception as dbg_err:
                print(f"[!] Could not save debug snapshot: {dbg_err}")
            print("[!] No job cards found on this page. Stopping pagination.")
            break

        stop_pagination = False
        page_jobs_added = 0

        for card in cards:
            job = extract_card(card)
            if not job:
                continue

            date_text = job.get("posted_date", "")

            # If we can parse the date and it's older than our window, stop
            if date_text and is_older_than_n_days(date_text):
                print(f"  [!] Found old job ('{date_text}'). Stopping pagination.")
                stop_pagination = True
                break

            # Accept the job (within window, or date unreadable — include to be safe)
            jobs.append(job)
            page_jobs_added += 1
            title = job.get("title", "Unknown")
            company = job.get("company", "Unknown")
            print(f"  [+] {title} @ {company}  [{date_text}]")

        print(f"  -> Added {page_jobs_added} jobs from page {page_num}")

        if stop_pagination:
            break

        # Check for a "next page" link — if absent, we've hit the last page
        next_link = page.locator("a[rel='next'], a:text-is('Next'), .pagination .next").first
        if next_link.count() == 0 or not next_link.is_visible(timeout=2000):
            print("[*] No next page found. Done.")
            break

        page_num += 1
        time.sleep(REQUEST_DELAY)

    return jobs


# ---------------------------------------------------------------------------
# Save Results
# ---------------------------------------------------------------------------

def save_jobs(jobs: list[dict]) -> Path:
    """Persist the collected jobs to a timestamped JSON file."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"iimjobs_{timestamp}.json"

    payload = {
        "fetched_at": datetime.now().isoformat(),
        "portal": BASE_URL,
        "days_back": DAYS_BACK,
        "total_jobs": len(jobs),
        "jobs": jobs,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"\n[+] Saved {len(jobs)} jobs to: {output_file}")
    return output_file


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  IIM Jobs Agent — Last 7 Days")
    print("=" * 60)

    if not EMAIL or not PASSWORD:
        print("\n[ERROR] Missing credentials.")
        print("  1. Copy .env.example to .env")
        print("  2. Fill in your IIMJOBS_EMAIL and IIMJOBS_PASSWORD")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,  # Set to False to watch the browser in action
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        try:
            # Step 1: Login
            if not login(page):
                print("\n[FATAL] Could not log in. Aborting.")
                return

            # Step 2: Fetch jobs
            jobs = fetch_all_jobs(page)

            # Step 3: Save results
            if jobs:
                output_file = save_jobs(jobs)
                print(f"\n[DONE] Found {len(jobs)} jobs from the last {DAYS_BACK} days.")
                print(f"       Results: {output_file}")
            else:
                print("\n[DONE] No jobs found from the last 7 days.")

        except KeyboardInterrupt:
            print("\n[!] Interrupted by user.")
        except Exception as exc:
            print(f"\n[ERROR] Unexpected error: {exc}")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
