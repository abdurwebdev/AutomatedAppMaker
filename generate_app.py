#!/usr/bin/env python3
"""Daily app generator: asks Claude for a new idea, builds it, then writes a
retrospective that is fed back into tomorrow's prompt (a "memory" loop)."""

import datetime
import html as html_lib
import json
import re
import sys
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-5"
ROOT = Path(__file__).parent
APPS_DIR = ROOT / "apps"
INDEX_FILE = APPS_DIR / "index.json"
LESSONS_FILE = ROOT / "lessons.md"

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def ask(prompt: str, max_tokens: int = 8000) -> str:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def load_index() -> list:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text())
    return []


def load_lessons() -> str:
    return LESSONS_FILE.read_text() if LESSONS_FILE.exists() else "(none yet)"


def pick_idea(index: list, lessons: str) -> dict:
    past = "\n".join(f"- {a['title']}: {a['description']}" for a in index[-50:]) or "(none yet)"
    prompt = f"""Come up with ONE small, useful or fun app idea that can be built as a
single self-contained HTML file (HTML + CSS + vanilla JS, no external libraries or network calls).

Apps already built (do NOT repeat or closely resemble these):
{past}

Lessons learned from earlier builds:
{lessons}

Reply with ONLY a JSON object, no markdown fences:
{{"title": "...", "slug": "lowercase-with-dashes", "description": "one sentence"}}"""
    text = ask(prompt, max_tokens=500)
    match = re.search(r"\{.*\}", text, re.S)
    idea = json.loads(match.group(0))
    idea["slug"] = re.sub(r"[^a-z0-9-]", "", idea["slug"].lower())[:50] or "app"
    return idea


def build_app(idea: dict, lessons: str, feedback: str = "") -> str:
    prompt = f"""Build this app as ONE complete, self-contained HTML file.

Title: {idea['title']}
Description: {idea['description']}

Requirements:
- Vanilla HTML/CSS/JS only. No external scripts, fonts, images, or network requests.
- Must work on desktop and mobile, with a clean, polished design.
- Do not use localStorage-dependent logic without try/catch.
- Handle edge cases and invalid input gracefully.

Lessons from earlier builds (apply them):
{lessons}

{feedback}
Reply with ONLY the HTML, starting with <!DOCTYPE html>. No explanation, no markdown fences."""
    html = ask(prompt, max_tokens=12000).strip()
    html = re.sub(r"^```(?:html)?\s*|\s*```$", "", html)
    return html


def check_app(html: str) -> str:
    """Return an error message if the app looks broken, else an empty string."""
    low = html.lower()
    if not low.startswith("<!doctype html"):
        return "Output did not start with <!DOCTYPE html>."
    if "</html>" not in low:
        return "HTML appears truncated (no closing </html>)."
    if re.search(r'<script[^>]+src=["\']https?://', low):
        return "Uses an external script; must be fully self-contained."
    if "<script" not in low:
        return "No JavaScript found; app should be interactive."
    return ""


def write_retrospective(idea: dict, attempts: int, problems: list) -> str:
    prompt = f"""You just built an app called "{idea['title']}" ({idea['description']}).
It took {attempts} attempt(s). Problems detected by automated checks: {problems or 'none'}.

Write 2-3 short bullet points of concrete, reusable lessons for building better
single-file HTML apps next time. Bullets only, no preamble."""
    return ask(prompt, max_tokens=400).strip()


def build_gallery(index: list) -> None:
    """Regenerate the root index.html listing every app, newest first."""
    cards = []
    for a in reversed(index):
        cards.append(
            f'<a class="card" href="{html_lib.escape(a["path"])}/index.html">'
            f'<span class="date">{html_lib.escape(a["date"])}</span>'
            f'<h2>{html_lib.escape(a["title"])}</h2>'
            f'<p>{html_lib.escape(a["description"])}</p></a>'
        )
    body = "\n".join(cards) or "<p>No apps yet.</p>"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Apps</title>
<style>
  :root {{ --bg:#f7f7f5; --fg:#1c1c1a; --card:#fff; --muted:#6b6b66; --line:#e2e2dc; --accent:#3b6cf6; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141413; --fg:#eeeeea; --card:#1e1e1c; --muted:#9a9a93; --line:#2e2e2b; --accent:#7c9cff; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:2rem 1rem; background:var(--bg); color:var(--fg);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 960px; margin: 0 auto; }}
  h1 {{ margin: 0 0 .25rem; }}
  .sub {{ color: var(--muted); margin: 0 0 2rem; }}
  .grid {{ display:grid; gap:1rem; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }}
  .card {{ display:block; padding:1.1rem; background:var(--card); border:1px solid var(--line);
          border-radius:12px; text-decoration:none; color:inherit; transition: transform .15s, border-color .15s; }}
  .card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
  .card h2 {{ font-size:1.05rem; margin:.4rem 0; }}
  .card p {{ margin:0; color:var(--muted); font-size:.92rem; line-height:1.4; }}
  .date {{ font-size:.78rem; color:var(--accent); font-weight:600; }}
</style>
</head>
<body>
<main>
  <h1>Daily Apps</h1>
  <p class="sub">{len(index)} app(s), one new one every day.</p>
  <div class="grid">
{body}
  </div>
</main>
</body>
</html>
"""
    (ROOT / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    APPS_DIR.mkdir(exist_ok=True)
    index = load_index()
    lessons = load_lessons()

    idea = pick_idea(index, lessons)
    print(f"Idea: {idea['title']} - {idea['description']}")

    problems, html, feedback = [], "", ""
    for attempt in range(1, 4):
        html = build_app(idea, lessons, feedback)
        error = check_app(html)
        if not error:
            break
        problems.append(error)
        feedback = f"A previous attempt failed this check: {error} Fix it."
        print(f"Attempt {attempt} failed: {error}")
    else:
        print("All attempts failed; nothing saved.")
        return 1

    today = datetime.date.today().isoformat()
    folder = APPS_DIR / f"{today}-{idea['slug']}"
    folder.mkdir(exist_ok=True)
    (folder / "index.html").write_text(html, encoding="utf-8")

    index.append({**idea, "date": today, "path": str(folder.relative_to(ROOT))})
    INDEX_FILE.write_text(json.dumps(index, indent=2))
    build_gallery(index)

    notes = write_retrospective(idea, len(problems) + 1, problems)
    with LESSONS_FILE.open("a", encoding="utf-8") as f:
        f.write(f"\n## {today} - {idea['title']}\n{notes}\n")

    print(f"Saved to {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
