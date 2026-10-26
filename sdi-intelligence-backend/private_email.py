"""Private email foundation. No send/delete/move API; no model executes actions.

Transport and verified identity are injected by the host. Disabled unless configured.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
import base64
import binascii
import hashlib
import json
import re
import secrets
import sqlite3
import time

OCTET = "application/octet-stream"
# Big enough for the drawings and spec sheets that actually arrive; small enough
# that one request cannot hold the service's memory. Above it, Outlook.
MAX_ATTACHMENT = 25 * 1024 * 1024


class Denied(Exception):
    pass


def _file_name(name):
    """A sender's file name, reduced to a name.

    It arrives from outside and ends up in a download header and, wherever the
    person saves it, on a disk. So: no directory separators, no traversal, no
    control characters, and never empty.
    """
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", str(name or "")).strip()
    cleaned = cleaned.replace("\\", "/").rsplit("/", 1)[-1].strip(" .")
    cleaned = re.sub(r'[<>:"|?*]', "_", cleaned)
    return cleaned[:160] or "attachment"


@dataclass(frozen=True)
class Policy:
    tenant: str = ""
    owner: str = ""
    enabled: bool = False

    def check(self, claims):
        if not self.enabled or not self.tenant or not self.owner:
            raise Denied("Private assistant is not configured")
        if (not claims or claims.get("kind") != "user"
                or claims.get("tid") != self.tenant
                or claims.get("oid") != self.owner):
            raise Denied("Private assistant: owner sign-in required")


class GraphMailbox:
    """Fixed Graph operations only. Never accept an arbitrary URL from the model."""
    BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, request, owner):
        self.request = request
        self.owner = owner

    def verify(self):
        me = self.request("GET", self.BASE + "/me", params={"$select": "id"})
        if me.get("id") != self.owner:
            raise Denied("Graph mailbox does not match the permitted owner")

    def review(self, now=None, max_pages=10):
        self.verify()
        end = now or datetime.now(timezone.utc)
        start = end - timedelta(days=7)
        iso = lambda dt: dt.isoformat().replace("+00:00", "Z")
        params = {"$filter": f"receivedDateTime ge {iso(start)} and receivedDateTime lt {iso(end)}",
                  "$select": "id,subject,from,receivedDateTime,bodyPreview,webLink,"
                             "conversationId,hasAttachments",
                  "$orderby": "receivedDateTime desc", "$top": 50}
        url = self.BASE + "/me/messages"
        messages, seen = [], set()
        for _ in range(max_pages):
            if url in seen:
                raise Denied("Graph pagination loop; review incomplete")
            seen.add(url)
            page = self.request("GET", url, params=params)
            for message in page.get("value", []):
                # Enforce bounds ourselves: search providers can ignore filters.
                try:
                    received = datetime.fromisoformat(message["receivedDateTime"].replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    raise Denied("Message date missing or invalid; review incomplete")
                if start <= received < end:
                    messages.append(message)
            url = page.get("@odata.nextLink")
            if not url:
                break
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com"
                    or parsed.path != "/v1.0/me/messages"):
                raise Denied("Unexpected Graph pagination destination")
            params = None
        return {"start": iso(start), "end": iso(end), "complete": not bool(url),
                "messages": messages, "scope": "mailbox previews; not a full thread or attachment review",
                "ai_summary": "not connected"}

    def source(self, message_id):
        self.verify()
        return self.request("GET", self.BASE + "/me/messages/" + quote(message_id, safe=""),
                            params={"$select": "id,subject,from,replyTo,webLink"})

    def attachments(self, message_id):
        """What is attached: names, types and sizes. Never content.

        The list is cheap and safe to show beside every message. Content costs a
        second, deliberate request for one named attachment, so nothing is pulled
        out of the mailbox because a page happened to render.
        """
        self.verify()
        page = self.request(
            "GET", self.BASE + "/me/messages/" + quote(message_id, safe="") + "/attachments",
            params={"$select": "id,name,contentType,size,isInline"})
        listed = []
        for item in page.get("value", []):
            listed.append({
                "id": str(item.get("id") or ""),
                "name": _file_name(item.get("name")),
                "contentType": str(item.get("contentType") or OCTET),
                "size": int(item.get("size") or 0),
                "isInline": bool(item.get("isInline")),
                # A file is downloadable here. A forwarded email or a link to a
                # file on a share is not, and says so rather than failing later.
                "kind": str(item.get("@odata.type") or "").rsplit(".", 1)[-1],
            })
        return {"message_id": message_id, "attachments": listed}

    def attachment(self, message_id, attachment_id):
        """One attachment's bytes, by name and id, with its stated type.

        The type is what the sender claimed. It decides nothing here: the route
        serves these bytes as a download, never as a page on this origin, so an
        HTML or SVG attachment cannot run as though it came from us.
        """
        self.verify()
        item = self.request(
            "GET", self.BASE + "/me/messages/" + quote(message_id, safe="")
            + "/attachments/" + quote(attachment_id, safe=""))
        kind = str(item.get("@odata.type") or "").rsplit(".", 1)[-1]
        if kind != "fileAttachment":
            raise Denied("That is an attached email or a link to a file, not a file. "
                         "Open the message in Outlook to see it.")
        raw = item.get("contentBytes")
        if not isinstance(raw, str) or not raw:
            raise Denied("Microsoft returned no content for that attachment")
        try:
            content = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error):
            raise Denied("That attachment's content could not be read")
        if len(content) > MAX_ATTACHMENT:
            raise Denied(f"That attachment is larger than "
                         f"{MAX_ATTACHMENT // (1024 * 1024)}MB. Open it in Outlook.")
        return {"name": _file_name(item.get("name")),
                "contentType": str(item.get("contentType") or OCTET),
                "content": content}

    def create_reply(self, message_id, body):
        self.verify()
        # createReply creates a draft; sending is a different endpoint, never exposed.
        result = self.request("POST", self.BASE + "/me/messages/" + quote(message_id, safe="") + "/createReply",
                              json={"message": {"body": {"contentType": "Text", "content": body}}})
        if not result.get("id") or result.get("isDraft") is not True:
            raise Denied("Draft creation outcome requires manual verification")
        return {"id": result["id"], "isDraft": True, "webLink": result.get("webLink")}


class DraftStore:
    """Persistent single-use approval. Uncertain writes are NOT automatically retried.

Database contains private draft text. Host must encrypt disk and restrict its ACL.
"""
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, owner TEXT, expires REAL, payload TEXT, digest TEXT, state TEXT, result TEXT)")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def propose(self, owner, source, body):
        if not body.strip() or len(body) > 20000:
            raise Denied("Reply must contain 1 to 20000 characters")
        recipients = source.get("replyTo") or [source.get("from")]
        if not recipients or any(not r or not r.get("emailAddress", {}).get("address") for r in recipients):
            raise Denied("Reply recipients could not be established")
        payload = {"message_id": source["id"], "subject": source.get("subject", ""),
                   "recipients": recipients, "body": body}
        encoded = json.dumps(payload, sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        pid = secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute("DELETE FROM proposals WHERE expires < ? AND state = 'pending'", (time.time(),))
            db.execute("INSERT INTO proposals VALUES (?,?,?,?,?,'pending',NULL)",
                       (pid, owner, time.time() + 900, encoded, digest))
        return {"proposal_id": pid, "digest": digest, **payload, "expires_in_seconds": 900}

    def confirm(self, owner, pid, digest, mailbox):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner,expires,payload,digest,state,result FROM proposals WHERE id=?", (pid,)).fetchone()
            if not row or row[0] != owner or row[3] != digest:
                raise Denied("Proposal does not match this owner and approval")
            if row[4] == "saved":
                return json.loads(row[5])
            if row[4] != "pending" or row[1] < time.time():
                raise Denied("Proposal expired or outcome uncertain; inspect Outlook before trying again")
            payload = json.loads(row[2])
            db.execute("UPDATE proposals SET state='attempted' WHERE id=?", (pid,))
        # 'attempted' survives a crash or timeout. Never duplicate an uncertain POST.
        source = mailbox.source(payload["message_id"])
        recipients = source.get("replyTo") or [source.get("from")]
        if recipients != payload["recipients"]:
            raise Denied("Reply recipients changed; create and review a new proposal")
        result = mailbox.create_reply(payload["message_id"], payload["body"])
        with self.db() as db:
            db.execute("UPDATE proposals SET state='saved',result=?,payload='{}' WHERE id=?",
                       (json.dumps(result), pid))
        return result
