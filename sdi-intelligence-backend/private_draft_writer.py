"""Claude words a reply. It is a suggestion on a screen, never a sent email.

Nothing here reaches Microsoft. The writer is handed the text of one message and
gives back wording; putting that wording anywhere is private_email.DraftStore's
job, and only after it has been shown and confirmed. So the worst a bad draft can
do is waste the time it takes to read it.

Two rules the system prompt exists to hold, because a plausible invention in a
reply to a customer is worse than no reply at all:

  * it answers from the message in front of it and nothing else - no prices,
    dates, stock, lead times or commitments that are not already in the thread;
  * where an answer needs something it has not been told, it says so in the
    draft rather than filling the gap.

No key configured, or Claude unreachable, means no suggestion - the screen falls
back to an empty box, which is what it does today. A reply that cannot be worded
is never an error; it is just a reply you write yourself.
"""
import json
import os
import re

MODEL = "claude-opus-5-5"
MAX_TOKENS = 2000
# A long thread, truncated. Claude needs the message, not the whole history, and
# an unbounded body is somebody else's cost and our timeout.
MAX_SOURCE = 6000

SYSTEM = """You read work email for James Gray, AI & Systems Controller at SDI Displays, a UK manufacturer of retail displays, and draft his replies.

You are writing a DRAFT. James reads it, amends it, and sends it himself. You never send anything.

Return ONE JSON object and nothing else, with exactly these four keys:

{"summary": "...", "asks": ["..."], "draft": "...", "gaps": ["..."]}

- "summary": one or two sentences saying what the message actually says and who it is from. This is how James checks you have read it correctly before he trusts the draft, so it must be your honest reading, not a restatement of the subject line. If the message is unclear, say it is unclear.
- "asks": each separate thing the sender wants, one per entry. An empty list if the message asks for nothing.
- "draft": the reply body, as described below.
- "gaps": every piece of information the draft needed and you were not given, worded as James would need to look it up - for example "the actual delivery date for the Morrisons bay units". An empty list if the draft invents nothing and leaves nothing blank. Every [square-bracket] placeholder in the draft must appear here.

Write the reply he would write:

- British English. Plain, direct, courteous. No American spellings.
- Short. Most replies are two to five sentences. Say the thing and stop.
- No "I hope this email finds you well", no "I wanted to reach out", no "Please do not hesitate".
- Match the sender's formality. A one-line question gets a one-line answer.
- Sign off "Thanks, James" unless the thread is formal, then "Kind regards, James".

What you must not do:

- Do not state any fact that is not in the message you were given. No prices, quantities, dates, lead times, stock levels, names or commitments you were not told.
- Where the reply needs something you have not been told, write the sentence with a clear gap for James to fill, like: "We can have these with you by [date]." Never guess a value and never leave the gap silent.
- Do not agree to anything on his behalf: no discounts, deadlines, meetings or orders. Propose, and let him commit.
- Do not apologise for SDI unless the message itself establishes something went wrong.

The "draft" value is the body text only: no subject line, no explanation of what you wrote, no markdown."""


def _opt(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def available() -> bool:
    """Whether a suggestion can be asked for at all. The screen uses this to
    decide between offering the button and not mentioning the feature."""
    return bool(_opt("ANTHROPIC_API_KEY")) and _opt("SDI_PRIVATE_DRAFT_AI", "yes").lower() == "yes"


def _plain(html_or_text: str) -> str:
    """Message bodies arrive as HTML often enough to matter. Tags carry no
    meaning for a reply and cost tokens, so they go."""
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html_or_text or "",
                  flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                         ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", text)).strip()


def _sender(message: dict) -> str:
    who = (message.get("from") or {}).get("emailAddress") or {}
    name, address = who.get("name", ""), who.get("address", "")
    return f"{name} <{address}>".strip() if name or address else "unknown sender"


def _blank() -> dict:
    return {"summary": "", "asks": [], "draft": "", "gaps": []}


def _read(text: str) -> dict:
    """The model's answer, as the four parts, however it wrapped them.

    A draft on its own is not reviewable: the summary is how James checks the
    message was understood before he trusts the reply. So wording that arrives
    without one is still shown - as a draft with no summary, which reads as the
    warning it is - rather than being thrown away or quietly dressed up as read.
    """
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()
    try:
        got = json.loads(text)
    except ValueError:
        return {**_blank(), "draft": text}
    if not isinstance(got, dict) or not isinstance(got.get("draft"), str):
        return {**_blank(), "draft": text}
    listed = lambda key: [str(x) for x in got.get(key) or [] if str(x).strip()]
    return {"summary": str(got.get("summary") or "").strip(),
            "asks": listed("asks"),
            "draft": got["draft"].strip(),
            "gaps": listed("gaps")}


def compose(message: dict, instruction: str = "", client=None) -> dict:
    """What the message says, and a suggested reply to it.

    Returns {"summary", "asks", "draft", "gaps"} - all empty if no suggestion
    could be had. The summary and the draft come from the same reading in the
    same call, so a summary that is wrong tells James the draft is wrong too.
    That is the point of showing it: he approves a reading, not just wording.

    `instruction` is whatever James typed into the box before asking - "say yes
    but push the date to the 14th", "ask what finish they want". It steers the
    draft; it is not a fact he has verified, so the no-invention rules above
    still apply to it.

    `client` is for the tests. Nothing else passes it.
    """
    if client is None and not available():
        return _blank()
    body = _plain(message.get("body", {}).get("content")
                  or message.get("bodyPreview", ""))[:MAX_SOURCE]
    if not body.strip():
        return _blank()
    asked = {
        "from": _sender(message),
        "subject": message.get("subject", ""),
        "received": message.get("receivedDateTime", ""),
        "message": body,
    }
    if instruction.strip():
        asked["how_james_wants_it_answered"] = instruction.strip()[:1000]
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        answer = client.messages.create(
            model=_opt("SDI_PRIVATE_DRAFT_MODEL", MODEL),
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=SYSTEM,
            messages=[{"role": "user",
                       "content": json.dumps(asked, ensure_ascii=False)}],
        )
        text = "".join(block.text for block in answer.content
                       if getattr(block, "type", "") == "text").strip()
    except Exception as problem:                                   # noqa: BLE001
        # Never an error on the screen: an empty box is a working screen.
        print(f"[private-email] no suggested wording this time: "
              f"{type(problem).__name__}: {problem}", flush=True)
        return _blank()
    return _read(text)
