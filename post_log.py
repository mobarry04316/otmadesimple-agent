"""
post_log.py

Keeps a running record of every post the agent makes -- its Zernio post
ID, topic, hook text, and caption -- so analyze_performance.py can later
look up how each one actually performed and feed that back into content
generation.
"""

import os
import json
import datetime
import subprocess

LOG_PATH = os.path.join(os.path.dirname(__file__), "post_log.json")


def _load_log():
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_log(entries):
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def log_post(post_id, topic, hook, caption):
    """Append a new post record and commit it to the repo."""
    entries = _load_log()
    entries.append({
        "post_id": post_id,
        "topic": topic,
        "hook": hook,
        "caption": caption,
        "posted_at": datetime.datetime.utcnow().isoformat() + "Z",
        "analytics": None,  # filled in later by analyze_performance.py
    })
    _save_log(entries)

    # Commit it so it persists across GitHub Actions runs (each run starts
    # from a fresh checkout of the repo, so anything not committed is lost).
    try:
        subprocess.run(["git", "config", "user.name", "otmadesimple-agent"], check=True)
        subprocess.run(["git", "config", "user.email", "agent@users.noreply.github.com"], check=True)
        subprocess.run(["git", "add", "post_log.json"], check=True)
        subprocess.run(["git", "commit", "-m", "Log post for performance tracking", "--allow-empty"], check=True)
        subprocess.run(["git", "push"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"WARNING: failed to commit post_log.json: {e}")
