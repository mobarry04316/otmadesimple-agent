"""
main.py

The full agent, end to end:
  1. Generate a tip topic + slide text + caption via Claude
  2. Render the slideshow images from the template
  3. Make the images publicly reachable (see host_images())
  4. Send the slideshow to TikTok via Zernio -- published directly by
     default (no music attached; see zernio_post.py for why sounds can't
     be auto-selected)

Run manually:
    python main.py

Run automatically:
    see .github/workflows/post_slideshow.yml -- this same script is what
    that workflow calls on a schedule.
"""

import os
import sys
import time
import datetime
import requests

from generate_tips import generate_tip_set
from render_slides import render_slideshow
from zernio_post import post_photo_slideshow, ZernioPostError

OUTPUT_ROOT = os.path.join(os.path.dirname(__file__), "output")

# True sends to the TikTok inbox as a draft (you tap Post yourself).
# False (default) publishes immediately -- safe here since Zernio holds
# the TikTok Business app authorization for this account.
POST_AS_DRAFT = os.environ.get("POST_AS_DRAFT", "false").lower() == "true"
PRIVACY_LEVEL = os.environ.get("TIKTOK_PRIVACY_LEVEL", "PUBLIC_TO_EVERYONE")


def host_images(local_paths):
    """
    TikTok requires public image URLs -- it downloads them rather than
    accepting raw bytes directly through Zernio's post endpoint.

    Default implementation: commit the rendered images into this repo and
    serve them via raw.githubusercontent.com. This works out of the box
    inside the GitHub Actions workflow with zero extra hosting accounts.

    If you'd rather use real cloud storage (S3 / Cloudflare R2 / etc.),
    replace this function's body with an upload call that returns public
    URLs -- everything else in the pipeline is agnostic to how hosting
    works.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError(
            "host_images(): GITHUB_REPOSITORY is not set, so the GitHub-raw "
            "hosting approach can't build URLs. Either run this via the "
            "provided GitHub Actions workflow, or swap in your own cloud "
            "storage upload logic here."
        )

    import subprocess

    subprocess.run(["git", "config", "user.name", "otmadesimple-agent"], check=True)
    subprocess.run(["git", "config", "user.email", "agent@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", "output/", "topic_history.json"], check=True)
    subprocess.run(["git", "commit", "-m", "Add generated slideshow images + topic history", "--allow-empty"], check=True)
    subprocess.run(["git", "push"], check=True)

    sha = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()

    urls = []
    url_to_local_path = {}
    for path in local_paths:
        rel_path = os.path.relpath(path, os.path.dirname(__file__))
        url = f"https://raw.githubusercontent.com/{repo}/{sha}/{rel_path}"
        urls.append(url)
        url_to_local_path[url] = path

    _wait_for_urls_live(url_to_local_path)
    return urls


def _wait_for_urls_live(url_to_local_path, max_wait_seconds=90, poll_interval=3):
    """
    GitHub's raw.githubusercontent.com CDN has multiple edge servers, and
    they don't all update at the same instant after a fresh push. A HEAD
    request returning 200 from one edge doesn't guarantee TikTok's own
    fetch (which may hit a different edge) gets the complete file -- a
    partial/incomplete copy would still return 200 but truncated bytes,
    which is exactly what caused images to appear cut off with black
    space filling the rest.

    This does a full GET (not just HEAD) for each URL and compares the
    downloaded byte size against the actual local file size, retrying
    until they match exactly (or giving up after max_wait_seconds).
    """
    import time

    deadline = time.time() + max_wait_seconds
    pending = dict(url_to_local_path)

    while pending and time.time() < deadline:
        still_pending = {}
        for url, local_path in pending.items():
            expected_size = os.path.getsize(local_path)
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code != 200 or len(resp.content) != expected_size:
                    still_pending[url] = local_path
            except requests.RequestException:
                still_pending[url] = local_path
        pending = still_pending
        if pending:
            time.sleep(poll_interval)

    if pending:
        raise RuntimeError(
            f"Timed out waiting for {len(pending)} image URL(s) to fully "
            f"propagate on raw.githubusercontent.com after {max_wait_seconds}s: "
            f"{list(pending.keys())}"
        )


def run():
    print(f"[{datetime.datetime.now()}] Generating tip content...")
    tip_set = generate_tip_set()
    print(f"Topic: {tip_set['topic']}")

    today = datetime.date.today().isoformat()
    slide_dir = os.path.join(OUTPUT_ROOT, today)

    print("Rendering slides...")
    local_paths = render_slideshow(
        tip_set["slides"],
        slide_dir,
        hook_emoji=tip_set.get("hook_emoji"),
    )
    print(f"Rendered {len(local_paths)} slides to {slide_dir}")

    print("Hosting images for TikTok to pull...")
    image_urls = host_images(local_paths)

    caption = tip_set["caption"] + "\n\n" + " ".join(tip_set["hashtags"])
    title = tip_set["slides"][0]  # the hook slide's own short text -- distinct
                                   # from the caption, so TikTok's bolded
                                   # title and description don't duplicate

    print(f"Posting to TikTok via Zernio (draft={POST_AS_DRAFT}, privacy={PRIVACY_LEVEL})...")

    max_attempts = 3
    retry_delay_seconds = 45
    for attempt in range(1, max_attempts + 1):
        try:
            result = post_photo_slideshow(
                image_urls=image_urls,
                title=title,
                description=caption,
                privacy_level=PRIVACY_LEVEL,
                draft=POST_AS_DRAFT,
            )
            print("Success:", result)
            break
        except ZernioPostError as e:
            is_last_attempt = attempt == max_attempts
            print(f"Post attempt {attempt}/{max_attempts} failed: {e}")
            if is_last_attempt:
                sys.exit(1)
            # Errors like TikTok's "photo_pull_failed" are explicitly
            # labeled temporary network issues by TikTok itself -- worth
            # a short wait and retry rather than failing the whole run
            # on what's likely a one-off blip.
            print(f"Retrying in {retry_delay_seconds}s...")
            time.sleep(retry_delay_seconds)


if __name__ == "__main__":
    run()
