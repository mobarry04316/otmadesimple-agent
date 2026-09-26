"""
analyze_performance.py

Runs weekly (separate from the 3x/day posting workflow). For each logged
post at least 48 hours old (TikTok's view/reach insights lag behind
publish time), pulls real performance data from Zernio's analytics API
and writes a short summary of what's working -- which generate_tips.py
then feeds back to Claude so future topics lean into what's actually
resonating.

Requires the same ZERNIO_API_KEY / ZERNIO_TIKTOK_ACCOUNT_ID as posting.
"""

import os
import json
import datetime
import subprocess
import requests

API_BASE = "https://zernio.com/api/v1"
LOG_PATH = os.path.join(os.path.dirname(__file__), "post_log.json")
SUMMARY_PATH = os.path.join(os.path.dirname(__file__), "performance_summary.json")

MIN_AGE_HOURS = 48       # give TikTok's insights time to populate
TOP_N = 5
BOTTOM_N = 5


def _headers():
    key = os.environ.get("ZERNIO_API_KEY")
    return {"Authorization": f"Bearer {key}"}


def _load_log():
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH) as f:
        return json.load(f)


def _save_log(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def fetch_analytics(post_id):
    """
    Returns a dict of metrics for one post, or None if TikTok's insights
    aren't ready yet (202) or the lookup failed (424 or other error).
    """
    resp = requests.get(
        f"{API_BASE}/analytics",
        headers=_headers(),
        params={"postId": post_id, "platform": "tiktok"},
    )
    if resp.status_code == 202:
        print(f"  {post_id}: sync pending, try again next week")
        return None
    if resp.status_code != 200:
        print(f"  {post_id}: analytics fetch failed ({resp.status_code})")
        return None

    data = resp.json()
    analytics = data.get("analytics") or data.get("data", {}).get("analytics")
    return analytics


def _engagement_score(analytics):
    """
    Prefer views-normalized engagement rate; fall back to raw
    likes+comments+shares if views aren't populated yet.
    """
    if not analytics:
        return None
    likes = analytics.get("likes") or 0
    comments = analytics.get("comments") or 0
    shares = analytics.get("shares") or 0
    views = analytics.get("views") or 0

    if views and views > 0:
        return (likes + comments + shares) / views
    return likes + comments + shares  # unnormalized fallback


def run():
    entries = _load_log()
    if not entries:
        print("No logged posts yet -- nothing to analyze.")
        return

    now = datetime.datetime.utcnow()
    updated = False

    for entry in entries:
        posted_at = datetime.datetime.fromisoformat(entry["posted_at"].rstrip("Z"))
        age_hours = (now - posted_at).total_seconds() / 3600

        if age_hours < MIN_AGE_HOURS:
            continue  # too soon, insights likely not populated yet

        print(f"Fetching analytics for post {entry['post_id']} ({entry['topic']!r})...")
        analytics = fetch_analytics(entry["post_id"])
        if analytics is not None:
            entry["analytics"] = analytics
            updated = True

    if updated:
        _save_log(entries)

    # Build the ranked summary from whatever posts have analytics so far
    scored = []
    for entry in entries:
        score = _engagement_score(entry.get("analytics"))
        if score is not None:
            scored.append({
                "topic": entry["topic"],
                "hook": entry["hook"],
                "score": score,
                "analytics": entry["analytics"],
            })

    if not scored:
        print("No posts with analytics data yet -- summary not updated.")
        return

    scored.sort(key=lambda x: x["score"], reverse=True)
    top_performers = scored[:TOP_N]
    underperformers = scored[-BOTTOM_N:] if len(scored) > TOP_N else []

    summary = {
        "generated_at": now.isoformat() + "Z",
        "posts_analyzed": len(scored),
        "top_performers": [
            {"topic": p["topic"], "hook": p["hook"]} for p in top_performers
        ],
        "underperformers": [
            {"topic": p["topic"], "hook": p["hook"]} for p in underperformers
        ],
    }

    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote performance_summary.json ({len(scored)} posts analyzed)")

    # Commit both files back to the repo
    try:
        subprocess.run(["git", "config", "user.name", "otmadesimple-agent"], check=True)
        subprocess.run(["git", "config", "user.email", "agent@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", "post_log.json", "performance_summary.json"], check=True)
        subprocess.run(["git", "commit", "-m", "Update performance analytics", "--allow-empty"], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"WARNING: failed to commit analytics update: {e}")


if __name__ == "__main__":
    run()
