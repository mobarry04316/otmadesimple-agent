"""
zernio_post.py

Posts the finished slideshow to TikTok through Zernio, which already holds
TikTok's business-app authorization -- so posts go public directly, no
personal developer-app audit or SELF_ONLY restriction.

Explicitly configured for NO auto-added music (auto_add_music: false).
TikTok's API gives no third-party tool access to its general sound
library, so a specific existing sound (a motivational speech clip, a
nature/white-noise track, etc.) can't be attached programmatically --
that part stays a manual step in the TikTok app, same as it would with
any automation tool. This posts silent; add the sound by hand afterward
if you want one attached.

Requires environment variables:
  ZERNIO_API_KEY          -- from your Zernio dashboard
  ZERNIO_TIKTOK_ACCOUNT_ID -- the accountId for @otmadesimple, from
                              connecting it in the Zernio dashboard
"""

import os
import requests

API_BASE = "https://zernio.com/api/v1"


class ZernioPostError(Exception):
    pass


def _headers():
    key = os.environ.get("ZERNIO_API_KEY")
    if not key:
        raise ZernioPostError("ZERNIO_API_KEY environment variable is not set.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _account_id():
    account_id = os.environ.get("ZERNIO_TIKTOK_ACCOUNT_ID")
    if not account_id:
        raise ZernioPostError("ZERNIO_TIKTOK_ACCOUNT_ID environment variable is not set.")
    return account_id


def get_creator_info():
    """
    Fetch the connected account's allowed privacy levels and posting
    limits. Worth checking once after connecting so you know which
    privacy_level values are actually valid for this account.
    """
    account_id = _account_id()
    resp = requests.get(
        f"{API_BASE}/accounts/{account_id}/tiktok/creator-info",
        headers=_headers(),
        params={"mediaType": "photo"},
    )
    data = resp.json()
    if resp.status_code != 200:
        raise ZernioPostError(f"Failed to fetch creator info: {data}")
    return data


def post_photo_slideshow(image_urls, caption, privacy_level="PUBLIC_TO_EVERYONE",
                          draft=False, allow_comment=True, dry_run=False):
    """
    Publish (or draft) a photo carousel to TikTok via Zernio.

    image_urls   : ordered list of public image URLs (max 35)
    caption      : full caption text -- goes in `description` (photo posts
                   put the long caption there, not `content`)
    privacy_level: must be one of the values get_creator_info() returns for
                   this account -- PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS,
                   FOLLOWER_OF_CREATOR, or SELF_ONLY
    draft        : True sends it to the TikTok inbox instead of posting
                   directly (you still tap Post in-app). False (default)
                   publishes immediately -- safe to do since this account
                   is connected through Zernio's TikTok Business app lane.
    dry_run      : validates without actually posting or using a post slot
    """
    if not (1 <= len(image_urls) <= 35):
        raise ZernioPostError("TikTok photo carousels must have between 1 and 35 images.")

    body = {
        "content": caption[:90],          # becomes the photo "title", hashtags stripped
        "mediaItems": [{"type": "image", "url": url} for url in image_urls],
        "platforms": [{"platform": "tiktok", "accountId": _account_id()}],
        "tiktokSettings": {
            "privacy_level": privacy_level,
            "allow_comment": allow_comment,
            "media_type": "photo",
            "photo_cover_index": 0,
            "description": caption[:4000],  # the actual full caption lives here
            "auto_add_music": False,        # explicitly no music, ever
            "content_preview_confirmed": True,
            "express_consent_given": True,
            "draft": draft,
        },
        "publishNow": not draft,
        "dryRun": dry_run,
    }

    resp = requests.post(f"{API_BASE}/posts", headers=_headers(), json=body)
    data = resp.json()

    # 207 is a "partial success" status Zernio uses when the post record
    # was created but the platform publish itself failed -- treat it as
    # an error for our purposes.
    if resp.status_code not in (200, 201) or data.get("post", {}).get("status") == "failed":
        raise ZernioPostError(f"Zernio/TikTok post failed: {data}")

    return data
