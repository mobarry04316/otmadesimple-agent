"""
render_slides.py

Takes a list of slide texts and renders each onto the @otmadesimple
floral template, matching the centered handwritten-caption style.

Usage (standalone test):
    python render_slides.py
"""

import os
import textwrap
import urllib.request
from PIL import Image, ImageDraw, ImageFont

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "clean_template.png")
FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "Caveat-Bold.ttf")
EMOJI_CACHE_DIR = os.path.join(os.path.dirname(__file__), "assets", "emoji")
TWEMOJI_BASE = "https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/"

CANVAS_SIZE = (1080, 1920)
SUPERSAMPLE = 3  # render at 3x then downscale for clean anti-aliasing (prevents
                  # "ringing"/speckle artifacts when thumbnails or previews
                  # later downscale the image again)
TEXT_COLOR = (35, 28, 22)          # matches the dark brown/black ink in the original
TEXT_ZONE_TOP = 420                 # safe vertical band that avoids the floral border
TEXT_ZONE_BOTTOM = 1500
MAX_TEXT_WIDTH = 860                # horizontal margin so text never runs into the flowers
MAX_FONT_SIZE = 105   # slightly bigger than before (was 92), in final-resolution units
MIN_FONT_SIZE = 54
LINE_SPACING = 1.35


def _emoji_to_codepoint(emoji_char, keep_variation_selector=False):
    """Convert an emoji character to its twemoji filename codepoint(s)."""
    if keep_variation_selector:
        return "-".join(f"{ord(c):x}" for c in emoji_char)
    return "-".join(f"{ord(c):x}" for c in emoji_char if ord(c) != 0xFE0F)


def get_emoji_image(emoji_char, size):
    """
    Return a PIL RGBA image for the given emoji, fetching it from the
    Twemoji asset set (cached locally) since handwriting fonts don't
    include color emoji glyphs.

    Some emoji (skin tones, ZWJ sequences) only exist under the variant
    of the codepoint that includes the variation selector (FE0F), others
    only exist without it -- Twemoji isn't fully consistent. This tries
    both before giving up, and raises EmojiNotFoundError if neither
    works, so the caller can skip the emoji instead of embedding a
    broken image.
    """
    os.makedirs(EMOJI_CACHE_DIR, exist_ok=True)

    candidates = [
        _emoji_to_codepoint(emoji_char, keep_variation_selector=False),
        _emoji_to_codepoint(emoji_char, keep_variation_selector=True),
    ]

    for codepoint in candidates:
        cache_path = os.path.join(EMOJI_CACHE_DIR, f"{codepoint}.png")

        if os.path.exists(cache_path):
            try:
                img = Image.open(cache_path).convert("RGBA")
                return img.resize((size, size), Image.LANCZOS)
            except Exception:
                os.remove(cache_path)  # cached file was bad, try re-fetching

        url = f"{TWEMOJI_BASE}{codepoint}.png"
        try:
            tmp_path = cache_path + ".tmp"
            urllib.request.urlretrieve(url, tmp_path)
            # Validate it's actually a real image before trusting it
            img = Image.open(tmp_path).convert("RGBA")
            os.replace(tmp_path, cache_path)
            return img.resize((size, size), Image.LANCZOS)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            continue  # try the next candidate codepoint

    raise EmojiNotFoundError(f"No Twemoji asset found for {emoji_char!r} (tried {candidates})")


class EmojiNotFoundError(Exception):
    pass


def _wrap_and_fit(draw, text, font_path, max_width, max_height, scale=1):
    """
    Find the largest font size (within MIN/MAX, scaled by `scale` for
    supersampled rendering) whose word-wrapped rendering of `text` fits
    inside (max_width, max_height).
    Returns (font, wrapped_lines, line_height).
    """
    max_size = MAX_FONT_SIZE * scale
    min_size = MIN_FONT_SIZE * scale

    for size in range(max_size, min_size - 1, -2 * scale):
        font = ImageFont.truetype(font_path, size)

        # Estimate a reasonable wrap width in characters for this font size,
        # then let PIL confirm actual pixel widths.
        avg_char_w = draw.textlength("abcdefghijklmnopqrstuvwxyz ", font=font) / 27
        wrap_chars = max(8, int(max_width / avg_char_w))

        wrapped = textwrap.fill(text, width=wrap_chars)
        lines = wrapped.split("\n")

        # Verify no line exceeds max_width; if so, re-wrap narrower.
        while any(draw.textlength(line, font=font) > max_width for line in lines) and wrap_chars > 4:
            wrap_chars -= 1
            wrapped = textwrap.fill(text, width=wrap_chars)
            lines = wrapped.split("\n")

        line_height = font.getbbox("Ag")[3] * LINE_SPACING
        total_height = line_height * len(lines)

        if total_height <= max_height:
            return font, lines, line_height

    # Fallback: smallest size, whatever it takes
    font = ImageFont.truetype(font_path, min_size)
    wrapped = textwrap.fill(text, width=20)
    lines = wrapped.split("\n")
    line_height = font.getbbox("Ag")[3] * LINE_SPACING
    return font, lines, line_height


def render_slide(text, output_path, emoji=None):
    """
    Render a single slide: template background + centered wrapped text.
    `emoji` (optional) is appended after the last line, matching the
    hook-slide style seen in slide 1 of the reference set.
    """
    img = Image.open(TEMPLATE_PATH).convert("RGB")
    # Supersample: work on a 2x canvas so text edges anti-alias cleanly,
    # then downscale at the end. This is what actually prevents speckle/
    # ringing artifacts when TikTok, a phone gallery, or any other viewer
    # generates a thumbnail or scales the image down further.
    render_size = (CANVAS_SIZE[0] * SUPERSAMPLE, CANVAS_SIZE[1] * SUPERSAMPLE)
    img = img.resize(render_size, Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    s = SUPERSAMPLE
    text_zone_top = TEXT_ZONE_TOP * s
    text_zone_bottom = TEXT_ZONE_BOTTOM * s
    max_text_width = MAX_TEXT_WIDTH * s

    # Reserve a little extra width on the last line if an emoji will be appended
    effective_max_width = max_text_width - 90 * s if emoji else max_text_width
    max_h = text_zone_bottom - text_zone_top
    font, lines, line_height = _wrap_and_fit(draw, text, FONT_PATH, effective_max_width, max_h, scale=s)

    # Pre-fetch the emoji (if any) up front, so layout math and rendering
    # both see a consistent answer -- if it can't be found, fall back to
    # no emoji cleanly instead of leaving a gap or a broken image.
    emoji_img = None
    if emoji:
        try:
            emoji_img = get_emoji_image(emoji, size=int(line_height * 0.7))
        except EmojiNotFoundError as e:
            print(f"WARNING: {e} -- rendering this slide without the emoji.")

    total_height = line_height * len(lines)
    start_y = text_zone_top + (max_h - total_height) / 2

    emoji_size = int(line_height * 0.7)
    y = start_y
    for i, line in enumerate(lines):
        is_last = i == len(lines) - 1
        text_w = draw.textlength(line, font=font)
        gap = 18 * s
        has_emoji = is_last and emoji_img is not None
        total_w = text_w + (gap + emoji_size if has_emoji else 0)
        x = (render_size[0] - total_w) / 2

        draw.text((x, y), line, font=font, fill=TEXT_COLOR)

        if has_emoji:
            emoji_x = int(x + text_w + gap)
            emoji_y = int(y + (line_height - emoji_size) / 2)
            img.paste(emoji_img, (emoji_x, emoji_y), emoji_img)

        y += line_height

    # Downscale back to final TikTok resolution with high-quality resampling
    img = img.resize(CANVAS_SIZE, Image.LANCZOS)
    img.save(output_path)
    return output_path


def render_slideshow(slide_texts, output_dir, hook_emoji=None, add_cta=True,
                      cta_text="follow @otmadesimple for more OT tips", cta_emoji="💌"):
    """
    Render a full slideshow. `slide_texts` is an ordered list of strings;
    the first slide is treated as the hook/title and gets `hook_emoji`
    appended if provided.

    If `add_cta` is True (default), a final slide with `cta_text` is
    automatically appended -- callers/AI-generated content don't need to
    remember to include the account handle themselves.
    """
    os.makedirs(output_dir, exist_ok=True)
    all_slides = list(slide_texts)
    if add_cta:
        all_slides.append(cta_text)

    paths = []
    for i, text in enumerate(all_slides, start=1):
        if i == 1:
            emoji = hook_emoji
        elif add_cta and i == len(all_slides):
            emoji = cta_emoji
        else:
            emoji = None
        path = os.path.join(output_dir, f"{i}.png")
        render_slide(text, path, emoji=emoji)
        paths.append(path)
    return paths


if __name__ == "__main__":
    # Quick standalone test matching the reference example
    test_slides = [
        "how to write a skilled documentation note in OT",
        "start with what the pt did, not what you did",
        "documentation is a skill and it takes time like everything else",
    ]
    out = render_slideshow(test_slides, os.path.join(os.path.dirname(__file__), "output", "test"), hook_emoji="🌿")
    print("Rendered:", out)
