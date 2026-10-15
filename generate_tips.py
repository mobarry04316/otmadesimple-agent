"""
generate_tips.py

Uses the Claude API to generate a complete OT-tip slideshow:
a hook/title slide, several tip slides, and a caption + hashtags
for the TikTok post itself.

Keeping 3 posts a day from feeling samey:
  * FORMAT ROTATION (in code, not left to Claude's mood): every post is
    assigned a content format -- myth vs reality, scenario, checklist,
    relatable student moment, etc. -- cycling in a fixed order, so two
    posts in a row never share a structure.
  * HOOK OPENER: rotated so the hook isn't "OT students: here's how to..."
    every time.
  * RECENT-HISTORY AVOID LISTS: Claude is shown the last topics, hooks and
    caption endings and told not to echo them. Hooks/captions come from
    post_log.json, which is already committed to the repo after every
    successful post (each GitHub Actions run starts from a fresh checkout,
    so anything not committed would be forgotten).
  * PERFORMANCE FEEDBACK: if performance_summary.json exists, the best and
    worst recent posts are included as a weak hint about what lands.

Captions end with a question (comments were 0 across the first 41 posts),
use at most one emoji, and hashtags are de-duplicated in code.

Requires the ANTHROPIC_API_KEY environment variable.
"""

import os
import re
import json
import random
import anthropic

MODEL = "claude-sonnet-4-6"

HERE = os.path.dirname(__file__)
HISTORY_PATH = os.path.join(HERE, "topic_history.json")
POST_LOG_PATH = os.path.join(HERE, "post_log.json")
PERFORMANCE_SUMMARY_PATH = os.path.join(HERE, "performance_summary.json")

HISTORY_LIMIT = 90        # recent topics to remember (~30 days at 3 posts/day)
RECENT_HOOKS_SHOWN = 12   # recent hooks Claude is told not to echo
RECENT_CAPTIONS_SHOWN = 8
RECENT_OPENERS_AVOIDED = 3
MAX_ATTEMPTS = 3          # re-ask Claude if its answer breaks a rule
MAX_HASHTAGS = 8
MAX_CAPTION_EMOJI = 1

# Seed examples/inspiration -- Claude is asked to generate NEW topics in this
# spirit, not limited to this exact list. Kept small on purpose.
SEED_TOPICS = [
    "how to write a skilled documentation note in OT",
    "signs a client is ready to be discharged",
    "grading an activity up or down for OT treatment",
    "common ADL adaptive equipment and when to use it",
    "how to build rapport with a pediatric OT client",
    "clinical reasoning: choosing the right outcome measure",
    "energy conservation techniques for clients with fatigue",
    "sensory processing red flags to watch for",
    "splinting basics every new OT should know",
    "self-care tips for OT students to avoid burnout",
]

# One of these is assigned to every post. `how` tells Claude the structure.
FORMATS = [
    {"name": "myth vs reality",
     "how": "Open on a common myth or misconception about the topic. Slides: the myth, "
            "the reality, why it matters in real practice, what to do instead."},
    {"name": "mistake and fix",
     "how": "A mistake new OT students or new grads commonly make with the topic. Slides: "
            "the mistake, why it backfires, the fix, a short example of the fix in action."},
    {"name": "scenario",
     "how": "Drop the viewer into one realistic moment (a client refuses, a family member "
            "pushes back, a goal isn't working) and ask what they would do. Slides walk "
            "through the reasoning and a good answer."},
    {"name": "this vs that",
     "how": "Compare two related concepts, tools or approaches students mix up. Slides: "
            "what A is, what B is, the key difference, how to decide between them."},
    {"name": "checklist",
     "how": "3-4 specific things to look for or do. Each slide is exactly one item, "
            "concrete enough to use tomorrow."},
    {"name": "wish I knew",
     "how": "Honest peer-to-peer 'things I wish I knew before...' (fieldwork, a setting, "
            "NBCOT, your first caseload). Can be non-clinical: supervisors, time "
            "management, burnout. Warm and a little vulnerable."},
    {"name": "relatable moment",
     "how": "Light, relatable OT-student humor, like 'things OT students say vs what we "
            "actually mean' or a 'POV:' moment from fieldwork or class. Still clearly OT "
            "and still ends with something genuinely useful or reassuring."},
    {"name": "walkthrough",
     "how": "A step-by-step of doing one specific thing, in order. Each slide is one step."},
]

# Hook openers. None = no label prefix; open with a question that names a
# specific OT term or setting instead.
HOOK_OPENERS = ["OT students:", "OT tip:", "Fieldwork tip:", "New grad OT:", None]

SYSTEM_PROMPT = """You write short, punchy educational slideshow scripts for an \
occupational therapy TikTok page (@otmadesimple) aimed at OT students and \
new clinicians. Tone: warm, encouraging, peer-to-peer -- like a fellow \
student sharing a tip, not a textbook. Lowercase, casual phrasing is fine \
and matches the page's existing style.

Each slide's text must be SHORT -- one sentence or a fragment, similar in \
length to:
  "start with what the pt did, not what you did"
  "documentation is a skill and it takes time like everything else"

HOOK (first slide): must make it obvious at a glance this is an OT post \
and promise something specific. Keep it under about 14 words -- long hooks \
force the text to shrink. It must either start with a label like "OT \
students:" or "OT tip:", or name a specific OT term (fieldwork, ADLs, \
clinical reasoning, NBCOT, goals, documentation...). Avoid generic \
self-help phrasing that could belong to any niche. You'll be told which \
opener to use this time and which hooks to avoid echoing.

PLAIN TEXT ONLY: the "slides" strings must contain no emoji anywhere. The \
single hook emoji goes ONLY in the separate "hook_emoji" field.

TOPIC: pick a specific, concrete topic. You'll be given recent topics -- \
don't repeat or closely overlap them. Also notice which practice areas are \
over-represented in that list and choose from an under-represented one: \
pediatrics, mental health, older adults / skilled nursing, hand therapy, \
acute care, school-based practice, home health, low vision, neuro rehab, \
documentation and billing, assessments, adaptive equipment, fieldwork and \
student life, NBCOT prep, burnout and boundaries. Don't begin every topic \
with "how to use" -- the assigned format decides the angle.

CAPTION: 1-2 sentences in the same casual voice. The final sentence must be \
ONE genuine question that invites OT students or clinicians to answer in \
the comments, specific to this post's topic and answerable in a sentence \
(good: "what's the cue you catch yourself overusing?" -- bad: "thoughts?"). \
Use at most one emoji in the whole caption. A "save this" nudge is optional \
and must not be worded like the recent caption endings you'll be shown.

HASHTAGS: 4-8, lowercase, no duplicates, mixing 2 broad (#occupationaltherapy, \
#otstudent) with specific ones for the topic.

Example topic style (inspiration only):
""" + "\n".join(f"- {t}" for t in SEED_TOPICS) + """

Respond with ONLY valid JSON, no markdown fences, in this exact shape:
{
  "topic": "<the specific topic you chose>",
  "hook_emoji": "<single emoji that fits the topic>",
  "slides": ["<hook slide text>", "<slide 2>", "<slide 3>", ...],
  "caption": "<caption ending in a question>",
  "hashtags": ["#tag1", "#tag2", ...]
}

Generate between 4 and 6 slides total including the hook -- a follow/CTA \
slide with the account handle is appended automatically afterward, so do \
NOT write one yourself."""


# ---------------------------------------------------------------------------
# History / log helpers
# ---------------------------------------------------------------------------

def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _load_history():
    history = _load_json(HISTORY_PATH, [])
    return history if isinstance(history, list) else []


def _save_history(history):
    with open(HISTORY_PATH, "w") as f:
        json.dump(history[-HISTORY_LIMIT:], f, indent=2)


def _load_post_log():
    log = _load_json(POST_LOG_PATH, [])
    return log if isinstance(log, list) else []


def _load_performance_summary():
    summary = _load_json(PERFORMANCE_SUMMARY_PATH, None)
    return summary if isinstance(summary, dict) else None


def _caption_ending(caption):
    """Last sentence of the caption body (ignoring the hashtag block)."""
    body = (caption or "").split("\n\n")[0].strip()
    if not body:
        return ""
    return re.split(r"(?<=[.!?])\s+", body)[-1]


def _pick_format(post_count):
    # Stride 3 is coprime with 8 formats, so consecutive posts always differ
    # and the order doesn't look like a simple loop.
    return FORMATS[(post_count * 3) % len(FORMATS)]


def _pick_opener(recent_hooks):
    """Random opener, skipping any used by the last few hooks."""
    recent = [h.lower() for h in recent_hooks[-RECENT_OPENERS_AVOIDED:]]
    candidates = [
        o for o in HOOK_OPENERS
        if o is None or not any(h.startswith(o.lower()) for h in recent)
    ]
    return random.choice(candidates or HOOK_OPENERS)


# ---------------------------------------------------------------------------
# Output validation / cleanup
# ---------------------------------------------------------------------------

_EMOJI_BASE = (
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002300-\U000023FF]"
)
# One emoji = a base symbol plus any variation selectors / ZWJ-joined parts,
# so "👩‍⚕️" counts once and "🧠✨" counts twice.
_EMOJI_PATTERN = re.compile(
    _EMOJI_BASE + "[\U0000FE0F\U0001F3FB-\U0001F3FF]*"
    "(?:\U0000200D" + _EMOJI_BASE + "[\U0000FE0F\U0001F3FB-\U0001F3FF]*)*"
)

_OT_SIGNAL = re.compile(
    r"\bOT\b|\bOTA\b|\bOTD\b|\bOTR\b|occupational|fieldwork|\bADLs?\b|NBCOT|clinical reasoning",
    flags=re.IGNORECASE,
)


def _limit_emoji(text, max_count):
    """Keep the first `max_count` emoji in `text`, drop the rest."""
    seen = 0

    def _sub(match):
        nonlocal seen
        seen += 1
        return match.group(0) if seen <= max_count else ""

    out = _EMOJI_PATTERN.sub(_sub, text)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def _clean_hashtags(tags):
    cleaned, seen = [], set()
    for tag in tags:
        tag = re.sub(r"\s+", "", str(tag)).lower()
        tag = "#" + tag.lstrip("#")
        if len(tag) > 1 and tag not in seen:
            seen.add(tag)
            cleaned.append(tag)
    return cleaned[:MAX_HASHTAGS]


def _extract_json(raw):
    """Pull the JSON object out of the reply even if wrapped in fences/prose."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in reply")
    return json.loads(raw[start:end + 1])


def _problems(result):
    """Rule violations worth asking Claude to fix (empty list = good)."""
    problems = []
    if not isinstance(result, dict):
        return ["reply was not a JSON object"]
    for key in ("topic", "hook_emoji", "slides", "caption", "hashtags"):
        if key not in result:
            problems.append(f'missing the "{key}" field')
    if problems:
        return problems

    slides = result["slides"]
    if not (isinstance(slides, list) and 4 <= len(slides) <= 6
            and all(isinstance(s, str) and s.strip() for s in slides)):
        problems.append('"slides" must be 4-6 non-empty strings')
    elif not _OT_SIGNAL.search(slides[0]):
        problems.append("the hook slide doesn't clearly signal OT -- name OT or a specific OT term")

    if "?" not in str(result["caption"]):
        problems.append("the caption must end with a question")
    if not isinstance(result["hashtags"], list) or not result["hashtags"]:
        problems.append('"hashtags" must be a non-empty list')
    return problems


def _fatal(result):
    """Problems we can't post through (vs. soft ones we can accept)."""
    if not isinstance(result, dict):
        return True
    if not all(k in result for k in ("topic", "hook_emoji", "slides", "caption", "hashtags")):
        return True
    slides = result["slides"]
    return not (isinstance(slides, list) and len(slides) >= 2
                and all(isinstance(s, str) and s.strip() for s in slides)
                and isinstance(result["hashtags"], list))


def _clean(result, fmt):
    result["slides"] = [s.strip() for s in result["slides"]]
    result["caption"] = _limit_emoji(str(result["caption"]).strip(), MAX_CAPTION_EMOJI)
    result["hashtags"] = _clean_hashtags(result["hashtags"])
    result["hook_emoji"] = str(result["hook_emoji"]).strip()
    result["format"] = fmt["name"]
    return result


# ---------------------------------------------------------------------------
# Prompt assembly + generation
# ---------------------------------------------------------------------------

def _build_user_content(history, post_log, performance, fmt, opener):
    parts = []

    parts.append(
        f"FORMAT for this post: {fmt['name']}\n{fmt['how']}"
    )

    if opener:
        parts.append(f'HOOK OPENER for this post: start the hook with "{opener}"')
    else:
        parts.append(
            "HOOK OPENER for this post: no label prefix. Open the hook with a question "
            "that names a specific OT term or setting."
        )

    parts.append(
        "Recently used topics (don't repeat or overlap these):\n"
        + ("\n".join(f"- {t}" for t in history) if history else "(none yet)")
    )

    recent_hooks = [e["hook"] for e in post_log[-RECENT_HOOKS_SHOWN:] if e.get("hook")]
    if recent_hooks:
        parts.append(
            "Recent hooks (don't reuse their opening words or sentence pattern -- in "
            "particular don't lean on \"here's how to...\" again):\n"
            + "\n".join(f"- {h}" for h in recent_hooks)
        )

    endings = [
        _caption_ending(e.get("caption"))
        for e in post_log[-RECENT_CAPTIONS_SHOWN:]
    ]
    endings = [x for x in endings if x]
    if endings:
        parts.append(
            "Recent caption endings (word yours differently):\n"
            + "\n".join(f"- {x}" for x in endings)
        )

    if performance and performance.get("top_performers"):
        lines = [
            "Real performance data from past posts. The sample is small, so treat this as a "
            "weak hint about which angles resonate with this audience, not a rule -- and "
            "don't copy these topics (they're already in the avoid list).",
            "",
            "Best performers:",
        ]
        for p in performance["top_performers"]:
            stats = f" -- {p['stats']}" if p.get("stats") else ""
            lines.append(f"- \"{p['hook']}\" (topic: {p['topic']}){stats}")
        if performance.get("underperformers"):
            lines += ["", "Weakest performers:"]
            for p in performance["underperformers"]:
                stats = f" -- {p['stats']}" if p.get("stats") else ""
                lines.append(f"- \"{p['hook']}\" (topic: {p['topic']}){stats}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def generate_tip_set(client=None):
    """
    Generate one slideshow's worth of content, with a rotating format and
    hook opener, steered away from recent topics/hooks/caption endings and
    informed by past performance. Re-asks Claude (up to MAX_ATTEMPTS) if the
    reply breaks a rule; accepts a soft miss on the last attempt rather than
    failing the whole run.
    """
    client = client or anthropic.Anthropic()
    history = _load_history()
    post_log = _load_post_log()
    performance = _load_performance_summary()

    post_count = len(post_log) if post_log else len(history)
    fmt = _pick_format(post_count)
    opener = _pick_opener([e.get("hook", "") for e in post_log])

    user_content = _build_user_content(history, post_log, performance, fmt, opener)

    result = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        message = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = message.content[0].text.strip()

        try:
            result = _extract_json(raw)
            problems = _problems(result)
        except (ValueError, json.JSONDecodeError) as e:
            result, problems = None, [f"reply wasn't valid JSON ({e})"]

        if not problems:
            break

        print(f"Attempt {attempt}/{MAX_ATTEMPTS}: {'; '.join(problems)}")
        if attempt < MAX_ATTEMPTS:
            user_content += (
                "\n\nYour previous reply had these problems -- fix them and reply "
                "again with the full JSON:\n" + "\n".join(f"- {p}" for p in problems)
            )

    if result is None or _fatal(result):
        raise RuntimeError(f"Claude never returned usable content after {MAX_ATTEMPTS} attempts")

    result = _clean(result, fmt)

    history.append(result["topic"])
    _save_history(history)

    return result


if __name__ == "__main__":
    result = generate_tip_set()
    print(json.dumps(result, indent=2))
