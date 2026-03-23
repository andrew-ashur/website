#!/usr/bin/env python3
"""
Slack -> Notion Task Agent

Monitors a Slack channel (or DMs) for task messages and automatically
creates tasks in a Notion "Tasks Tracker" database.

Message format examples:
  "Review Q1 financials by 3/28"
  "Call Nisbet about partnership | due: 2026-04-01 | status: in progress"
  "Fix landing page copy | context: Website redesign project"

Supported fields (pipe-delimited):
  - Task name:  first segment (required)
  - due:        due date (natural: "3/28", "tomorrow", or ISO: 2026-04-01)
  - status:     Not started, Acknowledged, In progress, Waiting For..., Done, Cancelled
  - context:    freeform context text
  - project:    project name (matched against existing Notion projects)
"""

import os
import re
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from notion_client import Client as NotionClient
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ.get(
    "NOTION_DATABASE_ID", "1c281f880910806ca7ded22bbc36c736"
)
SLACK_CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "")  # channel or DM to monitor
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))  # seconds
TASK_PREFIX = os.environ.get("TASK_PREFIX", "")  # optional prefix filter e.g. "/task"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("slack-notion-agent")

slack = WebClient(token=SLACK_BOT_TOKEN)
notion = NotionClient(auth=NOTION_TOKEN)

# ---------------------------------------------------------------------------
# Status mapping – normalises casual input to exact Notion status values
# ---------------------------------------------------------------------------
STATUS_MAP = {
    "not started": "Not started",
    "new": "Not started",
    "todo": "Not started",
    "to do": "Not started",
    "acknowledged": "Acknowledged",
    "ack": "Acknowledged",
    "in progress": "In progress",
    "in-progress": "In progress",
    "doing": "In progress",
    "started": "In progress",
    "wip": "In progress",
    "waiting": "Waiting For...",
    "waiting for": "Waiting For...",
    "blocked": "Waiting For...",
    "done": "Done",
    "complete": "Done",
    "completed": "Done",
    "finished": "Done",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
}

DEFAULT_STATUS = "Not started"


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
def parse_date(text: str) -> Optional[str]:
    """Parse a human-friendly date string into ISO-8601 (YYYY-MM-DD)."""
    text = text.strip().lower()
    today = datetime.now().date()

    if text in ("today", "now"):
        return today.isoformat()
    if text in ("tomorrow", "tmrw"):
        return (today + timedelta(days=1)).isoformat()
    if text == "next week":
        return (today + timedelta(weeks=1)).isoformat()

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


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------
def parse_task_message(text: str) -> Optional[dict]:
    """
    Parse a Slack message into task fields.

    Supports two formats:
      1. Pipe-delimited:  "Task name | due: 3/28 | status: in progress | context: notes"
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
        "task_name": "",
        "status": DEFAULT_STATUS,
        "due_date": None,
        "context": None,
    }

    # Pipe-delimited fields
    if "|" in text:
        parts = [p.strip() for p in text.split("|")]
        task["task_name"] = parts[0]
        for part in parts[1:]:
            kv = part.split(":", 1)
            if len(kv) != 2:
                continue
            key, val = kv[0].strip().lower(), kv[1].strip()
            if key in ("due", "due date", "date", "by"):
                task["due_date"] = parse_date(val)
            elif key in ("status", "state"):
                task["status"] = STATUS_MAP.get(val.lower(), DEFAULT_STATUS)
            elif key in ("context", "note", "notes", "info"):
                task["context"] = val
    else:
        # Simple format: "Do something by <date>"
        by_match = re.search(r"\s+by\s+(.+)$", text, re.IGNORECASE)
        if by_match:
            task["task_name"] = text[: by_match.start()].strip()
            task["due_date"] = parse_date(by_match.group(1))
        else:
            task["task_name"] = text

    if not task["task_name"]:
        return None

    return task


# ---------------------------------------------------------------------------
# Notion integration
# ---------------------------------------------------------------------------
def create_notion_task(task: dict) -> str:
    """Create a task in the Notion Tasks Tracker database. Returns the page URL."""
    properties: dict = {
        "Task name": {"title": [{"text": {"content": task["task_name"]}}]},
        "Status": {"status": {"name": task["status"]}},
    }

    if task.get("due_date"):
        properties["Due date"] = {"date": {"start": task["due_date"]}}

    if task.get("context"):
        properties["Context"] = {
            "rich_text": [{"text": {"content": task["context"]}}]
        }

    page = notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=properties,
    )

    url = page.get("url", "")
    log.info("Created Notion task: %s -> %s", task["task_name"], url)
    return url


# ---------------------------------------------------------------------------
# Slack helpers
# ---------------------------------------------------------------------------
def post_confirmation(channel: str, thread_ts: str, task: dict, notion_url: str):
    """Reply in the Slack thread confirming the task was created."""
    fields = [f"*Task:* {task['task_name']}"]
    fields.append(f"*Status:* {task['status']}")
    if task.get("due_date"):
        fields.append(f"*Due:* {task['due_date']}")
    if task.get("context"):
        fields.append(f"*Context:* {task['context']}")
    fields.append(f"<{notion_url}|View in Notion>")

    try:
        slack.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="\n".join(fields),
        )
    except SlackApiError as e:
        log.warning("Could not post confirmation: %s", e.response["error"])


def get_bot_user_id() -> str:
    """Get the bot's own user ID so we can ignore our own messages."""
    resp = slack.auth_test()
    return resp["user_id"]


# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------
def run():
    if not SLACK_CHANNEL_ID:
        log.error(
            "SLACK_CHANNEL_ID is not set. Set it to the channel or DM ID to monitor."
        )
        raise SystemExit(1)

    bot_user_id = get_bot_user_id()
    log.info("Agent started. Monitoring channel %s every %ds", SLACK_CHANNEL_ID, POLL_INTERVAL)

    # Track the latest timestamp we've processed
    last_ts = str(time.time())

    while True:
        try:
            resp = slack.conversations_history(
                channel=SLACK_CHANNEL_ID,
                oldest=last_ts,
                limit=20,
            )
            messages = resp.get("messages", [])

            # Process oldest-first
            for msg in reversed(messages):
                ts = msg.get("ts", "")
                user = msg.get("user", "")
                text = msg.get("text", "")

                # Skip bot's own messages and empty messages
                if user == bot_user_id or not text:
                    continue

                task = parse_task_message(text)
                if task:
                    log.info("Parsed task from Slack: %s", task["task_name"])
                    try:
                        notion_url = create_notion_task(task)
                        post_confirmation(SLACK_CHANNEL_ID, ts, task, notion_url)
                    except Exception:
                        log.exception("Failed to create Notion task")

                # Advance watermark past this message
                if ts > last_ts:
                    last_ts = ts

        except SlackApiError as e:
            log.error("Slack API error: %s", e.response["error"])
        except Exception:
            log.exception("Unexpected error in poll loop")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
