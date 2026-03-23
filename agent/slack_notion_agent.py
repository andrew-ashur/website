#!/usr/bin/env python3
"""
Slack -> Notion Task Agent (Socket Mode)

Listens for Slack messages via Socket Mode (real-time, no polling) and
automatically creates tasks in Andrew's Personal Task Tracker in Notion.

Message format examples:
  "Review Q1 financials by 3/28"
  "Call Nisbet about partnership | due: 2026-04-01 | priority: p1"
  "Fix landing page copy | tags: lucid, marketing | notes: Part of website redesign"
  "Send board deck | due: tomorrow | priority: p2 | status: to do | tags: fundraise"

Supported fields (pipe-delimited):
  - Name:       first segment (required)
  - due:        due date (natural: "3/28", "tomorrow", or ISO: 2026-04-01)
  - priority:   P1, P2, P3, P4
  - status:     Inbox, To Do, In Progress, Done, Dropped
  - tags:       comma-separated (lucid, personal, hiring, product, fundraise, ops, etc.)
  - notes:      freeform notes
  - recurring:  none, daily, weekly, monthly
"""

import os
import re
import logging
from datetime import datetime, timedelta
from typing import Optional

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from notion_client import Client as NotionClient
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp-... token for Socket Mode
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ.get(
    "NOTION_DATABASE_ID", "31381f88091081869611c3a55af8287e"
)
TASK_PREFIX = os.environ.get("TASK_PREFIX", "")  # optional prefix filter e.g. "/task"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("slack-notion-agent")

app = App(token=SLACK_BOT_TOKEN)
notion = NotionClient(auth=NOTION_TOKEN)

# ---------------------------------------------------------------------------
# Valid values for select/multi-select properties
# ---------------------------------------------------------------------------
VALID_TAGS = {
    "lucid", "personal", "hiring", "product", "fundraise",
    "ops", "legal", "marketing", "sales", "admin",
    "optimization", "email", "meeting-notes",
}
VALID_RECURRING = {"none", "daily", "weekly", "monthly"}

# ---------------------------------------------------------------------------
# Status mapping – normalises casual input to exact Notion status values
# ---------------------------------------------------------------------------
STATUS_MAP = {
    "inbox": "Inbox",
    "new": "Inbox",
    "todo": "To Do",
    "to do": "To Do",
    "to-do": "To Do",
    "next": "To Do",
    "in progress": "In Progress",
    "in-progress": "In Progress",
    "doing": "In Progress",
    "started": "In Progress",
    "wip": "In Progress",
    "done": "Done",
    "complete": "Done",
    "completed": "Done",
    "finished": "Done",
    "dropped": "Dropped",
    "cancelled": "Dropped",
    "canceled": "Dropped",
    "drop": "Dropped",
    "skip": "Dropped",
}

DEFAULT_STATUS = "Inbox"

# ---------------------------------------------------------------------------
# Priority mapping – normalises casual input
# ---------------------------------------------------------------------------
PRIORITY_MAP = {
    "p1": "P1", "1": "P1", "urgent": "P1", "critical": "P1",
    "p2": "P2", "2": "P2", "high": "P2",
    "p3": "P3", "3": "P3", "medium": "P3", "med": "P3",
    "p4": "P4", "4": "P4", "low": "P4",
}


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
def parse_date(text: str) -> Optional[str]:
    """Parse a human-friendly date string into ISO-8601 (YYYY-MM-DD)."""
    text = text.strip().lower()
    today = datetime.now().date()

    if text in ("today", "now"):
        return today.isoformat()
    if text in ("tomorrow", "tmrw", "tmr"):
        return (today + timedelta(days=1)).isoformat()
    if text == "next week":
        return (today + timedelta(weeks=1)).isoformat()
    if text in ("eod", "end of day"):
        return today.isoformat()
    if text in ("eow", "end of week"):
        days_until_friday = (4 - today.weekday()) % 7 or 7
        return (today + timedelta(days=days_until_friday)).isoformat()
    if text in ("eom", "end of month"):
        if today.month == 12:
            return datetime(today.year + 1, 1, 1).date().isoformat()
        next_month = today.replace(month=today.month + 1, day=1)
        return (next_month - timedelta(days=1)).isoformat()

    # Relative: "in 3 days", "in 2 weeks"
    rel = re.match(r"in\s+(\d+)\s+(day|week|month)s?", text)
    if rel:
        n, unit = int(rel.group(1)), rel.group(2)
        if unit == "day":
            return (today + timedelta(days=n)).isoformat()
        if unit == "week":
            return (today + timedelta(weeks=n)).isoformat()
        if unit == "month":
            return (today + timedelta(days=n * 30)).isoformat()

    # Explicit ISO
    iso = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if iso:
        return iso.group(1)

    # US-style: M/D or M/D/YYYY
    us = re.match(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", text)
    if us:
        month, day = int(us.group(1)), int(us.group(2))
        year = int(us.group(3)) if us.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            pass

    return None


def parse_tags(text: str) -> list[str]:
    """Parse comma-separated tags, validating against known tags."""
    raw = [t.strip().lower() for t in text.split(",")]
    return [t for t in raw if t in VALID_TAGS]


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------
def parse_task_message(text: str) -> Optional[dict]:
    """
    Parse a Slack message into task fields.

    Supports two formats:
      1. Pipe-delimited:  "Task name | due: 3/28 | priority: p1 | tags: lucid, product"
      2. Simple with trailing "by <date>":  "Review deck by Friday"

    Returns None if the message doesn't look like a task.
    """
    text = text.strip()

    # If a prefix is configured, only process matching messages
    if TASK_PREFIX:
        if not text.lower().startswith(TASK_PREFIX.lower()):
            return None
        text = text[len(TASK_PREFIX):].strip()

    if not text:
        return None

    task: dict = {
        "name": "",
        "status": DEFAULT_STATUS,
        "priority": None,
        "due_date": None,
        "notes": None,
        "tags": [],
        "recurring": None,
        "original_text": text,
    }

    # Pipe-delimited fields
    if "|" in text:
        parts = [p.strip() for p in text.split("|")]
        task["name"] = parts[0]
        for part in parts[1:]:
            kv = part.split(":", 1)
            if len(kv) != 2:
                continue
            key, val = kv[0].strip().lower(), kv[1].strip()
            if key in ("due", "due date", "date", "by"):
                task["due_date"] = parse_date(val)
            elif key in ("status", "state"):
                task["status"] = STATUS_MAP.get(val.lower(), DEFAULT_STATUS)
            elif key in ("priority", "pri", "p"):
                task["priority"] = PRIORITY_MAP.get(val.lower())
            elif key in ("tags", "tag"):
                task["tags"] = parse_tags(val)
            elif key in ("notes", "note", "context", "info"):
                task["notes"] = val
            elif key in ("recurring", "repeat", "recur"):
                val_lower = val.lower()
                if val_lower in VALID_RECURRING:
                    task["recurring"] = val_lower
    else:
        # Simple format: "Do something by <date>"
        by_match = re.search(r"\s+by\s+(.+)$", text, re.IGNORECASE)
        if by_match:
            task["name"] = text[: by_match.start()].strip()
            task["due_date"] = parse_date(by_match.group(1))
        else:
            task["name"] = text

    if not task["name"]:
        return None

    return task


# ---------------------------------------------------------------------------
# Notion integration
# ---------------------------------------------------------------------------
def create_notion_task(task: dict) -> str:
    """Create a task in the Notion Personal Task Tracker. Returns the page URL."""
    today = datetime.now().date().isoformat()

    properties: dict = {
        "Name": {"title": [{"text": {"content": task["name"]}}]},
        "Status": {"select": {"name": task["status"]}},
        "Source": {"select": {"name": "slack"}},
        "Created At": {"date": {"start": today}},
        "Original Text": {
            "rich_text": [{"text": {"content": task.get("original_text", "")[:2000]}}]
        },
    }

    if task.get("priority"):
        properties["Priority"] = {"select": {"name": task["priority"]}}

    if task.get("due_date"):
        properties["Due"] = {"date": {"start": task["due_date"]}}

    if task.get("notes"):
        properties["Notes"] = {
            "rich_text": [{"text": {"content": task["notes"][:2000]}}]
        }

    if task.get("tags"):
        properties["Tags"] = {
            "multi_select": [{"name": t} for t in task["tags"]]
        }

    if task.get("recurring"):
        properties["Recurring"] = {"select": {"name": task["recurring"]}}

    page = notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=properties,
    )

    url = page.get("url", "")
    log.info("Created Notion task: %s -> %s", task["name"], url)
    return url


# ---------------------------------------------------------------------------
# Slack event handler
# ---------------------------------------------------------------------------
@app.event("message")
def handle_message(event, say):
    """Handle incoming Slack messages and create Notion tasks."""
    # Ignore bot messages, message edits, and thread replies
    if event.get("bot_id") or event.get("subtype"):
        return

    text = event.get("text", "")
    if not text:
        return

    task = parse_task_message(text)
    if not task:
        return

    log.info("Parsed task from Slack: %s", task["name"])

    try:
        notion_url = create_notion_task(task)
    except Exception:
        log.exception("Failed to create Notion task")
        say(
            text="Sorry, I couldn't create that task in Notion. Please try again.",
            thread_ts=event.get("ts"),
        )
        return

    # Build confirmation message
    fields = [f"*Task:* {task['name']}"]
    fields.append(f"*Status:* {task['status']}")
    if task.get("priority"):
        fields.append(f"*Priority:* {task['priority']}")
    if task.get("due_date"):
        fields.append(f"*Due:* {task['due_date']}")
    if task.get("tags"):
        fields.append(f"*Tags:* {', '.join(task['tags'])}")
    if task.get("notes"):
        fields.append(f"*Notes:* {task['notes']}")
    if task.get("recurring") and task["recurring"] != "none":
        fields.append(f"*Recurring:* {task['recurring']}")
    fields.append(f"<{notion_url}|View in Notion>")

    say(text="\n".join(fields), thread_ts=event.get("ts"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    log.info("Starting Slack -> Notion Task Agent (Socket Mode)...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
