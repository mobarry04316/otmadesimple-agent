"""
generate_tips.py

Uses the Claude API to generate a complete OT-tip slideshow:
a hook/title slide, several tip slides, and a caption + hashtags
for the TikTok post itself.

Topic variety: rather than cycling a small fixed list (which would repeat
within days at 3 posts/day), Claude is asked to invent a fresh, specific
topic each run, informed by a rolling history of recently-used topics so
it avoids near-term repeats. The seed list below is just inspiration/
fallback, not the full universe of topics.

Requires the ANTHROPIC_API_KEY environment variable.
"""

import os
import json
import random
import anthropic

MODEL = "claude-sonnet-4-6"

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "topic_history.json")
HISTORY_LIMIT = 40  # how many recent topics to remember and avoid repeating

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

SYSTEM_PROMPT = """You write short, punchy educational slideshow scripts for an \
occupational therapy TikTok page (@otmadesimple) aimed at OT students and \
new clinicians. Tone: warm, encouraging, peer-to-peer -- like a fellow \
student sharing a tip, not a textbook. Lowercase, casual phrasing is fine \
and matches the page's existing style.

Each slide's text must be SHORT -- think one sentence or a fragment, \
similar in length to:
  "start with what the pt did, not what you did"
  "documentation is a skill and it takes time like everything else"

You will be given a list of topics used recently. Pick a DIFFERENT, \
specific topic relevant to OT students/new clinicians -- it can be inspired \
by the example style below but must not repeat or closely overlap any \
recently-used topic. Prefer specific, concrete angles over broad ones \
(e.g. "grading a dressing task for a stroke patient" rather than just \
"grading activities" again if that's been covered).

Example topic style (for inspiration only, not an exhaustive list):
""" + "\n".join(f"- {t}" for t in SEED_TOPICS) + """

Respond with ONLY valid JSON, no markdown fences, in this exact shape:
{
  "topic": "<the specific topic you chose>",
  "hook_emoji": "<single emoji that fits the topic>",
  "slides": ["<hook/title slide text>", "<tip 1>", "<tip 2>", ...],
  "caption": "<engaging TikTok caption, 1-2 sentences>",
  "hashtags": ["#tag1", "#tag2", ...]
}

Generate between 4 and 6 slides total (including the hook slide) -- a \
follow/CTA slide with the account handle is appended automatically \
afterward, so do NOT write one yourself. Include 4-8 relevant hashtags \
mixing broad (#occupationaltherapy, #otstudent) and specific ones related \
to the topic."""


def _load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(history):
    with open(HISTORY_PATH, "w") as f:
        json.dump(history[-HISTORY_LIMIT:], f, indent=2)


def generate_tip_set(client=None):
    """
    Generate one slideshow's worth of content. Claude picks a fresh topic
    itself, steered away from whatever's in the recent-history file.
    """
    client = client or anthropic.Anthropic()
    history = _load_history()

    user_content = "Recently used topics (avoid repeating/overlapping these):\n"
    user_content += "\n".join(f"- {t}" for t in history) if history else "(none yet)"

    message = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw)

    history.append(result["topic"])
    _save_history(history)

    return result


if __name__ == "__main__":
    result = generate_tip_set()
    print(json.dumps(result, indent=2))
