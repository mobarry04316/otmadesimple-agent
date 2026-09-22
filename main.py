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
    for path in local_paths:
        rel_path = os.path.relpath(path, os.path.dirname(__file__))
        urls.append(f"https://raw.githubusercontent.com/{repo}/{sha}/{rel_path}")

    _wait_for_urls_live(urls)
    return urls


def _wait_for_urls_live(urls, max_wait_seconds=60, poll_interval=3):
    """
    GitHub's raw.githubusercontent.com CDN can take a few seconds to
    catch up after a fresh push. Rather than guess a fixed sleep, poll
    each URL until it actually returns 200 (or give up after
    max_wait_seconds and raise, so the failure is obvious instead of
    silently handing TikTok a URL that 404s).
    """
    import time

    deadline = time.time() + max_wait_seconds
    pending = list(urls)

    while pending and time.time() < deadline:
        still_pending = []
        for url in pending:
            try:
                resp = requests.head(url, timeout=10, allow_redirects=True)
                if resp.status_code != 200:
                    still_pending.append(url)
            except requests.RequestException:
                still_pending.append(url)
        pending = still_pending
        if pending:
            time.sleep(poll_interval)

    if pending:
        raise RuntimeError(
            f"Timed out waiting for {len(pending)} image URL(s) to become "
            f"live on raw.githubusercontent.com after {max_wait_seconds}s: "
            f"{pending}"
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

    print(f"Posting to TikTok via Zernio (draft={POST_AS_DRAFT}, privacy={PRIVACY_LEVEL})...")
    try:
        result = post_photo_slideshow(
            image_urls=image_urls,
            caption=caption,
            privacy_level=PRIVACY_LEVEL,
            draft=POST_AS_DRAFT,
        )
        print("Success:", result)
    except ZernioPostError as e:
        print("Post failed:", e)
        sys.exit(1)


if __name__ == "__main__":
    run()
