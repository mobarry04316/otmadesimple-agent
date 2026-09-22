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
