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
REFRESH_WINDOW_DAYS = 21  # after this long, a post's numbers have settled --
                          # stop re-fetching it every week
TOP_N = 5
BOTTOM_N = 5

# How much each kind of interaction is worth. Follows and saves are the
# signals that matter for growing the page; likes are cheap and plentiful,
# so they count least. (Across the first 41 posts there were 72 follows,
# 141 saves, 6 shares and 0 comments.)
WEIGHTS = {"follows": 10, "saves": 3, "shares": 3, "comments": 2, "likes": 1}

# Small-sample smoothing. A post with 150 views and one lucky like shouldn't
# outrank a post with 1,500 views and a steady stream of saves, so every
# post's rate is blended with the account-wide average as if it had
# PRIOR_VIEWS extra views at that average. Posts with lots of views barely
# move; posts with few views get pulled toward the middle.
PRIOR_VIEWS = 300


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


def _weighted_interactions(analytics):
    return sum(weight * (analytics.get(key) or 0) for key, weight in WEIGHTS.items())


def _stats_line(analytics):
    """Compact human-readable numbers, e.g. '1352 views, 38 saves, 13 follows'."""
    parts = [f"{analytics.get('views') or 0} views"]
    for key, label in (("saves", "saves"), ("follows", "follows"),
                       ("shares", "shares"), ("comments", "comments")):
        value = analytics.get(key) or 0
        if value:
            parts.append(f"{value} {label}")
    return ", ".join(parts)


def rank_posts(entries):
    """
    Score every post that has real view data and return them best-first.

    score = (weighted interactions + PRIOR_VIEWS * account_avg_rate)
            / (views + PRIOR_VIEWS)

    Posts without views yet (insights not synced) are skipped rather than
    scored as zero.
    """
    usable = []
    for entry in entries:
        analytics = entry.get("analytics")
        if analytics and (analytics.get("views") or 0) > 0:
            usable.append((entry, analytics))

    if not usable:
        return []

    total_weighted = sum(_weighted_interactions(a) for _, a in usable)
    total_views = sum(a["views"] for _, a in usable)
    account_rate = total_weighted / total_views

    ranked = []
    for entry, analytics in usable:
        views = analytics["views"]
        score = (_weighted_interactions(analytics) + PRIOR_VIEWS * account_rate) / (views + PRIOR_VIEWS)
        ranked.append({
            "topic": entry["topic"],
            "hook": entry["hook"],
            "score": score,
            "stats": _stats_line(analytics),
            "views": views,
        })

    ranked.sort(key=lambda p: p["score"], reverse=True)
    return ranked


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

        if entry.get("analytics") and age_hours > REFRESH_WINDOW_DAYS * 24:
            continue  # numbers have settled, no need to re-fetch

        print(f"Fetching analytics for post {entry['post_id']} ({entry['topic']!r})...")
        analytics = fetch_analytics(entry["post_id"])
        if analytics is not None:
            entry["analytics"] = analytics
            updated = True

    if updated:
        _save_log(entries)

    # Build the ranked summary from whatever posts have analytics so far
    scored = rank_posts(entries)

    if not scored:
        print("No posts with analytics data yet -- summary not updated.")
        return

    top_performers = scored[:TOP_N]
    # Only name underperformers once there's enough data that the bottom of
    # the list can't overlap the top.
    underperformers = scored[-BOTTOM_N:] if len(scored) >= TOP_N + BOTTOM_N else []

    def _entry(p):
        return {"topic": p["topic"], "hook": p["hook"], "stats": p["stats"]}

    summary = {
        "generated_at": now.isoformat() + "Z",
        "posts_analyzed": len(scored),
        "top_performers": [_entry(p) for p in top_performers],
        "underperformers": [_entry(p) for p in underperformers],
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
