# Building & FM Telegram bot

A standalone Telegram application for **building defects** and **routine maintenance**. It is not
part of the web app: no Flask, nothing imported from `Backend/`, no sign-in through the website. The
only thing it shares with the platform is the PostgreSQL database.

> **This repository is the bot only.** The PostgreSQL schema it shares (`users`, `buildings`,
> `defects`, `defect_comments`, `maintenance_jobs`) is created by the platform's web API in the BMS
> repository (`wdodtelegram-pixel/BMS`, Alembic head `f6a7b8c9d0e1` or later, which makes
> `defects.reporter_id` nullable and adds `bot_reporter_id` / `reporter_label`). Run those
> migrations on the database first. This repo adds only its own `bot_*` tables.

Contents: [Capabilities](#capabilities) · [Architecture](#system-architecture) ·
[Access and mapped members](#access-who-may-use-the-bot) · [Demos](#demos-what-it-looks-like-in-telegram) ·
[Setup](#setup) · [Administration](#administration) · [Tests](#tests) · [Limits](#known-limitations) ·
[Ideas](#suggested-improvements-for-intra-day-reporting)

---

## Capabilities

| # | Capability | Command(s) | Notes |
|---|---|---|---|
| 1 | Access control by allowlist | `/start`, `/whoami` | Anyone not on the list is refused and shown only their own Telegram ID |
| 2 | Maintenance dashboard | `/service` | Status counts for every trade on one screen |
| 3 | Per-trade job lists | `/acmv` `/lift` `/electrical` `/fire` `/plumbing` | Generated from `fm/catalog.py`; a sixth trade needs no new code |
| 4 | Outstanding work | `/pending` | Every job that is not completed |
| 5 | My assigned work | `/myjobs`, `/mydefects` | Needs a *mapped* member (see below) |
| 6 | Defect list | `/defects` | Open defects, newest first, max 25 |
| 7 | Report a defect | `/report` | Guided: title, description, building, priority, optional photo, confirm |
| 8 | Calendar | `/calendar [today\|week\|month\|overdue]`, `/today`, `/overdue` | Maintenance jobs by due date and next service date |
| 9 | Assignment alerts | (pushed) | Sent to a mapped member when a defect is assigned to them; retried on failure |
| 10 | Tappable buttons | inline keyboards | Trade grid, building picker, priority picker; buttons edit messages in place |
| 11 | Native command menu | the blue **Menu** button | Registered with Telegram at start-up |
| 12 | Administration | `python -m botapp.admin ...` | Add/remove people, map to web accounts (command line only) |

**There are no roles.** Everyone on the allowlist has the same, full access. (The web app keeps its
own four roles; the bot ignores them.)

Not in the bot: it does not create or edit maintenance jobs, does not change a defect's status, and
defects have no dates, so they do not appear in the calendar.

---

## System architecture

```
 ┌────────────┐   HTTPS (long polling)   ┌──────────────────────────────────────┐
 │  Telegram  │ ◄──────────────────────► │  Bot  (Bot/botapp)  one process      │
 │  servers   │                          │                                      │
 └────────────┘                          │  main.py        wiring, menu, token  │
        ▲                                │  auth.py        allowlist gate       │
        │ chats                          │  handlers/      account browse defects│
   ┌────┴─────┐                          │  services/      queries (no Telegram)│
   │  People  │                          │  fm/            catalog, messages    │
   └──────────┘                          │  notifications  alert poller (30 s)  │
                                         │  db.py          session per call     │
                                         └───────────────┬──────────────────────┘
                                                         │ SQL (SQLAlchemy)
                                         ┌───────────────▼──────────────────────┐
   ┌──────────────────────┐   SQL        │            PostgreSQL                │
   │  Web API + React app │ ◄──────────► │  shared tables     bot tables        │
   │  (Backend/, Frontend/)│             │  users             bot_members       │
   └──────────────────────┘              │  buildings         bot_notification_ │
                                         │  defects, defect_  log               │
                                         │  comments, mainte- (owned by the bot)│
                                         │  nance_jobs                          │
                                         │  (owned by the API)                  │
                                         └──────────────────────────────────────┘
```

**Two applications, one database.** The bot and the web app never call each other. Stop either and
the other keeps working.

### Request path (one command)

1. Telegram delivers the message to the bot (long polling, one process per token).
2. `@require_member` looks the chat ID up in `bot_members`. Not found → refusal that shows the ID.
3. The handler calls `run_db(fn)`: a worker thread opens a **fresh database session**, runs `fn`
   (query **and** render), returns a finished string, and closes the session.
4. `ui.reply()` sends it, splitting messages over ~4,000 characters, with buttons on the last chunk.

Handlers must query and render inside `run_db` and return strings or dicts, never model instances:
the session is closed when `run_db` returns.

### Code map

```
botapp/main.py            entry point, handler wiring, command menu, token and database checks
botapp/config.py          settings from the environment; today() honours TZ
botapp/db.py              engine, run_db(), Base.query / db.session helpers
botapp/models.py          shared tables (mapped, not owned) + bot_members + bot_notification_log
botapp/auth.py            allowlist lookup, @require_member
botapp/admin.py           the command-line tool
botapp/notifications.py   assignment-alert poller
botapp/handlers/          account.py  browse.py (maintenance, calendar)  defects.py (/defects, /report)
botapp/services/          defect_service.py  maintenance_service.py
botapp/fm/                catalog.py  formatters.py  date_utils.py   (vendored copy)
botapp/ui.py              keyboards, message splitting, reply()
migrations/               the bot's own Alembic (version table alembic_version_bot)
tests/                    pytest against a real PostgreSQL
tools/render_demos.py     regenerates the demos below from the real handlers
```

### Data

| Table | Owner | Bot use |
|---|---|---|
| `bot_members` | bot | The allowlist: `telegram_chat_id`, `display_name`, optional `user_id`, `joined_at` |
| `bot_notification_log` | bot | One row per assignment alert (delivered, attempts, last error) |
| `users` | API | Read, only to validate a mapping |
| `buildings` | API | Read (building picker) |
| `defects`, `defect_comments` | API | Read; `/report` inserts |
| `maintenance_jobs` | API | Read |

`defects.reporter_id` is nullable and a defect raised by an unmapped member carries
`bot_reporter_id` + `reporter_label` instead (a CHECK guarantees one reporter is always recorded).
`bot_reporter_id` has no foreign key, so the two applications migrate independently.

**The contract is enforced by tests**: `tests/test_contracts.py` fails if a column or enum label the
bot maps disappears from the database, if the vendored catalog drifts from `Backend/fm/catalog.py`,
or if any bot module imports Flask or `Backend/`. (The catalog-drift test is skipped when the BMS repo's `Backend/` is not checked out alongside.)

---

## Access: who may use the bot

Access is an **allowlist of Telegram IDs** in `bot_members`, managed from the command line. There are
no invite phrases, no codes and no self-service sign-up.

1. The new person sends `/start` to the bot. It replies with their Telegram ID and nothing else.
2. They pass the ID to an administrator, who runs on the bot's host:
   `python -m botapp.admin add 123456789 "Tina Tan"`
3. From then on `/start` shows the full menu.

Remove access with `python -m botapp.admin remove 123456789`; it takes effect on their next message.
The first person is added the same way: message the bot, read your ID, run `add` on the host.

### What is a "mapped member"?

A member whose `bot_members.user_id` points at a row in the web app's **`users`** table. That is
the only thing "mapped" means.

It exists because "assigned to me" in the platform means assigned to a **web account**:
`defects.assigned_technician_id` and `maintenance_jobs.assigned_technician_id` are `users.id` values,
and the bot has no other way to know that a Telegram chat *is* that person.

| | Mapped | Not mapped |
|---|---|---|
| Sees all defects and maintenance, can `/report`, `/calendar` | yes | yes |
| `/myjobs`, `/mydefects` | their assignments | empty (never "everything") |
| Assignment alerts | yes | no |

Map someone when adding them, or later:

```bash
python -m botapp.admin add 123456789 "Tina Tan" --web-user 7     # 7 = users.id
python -m botapp.admin link-user 123456789 7                      # map later
python -m botapp.admin link-user 123456789 --clear                # unmap
python -m botapp.admin import-links                               # map everyone who used the old web link flow
```
Find the web user's ID in the web app's user list, or `SELECT id, name FROM users;`.
`/whoami` tells a member whether they are mapped.

---

## Demos: what it looks like in Telegram

These are **generated** by `tools/render_demos.py` from the real handlers and formatters against a
seeded database, so they match the code. `you ▸` is what the person types or taps; boxes are the
bot's messages; `[ ... ]` are inline buttons. Re-run with `--write` after changing any message.

<!-- demos:start -->

#### Someone who is not on the allowlist

They learn only their own Telegram ID, so they can ask an administrator to add them. No data is shown.

```text
you ▸ /start
  ┌─ bot ────────────────────────────────────────
  │ 🔒 You are not authorised to use this bot.
  │ 
  │ Send this ID to an administrator and ask to be added:
  │ 900001
  └────────────────────────────────────────────────────
you ▸ /service
  ┌─ bot ────────────────────────────────────────
  │ 🔒 You are not authorised to use this bot.
  │ 
  │ Send this ID to an administrator and ask to be added:
  │ 900001
  └────────────────────────────────────────────────────
```

#### /start and /help

The command list, generated from the trade catalog.

```text
you ▸ /start
  ┌─ bot ────────────────────────────────────────
  │ 👷 Building & Facilities Management
  │ 
  │ Maintenance schedules and building defects, in one place.
  │ Signed in as Alex Admin.
  │ 
  │ Maintenance
  │ /service — routine maintenance dashboard
  │ 
  │ Drill into a trade, e.g. /acmv for ACMV jobs:
  │ /acmv — ❄️ ACMV servicing
  │ /lift — 🛗 Lift and escalator servicing
  │ /electrical — ⚡ Electrical maintenance
  │ /fire — 🧯 Fire protection services
  │ /plumbing — 🚰 Plumbing and sanitary services
  │ 
  │ Defects
  │ /defects — open defects you can see
  │ /report — report a new defect
  │ 
  │ Yours
  │ /myjobs — maintenance jobs assigned to you
  │ /mydefects — defects assigned to you
  │ 
  │ Schedule
  │ /calendar — agenda: week (default), today, month, overdue
  │ /today — what is scheduled today
  │ /overdue — maintenance past its due date
  │ 
  │ Other
  │ /pending — all maintenance jobs not yet completed
  │ /refresh — reload the latest data
  │ /whoami — show who you are signed in as
  │ /help — show this menu again
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /whoami

A member with no web account link.

```text
you ▸ /whoami
  ┌─ bot ────────────────────────────────────────
  │ 👤 Your membership
  │ 
  │    Name: Alex Admin
  │    Access: full
  │    Web account: not linked — /myjobs and /mydefects will be empty
  │ 
  │ Access is managed by your administrator.
  └────────────────────────────────────────────────────
```

#### /whoami (a mapped member)

This person is linked to a web-app account, so "assigned to me" works.

```text
you ▸ /whoami
  ┌─ bot ────────────────────────────────────────
  │ 👤 Your membership
  │ 
  │    Name: Tara Tech
  │    Access: full
  │    Web account: linked (#171) — /myjobs, /mydefects and
  │    assignment alerts work
  │ 
  │ Access is managed by your administrator.
  └────────────────────────────────────────────────────
```

#### /service

One screen: every trade with its status counts.

```text
you ▸ /service
  ┌─ bot ────────────────────────────────────────
  │ 📋 Routine Maintenance Dashboard
  │ 
  │ ❄️ ACMV  (/acmv)
  │    ⚪ 1   🟡 3   🟢 1   — 5 job(s)
  │ 
  │ 🛗 Lift & Escalator  (/lift)
  │    ⚪ 1   🟡 1   🟢 1   — 3 job(s)
  │ 
  │ ⚡ Electrical  (/electrical)
  │    ⚪ 3   🟡 1   🟢 1   — 5 job(s)
  │ 
  │ 🧯 Fire Protection  (/fire)
  │    ⚪ 2   🟡 2   🟢 1   — 5 job(s)
  │ 
  │ 🚰 Plumbing & Sanitary  (/plumbing)
  │    ⚪ 1   🟡 1   🟢 1   — 3 job(s)
  │ 
  │ ──────────────
  │ Total: 21 job(s) · 5 completed
  │ 
  │ ⚪ Yet to start  🟡 In progress  🟢 Completed
  │ Tap a category command above for full details.
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /acmv  (also /lift /electrical /fire /plumbing)

Unfinished work first. Commands are generated from the catalog.

```text
you ▸ /acmv
  ┌─ bot ────────────────────────────────────────
  │ ❄️ ACMV — Routine Maintenance
  │ 
  │ 🟡 AHU filter replacement  ACMV-001
  │    📍 Location: Level 3 Plant Room
  │    🏢 Building: Tower A
  │    🔧 Type: Preventive maintenance
  │    📊 Status: In Progress
  │    🗓 Est. completion: Week 1 January 2026
  │    🔁 Next job: Week 1 April 2026
  │ 
  │ 🟡 Cooling tower chemical dosing  ACMV-004
  │    📍 Location: Roof Level
  │    🏢 Building: Tower A
  │    🔧 Type: Preventive maintenance
  │    📊 Status: In Progress
  │    🗓 Est. completion: Week 3 January 2026
  │    🔁 Next job: Week 3 February 2026
  │ 
  │ 🟡 Replace chiller filters  ACMV-D01
  │    📍 Location: Level 3 Plant Room
  │    🏢 Building: Tower A
  │    🔧 Type: Preventive maintenance
  │    📊 Status: In Progress
  │    🗓 Est. completion: Week 4 October 2026
  │    🔁 Next job: Week 4 November 2026
  │ 
  │ ⚪ Chiller quarterly servicing  ACMV-002
  │    📍 Location: Basement 1 Chiller Plant
  │    🏢 Building: Tower B
  │    🔧 Type: Preventive maintenance
  │    📊 Status: Yet to Start
  │    🗓 Est. completion: Week 2 January 2026
  │    🔁 Next job: Week 2 April 2026
  │ 
  │ 🟢 FCU water leak rectification  ACMV-003
  │    📍 Location: Level 7 Office
  │    🏢 Building: Annexe Block
  │    🔧 Type: Corrective maintenance
  │    📊 Status: Completed
  │    🗓 Est. completion: Week 4 December 2025
  │    🔁 Next job: -
  │ 
  │ ──────────────
  │ 5 job(s) in this category · /service for the full dashboard
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### Tapping a button

Buttons edit the message in place instead of adding a new one.

```text
you ▸ (taps 🛗 Lift)
  ┌─ bot (edited in place) ────────────────────────────────────────
  │ 🛗 LIFT & ESCALATOR — Routine Maintenance
  │ 
  │ 🟡 Escalator step chain adjustment  LFT-002
  │    📍 Location: Level 1 to Level 2
  │    🏢 Building: Annexe Block
  │    🔧 Type: Corrective maintenance
  │    📊 Status: In Progress
  │    🗓 Est. completion: Week 2 January 2026
  │    🔁 Next job: -
  │ 
  │ ⚪ Annual load test - service lift  LFT-003
  │    📍 Location: Tower B Service Core
  │    🏢 Building: Tower A
  │    🔧 Type: Preventive maintenance
  │    📊 Status: Yet to Start
  │    🗓 Est. completion: Week 4 February 2026
  │    🔁 Next job: Week 4 February 2027
  │ 
  │ 🟢 Passenger lift No.1 monthly service  LFT-001
  │    📍 Location: Tower A Lobby
  │    🏢 Building: Tower B
  │    🔧 Type: Preventive maintenance
  │    📊 Status: Completed
  │    🗓 Est. completion: Week 1 January 2026
  │    🔁 Next job: Week 1 February 2026
  │ 
  │ ──────────────
  │ 3 job(s) in this category · /service for the full dashboard
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /pending

Every job that is not completed, across all trades.

```text
you ▸ /pending
  ┌─ bot ────────────────────────────────────────
  │ ⏳ Outstanding Jobs (all trades)
  │ 
  │ ❄️ ACMV
  │    🟡 AHU filter replacement — Level 3 Plant Room — due Week 1
  │    January 2026
  │    ⚪ Chiller quarterly servicing — Basement 1 Chiller Plant — due
  │    Week 2 January 2026
  │    🟡 Cooling tower chemical dosing — Roof Level — due Week 3
  │    January 2026
  │    🟡 Replace chiller filters — Level 3 Plant Room — due Week 4
  │    October 2026
  │ 
  │ 🛗 Lift & Escalator
  │    🟡 Escalator step chain adjustment — Level 1 to Level 2 — due
  │    Week 2 January 2026
  │    ⚪ Annual load test - service lift — Tower B Service Core — due
  │    Week 4 February 2026
  │ 
  │ ⚡ Electrical
  │    🟡 Emergency lighting battery test — All Staircases — due Week
  │    2 January 2026
  │    ⚪ LV switchboard thermal scanning — Main Electrical Room — due
  │    Week 3 January 2026
  │    ⚪ Generator load bank test — Genset Room — due Week 1 March
  │    2026
  │    ⚪ Thermal scan of main switchboard — MSB room — due Week 4
  │    October 2026
  │ 
  │ 🧯 Fire Protection
  │    🟡 Sprinkler head inspection — Level 1 to Level 10 — due Week 2
  │    January 2026
  │    🟡 Fire pump weekly churn test — Pump Room B1 — due Week 2
  │    January 2026
  │    ⚪ Hose reel pressure rectification — Level 4 Riser — due Week
  │    3 January 2026
  │    ⚪ Sprinkler flow test — Basement 1 — due Week 1 November 2026
  │ 
  │ 🚰 Plumbing & Sanitary
  │    🟡 Booster pump servicing — Basement Pump Room — due Week 3
  │    January 2026
  │    ⚪ Water tank cleaning and disinfection — Roof Tank Room — due
  │    Week 4 January 2026
  │ 
  │ 17 outstanding job(s) in total.
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /myjobs  (mapped member)

Maintenance assigned to the linked web account.

```text
you ▸ /myjobs
  ┌─ bot ────────────────────────────────────────
  │ 🔧 Your Maintenance Jobs
  │ 
  │ 🟡 AHU filter replacement  ACMV-001
  │    📍 Location: Level 3 Plant Room
  │    🏢 Building: Tower A
  │    🔧 Type: Preventive maintenance
  │    📊 Status: In Progress
  │    🗓 Est. completion: Week 1 January 2026
  │    🔁 Next job: Week 1 April 2026
  │ 
  │ 🟡 Escalator step chain adjustment  LFT-002
  │    📍 Location: Level 1 to Level 2
  │    🏢 Building: Annexe Block
  │    🔧 Type: Corrective maintenance
  │    📊 Status: In Progress
  │    🗓 Est. completion: Week 2 January 2026
  │    🔁 Next job: -
  │ 
  │ ⚪ Water tank cleaning and disinfection  PLB-001
  │    📍 Location: Roof Tank Room
  │    🏢 Building: Tower A
  │    🔧 Type: Preventive maintenance
  │    📊 Status: Yet to Start
  │    🗓 Est. completion: Week 4 January 2026
  │    🔁 Next job: Week 4 July 2026
  │ 
  │ ⚪ Generator load bank test  ELE-004
  │    📍 Location: Genset Room
  │    🏢 Building: Tower B
  │    🔧 Type: Preventive maintenance
  │    📊 Status: Yet to Start
  │    🗓 Est. completion: Week 1 March 2026
  │    🔁 Next job: Week 1 September 2026
  │ 
  │ 🟡 Replace chiller filters  ACMV-D01
  │    📍 Location: Level 3 Plant Room
  │    🏢 Building: Tower A
  │    🔧 Type: Preventive maintenance
  │    📊 Status: In Progress
  │    🗓 Est. completion: Week 4 October 2026
  │    🔁 Next job: Week 4 November 2026
  │ 
  │ 5 job(s) assigned to you.
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```
#### /myjobs  (member with no web link)

Nothing can be assigned to them, so the list is empty. It is never "everything".

```text
you ▸ /myjobs
  ┌─ bot ────────────────────────────────────────
  │ ✅ No maintenance jobs are assigned to you.
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /defects

Open defects, newest first, up to 25.

```text
you ▸ /defects
  ┌─ bot ────────────────────────────────────────
  │ 🛠 Open Defects
  │ 
  │ 🟡 Carpark light out  #188
  │    📊 Status: Ongoing
  │    🔹 Priority: low
  │    🏢 Building: Annexe Block
  │    👷 Technician: Tara Tech
  │    🗓 Reported: 28 Oct 2026
  │ 
  │ 🟣 Toilet extract fan noisy  #187
  │    📊 Status: Reviewed
  │    🔸 Priority: medium
  │    🏢 Building: Tower B
  │    🗓 Reported: 28 Oct 2026
  │ 
  │ 🔴 Cracked lobby tile  #186
  │    📊 Status: Open
  │    🔺 Priority: high
  │    🏢 Building: Tower A
  │    🗓 Reported: 28 Oct 2026
  │ 
  │ 3 defect(s).
  └────────────────────────────────────────────────────
```

#### /mydefects

Defects assigned to the linked web account.

```text
you ▸ /mydefects
  ┌─ bot ────────────────────────────────────────
  │ 🛠 Your Assigned Defects
  │ 
  │ 🟡 Carpark light out  #188
  │    📊 Status: Ongoing
  │    🔹 Priority: low
  │    🏢 Building: Annexe Block
  │    👷 Technician: Tara Tech
  │    🗓 Reported: 28 Oct 2026
  │ 
  │ 1 defect(s).
  └────────────────────────────────────────────────────
```

#### /report

A guided conversation. Send /cancel at any step to stop.

```text
you ▸ /report
  ┌─ bot ────────────────────────────────────────
  │ 📝 New defect  (1 of 5)
  │ 
  │ What is the problem, in a few words?
  │ e.g. "Cracked lobby tile"
  │ 
  │ Send /cancel at any point to stop.
  └────────────────────────────────────────────────────
you ▸ Cracked lobby tile
  ┌─ bot ────────────────────────────────────────
  │ 📝 New defect  (2 of 5)
  │ 
  │ Now describe it. What is wrong, and where exactly?
  └────────────────────────────────────────────────────
you ▸ Tile near the lift lobby has split and is a trip hazard
  ┌─ bot ────────────────────────────────────────
  │ 📝 New defect  (3 of 5)
  │ 
  │ Which building?
  └────────────────────────────────────────────────────
  [ Annexe Block ]
  [ Tower A ]
  [ Tower B ]
  [ ✖️ Cancel ]
you ▸ (taps "Tower A")
  ┌─ bot (edited in place) ────────────────────────────────────────
  │ 📝 New defect  (4 of 5)
  │ 
  │ How urgent is it?
  └────────────────────────────────────────────────────
  [ 🔹 Low ]  [ 🔸 Medium ]  [ 🔺 High ]
  [ ✖️ Cancel ]
you ▸ (taps 🔺 High)
  ┌─ bot (edited in place) ────────────────────────────────────────
  │ 📝 New defect  (5 of 5)
  │ 
  │ Send a photo if you have one, or /skip to finish without.
  └────────────────────────────────────────────────────
you ▸ /skip
  ┌─ bot ────────────────────────────────────────
  │ 🔍 Ready to submit
  │ 
  │    Title: Cracked lobby tile
  │    Building: Tower A
  │    Priority: high
  │    Photo: no
  │ 
  │ Tile near the lift lobby has split and is a trip hazard
  │ 
  │ Send /confirm to log it, or /cancel to discard.
  └────────────────────────────────────────────────────
you ▸ /confirm
  ┌─ bot ────────────────────────────────────────
  │ ✅ Defect reported.
  │ 
  │ 🔴 Cracked lobby tile  #319
  │    📊 Status: Open
  │    🔺 Priority: high
  │    🏢 Building: Tower A
  │    🗓 Reported: 28 Oct 2026
  │ 
  │ It will be reviewed shortly.
  └────────────────────────────────────────────────────
```

#### /calendar

The next 7 days, grouped by day. A line at the bottom flags overdue work.

```text
you ▸ /calendar
  ┌─ bot ────────────────────────────────────────
  │ 📅 Next 7 days
  │ 
  │ Wed 28 Oct 2026 (today)
  │    🟡 Replace chiller filters — Level 3 Plant Room ACMV-D01 · due
  │ 
  │ Thu 29 Oct 2026 (tomorrow)
  │    ⚪ Quarterly lift inspection — Block A lifts LIFT-D01 · due
  │ 
  │ Fri 30 Oct 2026
  │    🟢 Flush water tanks — Roof tank PLMB-D01 · next service
  │ 
  │ Sun 01 Nov 2026
  │    ⚪ Sprinkler flow test — Basement 1 FIRE-D01 · due
  │ 
  │ ⚠️ 14 overdue — see /overdue
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /today

Shortcut for `/calendar today`.

```text
you ▸ /today
  ┌─ bot ────────────────────────────────────────
  │ 📅 Today
  │ 
  │ Wed 28 Oct 2026 (today)
  │    🟡 Replace chiller filters — Level 3 Plant Room ACMV-D01 · due
  │ 
  │ ⚠️ 14 overdue — see /overdue
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /calendar month

The next 30 days. Also `week` (default), `today`, `overdue`.

```text
you ▸ /calendar month
  ┌─ bot ────────────────────────────────────────
  │ 📅 Next 30 days
  │ 
  │ Wed 28 Oct 2026 (today)
  │    🟡 Replace chiller filters — Level 3 Plant Room ACMV-D01 · due
  │ 
  │ Thu 29 Oct 2026 (tomorrow)
  │    ⚪ Quarterly lift inspection — Block A lifts LIFT-D01 · due
  │ 
  │ Fri 30 Oct 2026
  │    🟢 Flush water tanks — Roof tank PLMB-D01 · next service
  │ 
  │ Sun 01 Nov 2026
  │    ⚪ Sprinkler flow test — Basement 1 FIRE-D01 · due
  │ 
  │ ⚠️ 14 overdue — see /overdue
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /overdue

Unfinished jobs past their due date, oldest first.

```text
you ▸ /overdue
  ┌─ bot ────────────────────────────────────────
  │ 📅 Overdue maintenance
  │ 
  │ Thu 01 Jan 2026 (300 days overdue)
  │    🟡 AHU filter replacement — Level 3 Plant Room ACMV-001 ·
  │    overdue
  │ 
  │ Thu 08 Jan 2026 (293 days overdue)
  │    ⚪ Chiller quarterly servicing — Basement 1 Chiller Plant
  │    ACMV-002 · overdue
  │    🟡 Emergency lighting battery test — All Staircases ELE-002 ·
  │    overdue
  │    🟡 Sprinkler head inspection — Level 1 to Level 10 FIR-001 ·
  │    overdue
  │    🟡 Fire pump weekly churn test — Pump Room B1 FIR-004 · overdue
  │    🟡 Escalator step chain adjustment — Level 1 to Level 2 LFT-002
  │    · overdue
  │ 
  │ Thu 15 Jan 2026 (286 days overdue)
  │    🟡 Cooling tower chemical dosing — Roof Level ACMV-004 · overdue
  │    ⚪ LV switchboard thermal scanning — Main Electrical Room
  │    ELE-001 · overdue
  │    ⚪ Hose reel pressure rectification — Level 4 Riser FIR-003 ·
  │    overdue
  │    🟡 Booster pump servicing — Basement Pump Room PLB-003 · overdue
  │ 
  │ Thu 22 Jan 2026 (279 days overdue)
  │    ⚪ Water tank cleaning and disinfection — Roof Tank Room
  │    PLB-001 · overdue
  │ 
  │ Sun 22 Feb 2026 (248 days overdue)
  │    ⚪ Annual load test - service lift — Tower B Service Core
  │    LFT-003 · overdue
  │ 
  │ Sun 01 Mar 2026 (241 days overdue)
  │    ⚪ Generator load bank test — Genset Room ELE-004 · overdue
  │ 
  │ Sun 25 Oct 2026 (3 days overdue)
  │    ⚪ Thermal scan of main switchboard — MSB room ELEC-D01 ·
  │    overdue
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /calendar with an unknown option

Anything other than today, week, month or overdue.

```text
you ▸ /calendar fortnight
  ┌─ bot ────────────────────────────────────────
  │ Use /calendar today, week, month or overdue.
  └────────────────────────────────────────────────────
```

#### Assignment alert (pushed by the bot)

Sent to a mapped member when a defect is assigned to their web account. Checked every 30 s, retried on failure.

```text
  ┌─ bot ────────────────────────────────────────
  │ 🔔 A defect has been assigned to you.
  │ 
  │ 🟡 Carpark light out  #188
  │    📊 Status: Ongoing
  │    🔹 Priority: low
  │    🏢 Building: Annexe Block
  │    👷 Technician: Tara Tech
  │    🗓 Reported: 28 Oct 2026
  │ 
  │ Three fittings out in basement 2, bay 40-50 is dark.
  │ 
  │ Use /mydefects to see everything assigned to you.
  └────────────────────────────────────────────────────
```

#### Anything the bot does not understand

It points back at /start, never silence.

```text
you ▸ hello?
  ┌─ bot ────────────────────────────────────────
  │ 🤔 I didn't recognise that. Send /start to see what I can do.
  └────────────────────────────────────────────────────
```

<!-- demos:end -->

---

## Setup

Prerequisites: Python 3.11+, PostgreSQL that already carries the **web API's migrations**
(`cd Backend && flask db upgrade`), and a bot token from @BotFather (`/newbot`).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                     # fill in TELEGRAM_BOT_TOKEN and DATABASE_URL
alembic -c migrations/alembic.ini upgrade head          # the bot's own tables
python -m botapp.admin add <YOUR_TELEGRAM_ID> "Your Name"
python -m botapp.main
```

Docker: `docker build -t fm-bot . && docker run --env-file .env fm-bot`. The image applies the bot's migrations
and starts the bot; if the API has not created the shared tables yet it exits and `restart` retries.

| Variable (`.env`, never committed) | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather; shape checked before start |
| `DATABASE_URL` | The **same** PostgreSQL database as the web API |
| `TZ` | Optional, default `UTC`. Decides what "today" means in `/calendar` |

No `SECRET_KEY`: the bot signs nothing.

## Administration

| Command | Does |
|---|---|
| `add CHAT_ID "Name" [--web-user ID]` | Allow a person (optionally map to a web account) |
| `remove CHAT_ID` | Remove access |
| `members` | List who is allowed |
| `link-user CHAT_ID USER_ID` / `--clear` | Map / unmap a web account |
| `import-links` | Allow everyone who linked through the old web flow, mapped |

Run as `python -m botapp.admin <command>` from the repository root.

## Tests

```bash
createdb bdms_test   # then run the BMS repo's `flask db upgrade` against it
DATABASE_URL=postgresql:///bdms_test alembic -c migrations/alembic.ini upgrade head
TEST_DATABASE_URL=postgresql:///bdms_test pytest
```
Each test runs in a rolled-back transaction. They need PostgreSQL (native enums), not SQLite.

## Troubleshooting

| Symptom | Cause |
|---|---|
| "CANNOT START - TOKEN PROBLEM" | Token missing or mis-copied |
| "TELEGRAM REJECTED YOUR TOKEN" | Revoked or wrong; get it from @BotFather → `/mybots` |
| "CANNOT START - DATABASE PROBLEM … missing table(s)" | Run the API's `flask db upgrade`, then the bot's alembic |
| Someone sees "not authorised" | They are not in `bot_members`; `add` their ID |
| `/myjobs` empty for someone with jobs | They are not mapped to a web account (`link-user`) |
| Two bots fighting | One process per token only |

## Known limitations

* **Messages sent while the bot is offline are discarded** (`drop_pending_updates=True`).
* An unfinished `/report` has no timeout; a restart drops it silently.
* Lists are capped (defects 25, buildings 50, calendar 60 entries). Defect status cannot be changed from chat.
* Photos: the largest Telegram size at or under 400,000 bytes, otherwise the smallest. No resizing.
* The allowlist is only as safe as the Telegram ID you add, and a removed person keeps any chat history already delivered to them.
* Unmapped people cannot be assigned work from the website.

## Suggested improvements for intra-day reporting

Not built. Because there are no roles, anything that "notifies" goes to **all members**.

1. **Keep messages sent while the bot was down** and answer them on restart.
2. **Scheduled digests** (timezone-aware): morning brief, midday check, end-of-day wrap, sent to everyone.
3. **Event alerts to all members:** a high-priority defect raised, a defect unassigned or ageing past a threshold, a job becoming overdue.
4. **Act from chat:** set Ongoing/Done, attach an after-photo and a note.
5. **More views:** `/summary [building]`, `/defect <id>` with its comment trail, Next/Prev paging.
6. **Photos:** real resize/compress and several photos per defect.
7. **Audit log** of who did what, and a heartbeat that warns if the bot has been silent.
8. **Group delivery:** post digests to a Telegram group instead of individuals.
9. **Webhook mode** once there is a stable HTTPS endpoint.
