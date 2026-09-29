"""Ask resource owners on Slack whether a flagged resource is still needed.

Flow:
  1. `ask_owner()` posts one message per finding — in the team channel with
     the owner @-mentioned (so the team sees it), or as a DM when no channel
     is configured. Unknown owners go to the channel as "who owns this?".
  2. People answer with a reaction: ✅ keep it, 🗑️ OK to delete. A thread
     reply can add the reason.
  3. `sync()` reads the reactions back and records the answer — the
     "owner confirmed" evidence a SOC 2 change ticket needs.

Only Slack's Web API is used (outbound HTTPS), so the local server never has
to be reachable from the internet. Nothing is ever deleted automatically.

Config (env only, never stored):
  AWSCO_SLACK_BOT_TOKEN   xoxb-… bot token
  AWSCO_SLACK_CHANNEL     channel ID for team-visible asks (optional)
  AWSCO_SLACK_USER_MAP    optional JSON {"iam-user-or-email": "U0123 or email"}
Bot scopes: chat:write, users:read, users:read.email, reactions:read, and
channels:history / im:history to read thread replies.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from awsco.models import Finding

API = "https://slack.com/api/"
KEEP = "white_check_mark"
DELETE_OK = "wastebasket"


class SlackError(RuntimeError):
    pass


def config() -> dict[str, Any]:
    token = os.environ.get("AWSCO_SLACK_BOT_TOKEN", "").strip()
    return {
        "configured": token.startswith("xoxb-"),
        "channel": os.environ.get("AWSCO_SLACK_CHANNEL", "").strip() or None,
        "user_map": _user_map(),
    }


def _user_map() -> dict[str, str]:
    raw = os.environ.get("AWSCO_SLACK_USER_MAP", "").strip()
    if not raw:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in json.loads(raw).items()}
    except (ValueError, AttributeError):
        return {}


def call(method: str, **params: Any) -> dict[str, Any]:
    """POST a Slack Web API method (form-encoded; JSON values pre-serialised)."""
    token = os.environ.get("AWSCO_SLACK_BOT_TOKEN", "").strip()
    if not token:
        raise SlackError("AWSCO_SLACK_BOT_TOKEN is not set")
    body = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
         for k, v in params.items() if v is not None}
    ).encode()
    req = urllib.request.Request(
        API + method,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — fixed https host
        data = json.loads(resp.read().decode())
    if not data.get("ok"):
        raise SlackError(f"{method}: {data.get('error', 'unknown error')}")
    return data


# --- who to ask ------------------------------------------------------------------


def slack_user_for(owner: dict[str, Any] | None) -> str | None:
    """Slack user ID for a finding's owner, or None if we can't tell."""
    if not owner or owner.get("source") == "unknown" or owner.get("is_service"):
        return None
    mapping = _user_map()
    for key in (owner.get("email"), owner.get("name")):
        if key and key.lower() in mapping:
            target = mapping[key.lower()]
            if target.startswith(("U", "W")) and "@" not in target:
                return target
            owner = {**owner, "email": target}
            break
    email = owner.get("email")
    if not email:
        return None
    try:
        return call("users.lookupByEmail", email=email)["user"]["id"]
    except SlackError:
        return None


# --- the message ------------------------------------------------------------------


def _owner_line(owner: dict[str, Any] | None, user_id: str | None) -> str:
    if not owner or owner.get("source") == "unknown":
        return "*Owner:* unknown — no owner tag and no recent CloudTrail history. Who owns this?"
    who = f"<@{user_id}>" if user_id else f"*{owner.get('name')}*"
    if owner.get("source") == "tag":
        return f"*Owner:* {who} (from the `{owner.get('tag_key')}` tag)"
    when = (owner.get("event_time") or "")[:10]
    return (
        f"*Owner:* {who} — CloudTrail shows they {owner.get('relationship', 'created')} it"
        f" ({owner.get('event_name')}{', ' + when if when else ''})"
    )


def build_message(f: Finding, user_id: str | None) -> dict[str, Any]:
    g = f.guidance or {}
    cost = f"${f.monthly_savings_usd:,.2f}/mo" if f.monthly_savings_usd else "no direct cost"
    risk = (g.get("risks") or [""])[0]
    ask = f"<@{user_id}>, is this still needed?" if user_id else "Is this still needed?"
    text = f"{ask} {f.title} ({f.region}, {cost})"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{ask}*\n{f.title}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Resource*\n`{f.resource_id}`"},
            {"type": "mrkdwn", "text": f"*Region*\n{f.region}"},
            {"type": "mrkdwn", "text": f"*Cost*\n{cost}"},
            {"type": "mrkdwn", "text": f"*Suggested*\n{g.get('recommendation', f.title)}"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": _owner_line(f.owner, user_id)}},
    ]
    if f.description:
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"Why it was flagged: {f.description}"}]})
    if risk:
        blocks.append({"type": "context", "elements": [
            {"type": "mrkdwn", "text": f":warning: If removed: {risk}"}]})
    blocks += [
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            f"React :{KEEP}: to *keep it*, or :{DELETE_OK}: if it's *OK to delete*. "
            "Reply in the thread with a reason if you like."
        )}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": (
            "Sent by aws-cost-optimizer (read-only scan). Nothing is deleted automatically."
        )}]},
    ]
    return {"text": text, "blocks": blocks}


def ask_owner(f: Finding, dry_run: bool = False) -> dict[str, Any]:
    """Post the question. Returns where it went and the message ts."""
    cfg = config()
    user_id = None if dry_run else slack_user_for(f.owner)
    msg = build_message(f, user_id)
    # Team channel when configured (owner @-mentioned); else DM the owner.
    target = cfg["channel"] or user_id
    if dry_run:
        return {"sent": False, "channel": target, "owner_slack_id": user_id, "message": msg}
    if not target:
        raise SlackError(
            "No one to ask: the owner isn't known (or not on Slack) and "
            "AWSCO_SLACK_CHANNEL isn't set."
        )
    resp = call("chat.postMessage", channel=target, text=msg["text"], blocks=msg["blocks"],
                unfurl_links=False)
    return {
        "sent": True,
        "channel": resp["channel"],
        "ts": resp["ts"],
        "owner_slack_id": user_id,
        "message": msg,
    }


# --- reading answers back ------------------------------------------------------------


def decide(reactions: list[dict[str, Any]], owner_slack_id: str | None, bot_id: str | None):
    """(status, responder) from a message's reactions.

    Only the owner's reaction counts when the owner is known; otherwise anyone
    but the bot. If someone says both keep and delete, keep wins — the safe
    default is not deleting.
    """
    def voters(name: str) -> list[str]:
        for r in reactions:
            if r.get("name", "").split("::")[0] == name:
                users = [u for u in r.get("users", []) if u != bot_id]
                return [u for u in users if u == owner_slack_id] if owner_slack_id else users
        return []

    keep, delete = voters(KEEP), voters(DELETE_OK)
    if keep:
        return "keep", keep[0]
    if delete:
        return "delete_ok", delete[0]
    return "pending", None


def read_answer(channel: str, ts: str, owner_slack_id: str | None) -> dict[str, Any]:
    msg = call("reactions.get", channel=channel, timestamp=ts, full=True).get("message", {})
    # The message was posted by our bot, so its author is the bot user.
    status, responder = decide(msg.get("reactions", []), owner_slack_id, msg.get("user"))
    note = None
    if status != "pending":
        try:
            replies = call("conversations.replies", channel=channel, ts=ts, limit=20)["messages"]
            by_responder = [m for m in replies[1:] if m.get("user") == responder]
            note = by_responder[-1]["text"] if by_responder else None
        except SlackError:
            pass  # missing history scope: the reaction alone is the answer
    return {"status": status, "responder": responder, "note": note}
