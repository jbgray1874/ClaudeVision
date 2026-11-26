"""Ask the user guide - the chat box on the Live Orders and Estimate → X3 user guides. Written 25 Nov 2026.

James (25 Nov): "let's make it interactive like a chat bot where we can ask questions of the user guide and it responds
with a sensible response."

The page sends the question (and the last few questions and answers, for follow-ups); the answer comes from Claude, given
only that page's user guide (and, for Live Orders, its How it works rules). Nothing from Sage X3 or the workbooks is sent.
Without ANTHROPIC_API_KEY in the portal's .env, or the anthropic package, or if Claude can't be reached, it says so and
the page shows the guide sections that best match the question instead - the box always gives an answer.

Used by live_orders_routes.py (POST /api/live-orders/ask) and estimating_routes.py (POST /api/estimate-x3/ask).
"""
import html
import os
import re

MODEL = os.getenv("SDI_GUIDE_MODEL", "claude-opus-5-5")
MAX_Q, MAX_TURNS, MAX_A = 600, 4, 1500

SYSTEM = """You answer questions from SDI staff about one page of the SDI Intelligence portal, using only the user guide
below. SDI is a UK manufacturer (metal, joinery and acrylics shops). The people asking work in Production, Purchasing,
Customer Services, Estimating or Finance; they are not IT people.

How to answer:
- Plain British English, short: two to six sentences, or a few numbered steps when they ask how to do something.
- Name the buttons, tabs and columns exactly as the guide does.
- Only what the guide says. If the guide doesn't cover it, say so in one sentence and suggest asking James Gray.
  Never invent buttons, numbers, dates or rules.
- No markdown headings or tables; **bold** for a button or tab name is fine.
- If the question is about a specific works order, part or figure, explain where on the page to look and how it's
  worked out - you can't see the data.

The page: {page}

The user guide:
<guide>
{guide}
</guide>"""


def text_of(html_fragment):
    """Readable text of a piece of the page: headings and list items on their own lines, tags dropped."""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html_fragment)
    s = re.sub(r"(?i)<br\s*/?>|</(p|li|h\d|tr|div|ol|ul|table|summary)>", "\n", s)
    s = re.sub(r"(?i)<(h\d)[^>]*>", "\n## ", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n- ", s)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


def section(page_html, start_marker, end_marker):
    """The user guide's part of a page, between two markers in its HTML."""
    i = page_html.find(start_marker)
    if i < 0:
        return ""
    j = page_html.find(end_marker, i + len(start_marker))
    return page_html[i:j if j > 0 else None]


def ask(question, history, guide, page):
    """{'answer': text, 'source': 'claude'} or {'answer': None, 'source': 'guide', 'why': ...} (the page then shows the
    best-matching guide sections)."""
    q = (question or "").strip()[:MAX_Q]
    if not q:
        return {"answer": None, "source": "guide", "why": "Type a question first."}
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return {"answer": None, "source": "guide", "why": "Claude isn't switched on for the portal (no ANTHROPIC_API_KEY) "
                                                         "- here are the parts of the guide that match."}
    try:
        import anthropic
    except ImportError:
        return {"answer": None, "source": "guide", "why": "The anthropic package isn't installed for the portal - here "
                                                         "are the parts of the guide that match."}
    # Earlier turns go in as plain text inside the one question, so a follow-up ("and then?") makes sense
    turns = [t for t in (history or []) if isinstance(t, dict) and t.get("q")][-MAX_TURNS:]
    earlier = "\n\n".join(f"Q: {str(t['q'])[:MAX_Q]}\nA: {str(t.get('a') or '')[:MAX_A]}" for t in turns)
    content = (f"Earlier in this chat:\n{earlier}\n\nNew question: {q}" if earlier else q)
    system = [{"type": "text", "text": SYSTEM.format(page=page, guide=guide[:60000]),
               "cache_control": {"type": "ephemeral"}}]        # the guide is the same every time: cached
    client = anthropic.Anthropic().with_options(timeout=60.0, max_retries=1)
    common = dict(model=MODEL, max_tokens=8000, system=system, messages=[{"role": "user", "content": content}])
    try:
        try:   # low effort: a short answer from a short guide; on a refusal, the API's own fallback model answers
            r = client.beta.messages.create(**common, output_config={"effort": "low"},
                                            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except (TypeError, AttributeError, anthropic.BadRequestError):   # an older package / option: the plain request
            r = client.messages.create(**common)
    except anthropic.AuthenticationError:
        return {"answer": None, "source": "guide", "why": "The portal's Claude key was refused - here are the parts of "
                                                         "the guide that match. (Tell James.)"}
    except anthropic.RateLimitError:
        return {"answer": None, "source": "guide", "why": "Claude is busy - try again in a minute. Meanwhile, the parts "
                                                         "of the guide that match:"}
    except anthropic.APIStatusError as e:
        return {"answer": None, "source": "guide", "why": f"Claude answered with an error ({e.status_code}) - here are "
                                                         "the parts of the guide that match."}
    except anthropic.APIConnectionError:
        return {"answer": None, "source": "guide", "why": "The portal couldn't reach Claude - here are the parts of the "
                                                         "guide that match."}
    if r.stop_reason == "refusal":
        return {"answer": None, "source": "guide", "why": "Claude couldn't answer that one - here are the parts of the "
                                                         "guide that match."}
    a = "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    if not a:
        return {"answer": None, "source": "guide", "why": "No answer came back - here are the parts of the guide that "
                                                         "match."}
    return {"answer": a, "source": "claude"}
