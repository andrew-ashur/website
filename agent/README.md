# Slack → Notion Task Agent

A lightweight Python agent that monitors a Slack channel for messages and automatically creates tasks in your Notion **Tasks Tracker** database.

## How It Works

1. The agent polls a Slack channel (or DM) for new messages
2. It parses task details from the message text
3. It creates a task in your Notion Tasks Tracker with the parsed fields
4. It replies in the Slack thread confirming the task was created

## Message Formats

### Simple format
```
Review Q1 financials by 3/28
```
Creates a task named "Review Q1 financials" with a due date of March 28.

### Pipe-delimited format (for more control)
```
Call Nisbet about partnership | due: 2026-04-01 | status: in progress | context: Follow up from dinner
```

### Supported fields
| Field     | Aliases                        | Example values                                      |
|-----------|-------------------------------|-----------------------------------------------------|
| Task name | (first segment, required)     | Any text                                            |
| due       | `due date`, `date`, `by`      | `today`, `tomorrow`, `3/28`, `2026-04-01`, `in 3 days` |
| status    | `state`                       | `todo`, `in progress`, `wip`, `done`, `blocked`     |
| context   | `note`, `notes`, `info`       | Any text                                            |

### Status shortcuts
| You type                          | Notion status     |
|----------------------------------|-------------------|
| `todo`, `new`, `not started`    | Not started       |
| `ack`, `acknowledged`           | Acknowledged      |
| `doing`, `wip`, `in progress`   | In progress       |
| `blocked`, `waiting`            | Waiting For...    |
| `done`, `complete`, `finished`  | Done              |
| `cancelled`, `canceled`         | Cancelled         |

## Setup

### 1. Create a Slack App
1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Under **OAuth & Permissions**, add these Bot Token Scopes:
   - `channels:history` (read public channel messages)
   - `groups:history` (read private channel messages)
   - `im:history` (read DM messages)
   - `chat:write` (post confirmations)
3. Install the app to your workspace and copy the **Bot User OAuth Token** (`xoxb-...`)
4. Invite the bot to the channel you want to monitor

### 2. Create a Notion Integration
1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Create a new integration and copy the token (`ntn_...`)
3. Share your **Tasks Tracker** database with the integration (click "..." on the database → Connections → Add your integration)

### 3. Configure & Run
```bash
cd agent
cp .env.example .env
# Edit .env with your tokens and channel ID

pip install -r requirements.txt
python slack_notion_agent.py
```

## Optional: Use a Prefix Filter

If you don't want *every* message in the channel to become a task, set `TASK_PREFIX=/task` in your `.env`. Then only messages starting with `/task` will be processed:

```
/task Review Q1 financials by 3/28
```

## Running as a Service

For persistent operation, use a process manager like `systemd`, `pm2`, or `supervisor`, or deploy to a cloud service (Railway, Render, etc.).
