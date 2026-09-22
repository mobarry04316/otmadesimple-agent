# @otmadesimple TikTok slideshow agent

Fully automatic pipeline: Claude writes an OT tip topic + slide text + caption,
the slides get rendered onto your floral template, and the finished
slideshow is **posted directly and publicly** to TikTok, 3x/day, via GitHub
Actions -- no manual "tap Post" step needed, and no music ever attached.

## What's in here

| File | Purpose |
|---|---|
| `render_slides.py` | Draws tip text onto `templates/clean_template.png` -- Caveat Bold font, real emoji via Twemoji, supersampled rendering for clean edges at any display size |
| `generate_tips.py` | Calls Claude to invent a fresh topic + slide text + caption each run, tracked in `topic_history.json` to avoid near-term repeats |
| `zernio_post.py` | Posts the finished carousel to TikTok through Zernio (no music, direct public post) |
| `main.py` | Runs the whole pipeline end to end |
| `.github/workflows/post_slideshow.yml` | Runs `main.py` 3x/day automatically |

## Why Zernio instead of TikTok's own developer API

TikTok's raw developer API forces posts to private (`SELF_ONLY`) until your
own app passes TikTok's content audit -- a multi-week process with a demo
video, Terms of Service page, and review queue. Zernio already holds that
audit as a business, so connecting your account through them gives you
**direct public posting from day one**, through a normal one-click OAuth
login -- no developer portal, no sandbox, no audit wait.

## One-time setup (~10 minutes)

### 1. Push this folder to a private GitHub repo
(Same as before, if you haven't already.)

### 2. Sign up at zernio.com and connect @otmadesimple
1. Create a Zernio account and grab your API key from the dashboard.
2. Connect your TikTok account: call `GET /v1/connect/tiktok` with your
   profile ID (see [Zernio's connecting-accounts guide](https://docs.zernio.com/guides/connecting-accounts))
   to get a login URL, open it, and log into @otmadesimple to authorize it.
   This goes through TikTok's own consent screen -- that one click is still
   required by TikTok for any integration, no way around it.
3. Note the `accountId` Zernio gives you back for the connected account.

### 3. Add GitHub Actions secrets
In your repo: **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Claude API key from console.anthropic.com |
| `ZERNIO_API_KEY` | From your Zernio dashboard |
| `ZERNIO_TIKTOK_ACCOUNT_ID` | The `accountId` from step 2 |

### 4. Check your allowed privacy levels (optional but worth doing once)
Run this locally to confirm `PUBLIC_TO_EVERYONE` is available for your
account (it should be, on Zernio's Business app connection):
```bash
python -c "from zernio_post import get_creator_info; print(get_creator_info())"
```

### 5. Test it
Go to the **Actions** tab → "Post OT slideshow to TikTok" → **Run workflow**
to trigger it manually and confirm a post actually lands on @otmadesimple
before trusting the schedule.

## No music, ever

`auto_add_music` is hardcoded to `false` in `zernio_post.py`. TikTok's API
doesn't expose its general sound library to any third-party tool (Zernio's
own docs confirm this), so a specific sound -- your inspirational-speech or
nature/white-noise clips -- can't be attached automatically by anything,
Zernio included. Posts go up silent; add a sound by hand afterward in the
TikTok app if you want one on a specific post.

## Customizing

- **Posting schedule/time**: edit the `cron` lines in
  `.github/workflows/post_slideshow.yml`.
- **Draft mode instead of direct**: set the `POST_AS_DRAFT` repo variable
  to `true` if you ever want to go back to reviewing before posting.
- **Topics**: Claude invents fresh ones each run; `SEED_TOPICS` in
  `generate_tips.py` is style inspiration, not a fixed list.
- **Caption style**: edit `SYSTEM_PROMPT` in `generate_tips.py`.
- **Design**: `templates/clean_template.png` is the background with all
  original text removed. Swap in a different background anytime.
- **Font**: `fonts/Caveat-Bold.ttf`. Swap in a different `.ttf` if desired.

## Local testing

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python generate_tips.py        # preview generated tip content
python render_slides.py        # preview rendered slide images in output/test/
```
