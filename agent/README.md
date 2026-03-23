# Slack → Notion Task Agent

A lightweight Python agent that monitors a Slack channel for messages and automatically creates tasks in your Notion **Personal Task Tracker** database.

## How It Works

1. The agent polls a Slack channel (or DM) for new messages
2. It parses task details from the message text
3. It creates a task in Notion with Source set to `slack` and the original message preserved
4. It replies in the Slack thread confirming the task was created with a link back to Notion

## Message Formats

### Simple format
```
Review Q1 financials by 3/28
```
Creates a task named "Review Q1 financials" due March 28, status Inbox.

### Pipe-delimited format (for full control)
```
Call Nisbet about partnership | due: 2026-04-01 | priority: p1 | tags: lucid
```

### Full example with all fields
```
Send board deck | due: tomorrow | priority: p2 | status: to do | tags: fundraise, ops | notes: Include Q1 numbers | recurring: weekly
```

## Supported Fields

| Field     | Aliases                        | Example values                                           |
|-----------|-------------------------------|----------------------------------------------------------|
| Name      | (first segment, required)     | Any text                                                 |
| due       | `due date`, `date`, `by`      | `today`, `tomorrow`, `eow`, `3/28`, `2026-04-01`, `in 3 days` |
| priority  | `pri`, `p`                    | `p1`, `urgent`, `high`, `p3`, `low`                      |
| status    | `state`                       | `inbox`, `todo`, `in progress`, `done`, `dropped`        |
| tags      | `tag`                         | `lucid`, `personal`, `hiring`, `product`, `fundraise`... |
| notes     | `note`, `context`, `info`     | Any text                                                 |
| recurring | `repeat`, `recur`             | `daily`, `weekly`, `monthly`                             |

### Priority shortcuts
| You type                         | Notion value |
|---------------------------------|-------------|
| `p1`, `1`, `urgent`, `critical` | P1          |
| `p2`, `2`, `high`               | P2          |
| `p3`, `3`, `medium`, `med`      | P3          |
| `p4`, `4`, `low`                | P4          |

### Status shortcuts
| You type                          | Notion value |
|----------------------------------|-------------|
| `inbox`, `new`                   | Inbox       |
| `todo`, `to do`, `next`         | To Do       |
| `doing`, `wip`, `in progress`   | In Progress |
| `done`, `complete`, `finished`  | Done        |
| `dropped`, `cancelled`, `skip`  | Dropped     |

### Date shortcuts
| You type              | Result               |
|----------------------|----------------------|
| `today`, `now`, `eod`| Today                |
| `tomorrow`, `tmrw`   | Tomorrow             |
| `eow`                | Next Friday          |
| `eom`                | End of month         |
| `next week`          | 7 days from now      |
| `in 3 days`          | 3 days from now      |
| `3/28` or `3/28/26`  | March 28, 2026       |
| `2026-04-01`         | April 1, 2026        |

### Available tags
`lucid`, `personal`, `hiring`, `product`, `fundraise`, `ops`, `legal`, `marketing`, `sales`, `admin`, `optimization`, `email`, `meeting-notes`

## Auto-populated Fields

Every task created by the agent automatically includes:
- **Source:** `slack`
- **Created At:** today's date
- **Original Text:** the raw Slack message (for reference)
- **Status:** `Inbox` (default, unless overridden)

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
3. Share your **Personal Task Tracker** database with the integration (click "..." on the database → Connections → Add your integration)

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
