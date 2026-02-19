# IIM Jobs Agent

An AI agent that logs in to [iimjobs.com](https://www.iimjobs.com) and fetches all jobs posted in the last 7 days, saving the results as a structured JSON file.

## How It Works

1. Launches a headless Chromium browser via Playwright
2. Logs in using your iimjobs.com credentials
3. Iterates through job listings, collecting every job posted within the last 7 days
4. Saves results to `output/iimjobs_<timestamp>.json`

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` and fill in your iimjobs.com login details:

```
IIMJOBS_EMAIL=your_email@example.com
IIMJOBS_PASSWORD=your_password_here
```

> **Note:** The `.env` file is git-ignored and will never be committed.

### 3. Run the agent

```bash
python agent.py
```

## Output

Results are saved in the `output/` directory as a JSON file:

```json
{
  "fetched_at": "2026-02-19T10:30:00.000000",
  "portal": "https://www.iimjobs.com",
  "days_back": 7,
  "total_jobs": 42,
  "jobs": [
    {
      "title": "Senior Product Manager",
      "company": "Acme Corp",
      "experience": "5-10 years",
      "location": "Bangalore",
      "salary": "25-40 LPA",
      "skills": ["Product Management", "Agile", "Analytics"],
      "posted_date": "2 days ago",
      "url": "https://www.iimjobs.com/j/...",
      "fetched_at": "2026-02-19T10:30:00.000000"
    }
  ]
}
```

## Configuration

| Variable | Description | Default |
|---|---|---|
| `IIMJOBS_EMAIL` | Your iimjobs.com login email | *(required)* |
| `IIMJOBS_PASSWORD` | Your iimjobs.com password | *(required)* |

To change the look-back window (default: 7 days), edit `DAYS_BACK` in `agent.py`:

```python
DAYS_BACK = 7  # Change to any number of days
```

To watch the browser in action (non-headless mode), set `headless=False` in `agent.py`:

```python
browser = p.chromium.launch(headless=False)
```
