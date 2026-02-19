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

    # Use JS to pull key fields directly from the element —
    # avoids selector brittleness when class names are opaque.
    try:
        data = card.evaluate("""el => {
            // --- Title + URL ---
            const linkEl = el.querySelector(
                'a[href*="/j/"], a[href*="/job/"], a.job-title, h2 a, h3 a, h4 a, .title a'
            );
            if (!linkEl) return null;
            const title = (linkEl.innerText || linkEl.textContent || '').trim();
            if (!title) return null;
            const href = linkEl.getAttribute('href') || '';

            // --- All text nodes in the card, for fallback parsing ---
            const allText = el.innerText || el.textContent || '';

            // --- Posted date: prefer elements whose text contains 'ago/today/yesterday' ---
            let postedDate = '';
            const allEls = el.querySelectorAll('*');
            for (const e of allEls) {
                if (e.children.length > 0) continue;  // leaf nodes only
                const t = (e.innerText || e.textContent || '').trim().toLowerCase();
                if (t && (t.includes(' ago') || t === 'today' || t === 'yesterday'
                          || /\\d+\\s+(day|week|month|hour|min)/.test(t))) {
                    postedDate = (e.innerText || e.textContent || '').trim();
                    break;
                }
            }
            // Fallback: regex on full card text
            if (!postedDate) {
                const m = allText.match(
                    /(\\d+\\s+(day|week|month|hour|min)[s]?\\s+ago|today|yesterday)/i
                );
                if (m) postedDate = m[0];
            }

            // --- Company: element with class containing 'company'/'employer'/'org' ---
            let company = '';
            const compEl = el.querySelector(
                '[class*="company"],[class*="employer"],[class*="org-name"],' +
                '[class*="comp-name"],[class*="companyName"],[class*="brand"]'
            );
            if (compEl) company = (compEl.innerText || compEl.textContent || '').trim();

            // --- Experience ---
            let experience = '';
            const expEl = el.querySelector(
                '[class*="exp"],[class*="experience"],[class*="yrs"],[class*="year"]'
            );
            if (expEl) experience = (expEl.innerText || expEl.textContent || '').trim();

            // --- Location ---
            let location = '';
            const locEl = el.querySelector(
                '[class*="loc"],[class*="location"],[class*="city"],[class*="cities"]'
            );
            if (locEl) location = (locEl.innerText || locEl.textContent || '').trim();

            // --- Salary ---
            let salary = '';
            const salEl = el.querySelector(
                '[class*="sal"],[class*="salary"],[class*="ctc"],[class*="lpa"]'
            );
            if (salEl) salary = (salEl.innerText || salEl.textContent || '').trim();

            // --- Skills ---
            const skillEls = el.querySelectorAll('[class*="skill"],[class*="tag"],[class*="keyword"]');
            const skills = Array.from(skillEls)
                .map(s => (s.innerText || s.textContent || '').trim())
                .filter(s => s.length > 0 && s.length < 60);

            return { title, href, postedDate, company, experience, location, salary, skills };
        }""")
    except Exception:
        data = None

    if not data:
        return None

    job["title"] = data.get("title", "").strip()
    if not job["title"]:
        return None

    href = data.get("href", "")
    job["url"] = href if href.startswith("http") else f"{BASE_URL}{href}"
    job["posted_date"] = data.get("postedDate", "")
    if data.get("company"):
        job["company"] = data["company"]
    if data.get("experience"):
        job["experience"] = data["experience"]
    if data.get("location"):
        job["location"] = data["location"]
    if data.get("salary"):
        job["salary"] = data["salary"]
    if data.get("skills"):
        job["skills"] = data["skills"]

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

        # Wait for job links to appear (up to 10s) before searching
        try:
            page.wait_for_selector(
                "a[href*='/j/'], a[href*='/job/']", timeout=10000
            )
        except PlaywrightTimeoutError:
            pass
        time.sleep(1)

        # --- Strategy 1: known CSS class selectors ---
        card_selectors = [
            ".job-list-item",
            ".job-card",
            "[class*='job-item']",
            "[class*='jobItem']",
            "[class*='job_item']",
            "[class*='jobfeed']",
            "[class*='feed-item']",
            "[class*='feedItem']",
            "li.job",
            "div[data-job-id]",
            "div[data-jobid]",
            "article.job",
            ".jobs-list > li",
            ".result",
            ".jobTuple",
            "[class*='tuple']",
            "[class*='Tuple']",
            "li:has(a[href*='/j/'])",
            "li:has(a[href*='/job/'])",
            "tr:has(a[href*='/j/'])",
        ]
        cards = []
        for sel in card_selectors:
            found = page.locator(sel).all()
            if found:
                cards = found
                print(f"[*] Using card selector '{sel}' — found {len(cards)} cards")
                break

        # --- Strategy 2: JS walk-up from job links (works with any class names) ---
        if not cards:
            print("[*] CSS selectors failed — trying JS walk-up from job links ...")
            handles = page.evaluate_handle("""
                () => {
                    // Find all links that look like job detail pages
                    const links = Array.from(
                        document.querySelectorAll('a[href*="/j/"], a[href*="/job/"]')
                    ).filter(a => {
                        const href = a.getAttribute('href') || '';
                        return /\\/(j|job)\\//.test(href) && a.textContent.trim().length > 5;
                    });

                    // For each link, walk up 3 levels to find the likely card container
                    const seen = new Set();
                    const containers = [];
                    links.forEach(link => {
                        let el = link;
                        for (let i = 0; i < 4; i++) {
                            if (!el.parentElement || el.parentElement === document.body) break;
                            el = el.parentElement;
                        }
                        if (!seen.has(el)) {
                            seen.add(el);
                            containers.push(el);
                        }
                    });
                    return containers;
                }
            """)
            # Convert JSHandle array to Playwright element handles
            count = page.evaluate("els => els.length", handles)
            if count:
                cards = [
                    page.evaluate_handle(f"(els) => els[{i}]", handles)
                    for i in range(count)
                ]
                print(f"[*] JS walk-up found {len(cards)} job containers")

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
