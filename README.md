# FM Control: Telegram bot + master-control website

A facilities-management system with **two front ends on one PostgreSQL database**:

* a **guided Telegram bot** for everyone (query what is scheduled, report a defect), and
* a **website for master control** to monitor the data, approve people, manage equipment types and import CSVs.

The bot never imports the web framework and the website never calls the bot; they share the database and the
code in `core/`. Stop either and the other keeps working.

Contents: [Capabilities](#capabilities) · [Architecture](#system-architecture) · [Data](#data-three-stores) ·
[Access flow](#access-flow) · [Guided flows](#guided-telegram-flows) · [Website](#the-website) ·
[Demos](#demos-what-it-looks-like-in-telegram) · [Setup](#setup) · [Administration](#administration-cli) ·
[Tests](#tests) · [Limits](#known-limitations) · [Ideas](#ideas-not-built)

---

## Capabilities

| # | Capability | Where | Who |
|---|---|---|---|
| 1 | **Request access once; master control approves; the decision is remembered** | Telegram, website | anyone / master control |
| 2 | **Event query**: ask when, see what is scheduled, grouped by equipment type | `/events`, menu button | members |
| 3 | **Defect reporting, match-first**: describe it; the bot searches scheduled items and earlier reports for the closest matches; records against a scheduled item, adds to an earlier report, or creates a fresh one | `/report`, menu button | members |
| 4 | Equipment types are **editable with add-ons** (ACMV, Lift, Electrical, Fire, Plumbing, **Event**, and your own) | website, CLI | master control |
| 5 | Scheduled items and events in **one store**, imported from a CSV | website, CLI | master control |
| 6 | Dashboards and tables over scheduled items, defect reports and access | website | master control |
| 7 | Maintenance views: dashboard, per-type lists, outstanding, my jobs/defects, calendar, overdue | `/service` `/acmv` `/pending` `/myjobs` `/defects` `/calendar` `/overdue` | members |
| 8 | Assignment alerts to people linked to a web account (retried on failure) | Telegram | linked members |
| 9 | Guided flows with Back / Cancel on every step, a 30-minute timeout, typed dates ("25 Nov 14:30") | Telegram | members |

**Two tiers.** *End user*: Telegram only. *Master control*: Telegram **and** the website, and the people who approve requests.

---

## System architecture

```
                       Telegram                                   Browser
                          ▲                                          ▲
                          │ long polling                             │ HTTPS
              ┌───────────┴────────────┐                 ┌───────────┴────────────┐
              │  bot   (botapp/)       │                 │  web   (web/)          │
              │  guided flows          │                 │  React + Tailwind      │
              │  alert + access poller │                 │  nginx  /api ──────────┼───┐
              └───────────┬────────────┘                 └────────────────────────┘   │
                          │                                                           ▼
                          │                                           ┌───────────────────────────┐
                          │                                           │  api   (api/)  Flask      │
                          │                                           │  JWT, master control only │
                          │                                           └─────────────┬─────────────┘
                          ▼                                                         ▼
              ┌──────────────────────────────────────────────────────────────────────────────────┐
              │  core/   models · services · similarity · access rules · importer · equipment    │
              │          (plain SQLAlchemy, no web framework; one Alembic chain: migrations/)    │
              └───────────────────────────────────────┬──────────────────────────────────────────┘
                                                      ▼
                                              PostgreSQL  (one database)
```

| Part | Folder | Runs as | Depends on |
|---|---|---|---|
| Bot | `botapp/` | one process (long polling, no inbound port) | `core/` |
| API | `api/` | gunicorn | `core/`, Flask |
| Website | `web/` | static files behind nginx, which proxies `/api` | the API |
| Shared logic | `core/` | imported, not run | SQLAlchemy |
| Schema | `migrations/` | one-shot `migrate` job | |

Rules that keep it honest (checked by tests): the bot imports no Flask; the website and bot never call each other;
a decision made in the website reaches the person via the bot's 30-second poller; every schema change is a migration.

### Request path in the bot
1. Telegram delivers the update; `@require_member` checks the chat's access state.
2. The handler calls `run_db(fn)`: a worker thread opens a **fresh session**, does the query *and* the rendering,
   returns a finished string, and closes the session (never return model instances).
3. `ui.reply()` sends it (splits long messages, edits in place on button taps).

### Code map
```
core/        models.py db.py config.py  access.py  equipment.py  importer.py  similarity.py  when.py
             services/{defect,maintenance,report}_service.py   fm/{catalog,formatters,date_utils}.py
botapp/      main.py  auth.py  admin.py  notifications.py  ui.py  handlers/{account,access,browse,defects,guided}.py
api/         app.py  auth.py  routes/{auth,dashboard,scheduled,defects,access,equipment}.py
web/         src/{App.jsx,pages/*,components/*}   (Vite 6 · React 18 · Tailwind 4 · BMS design tokens)
migrations/  versions/0000 … 0008 (one chain, table alembic_version_bot)
tests/       pytest against real PostgreSQL; harness.py drives the real Telegram dispatcher with a fake bot
tools/       render_demos.py  (regenerates the demos below from the real bot)
```

---

## Data: three stores

| Store | Table | What it holds |
|---|---|---|
| **Scheduled items & events** (merged) | `maintenance_jobs` | a start-to-end timeline, an equipment type, location, status. **Event is just another equipment type.** Loaded from a CSV. |
| **Defect reports** | `defects` (+ `defect_comments`) | `kind` = *scheduled* (matched a scheduled item) or *unscheduled*; **one** occurrence time (no end); location; specific equipment; the scheduled item it matched; the report it was added to. Starts empty. |
| **Access** | `bot_members` | one row per person who ever asked: tier, status, who decided and when, optional link to a web account. |

Supporting tables: `equipment_types` (editable list), `users` (website logins, bcrypt), `buildings`,
`bot_notification_log` (alerts already sent). The shared web-app tables keep their original names, so an existing BMS
database upgrades in place; an empty database gets them from the baseline migration.

---

## Access flow

```
(no record) ──ask──▶ pending ──approve──▶ approved ◀──▶ revoked
                        └──deny──▶ denied ──reconsider──▶ pending
```

* **Ask once.** A stranger sees only a *Request access* button. The request is stored; asking again notifies nobody twice.
* **Decide in Telegram or the website.** Every master control member gets *Approve / Approve as master / Deny* buttons;
  the website's Access page does the same. The person is told by the bot either way.
* **Remembered.** Approved people never ask again. A denied or revoked person cannot re-ask; master control can *reconsider*.
* **Safety.** Only master control decides. The **last** master control can never be revoked or demoted.
* **Website login** is for master control only: an email + password in `users`, *and* an approved master control member
  linked to it. Every request re-checks the member, so revoking someone cuts them off on their next click.

### What is a "linked" (mapped) member?
A member whose `bot_members.user_id` points at a row in the web app's `users` table. It matters only because "assigned to me"
means assigned to a **web account** (`defects.assigned_technician_id`, `maintenance_jobs.assigned_technician_id` are `users.id`):

| | Linked | Not linked |
|---|---|---|
| Everything else in the bot | yes | yes |
| `/myjobs`, `/mydefects`, assignment alerts | their assignments | empty (never "everything") |
| Website sign-in (master control) | required | not possible |

Link someone on the Access page, or `python -m botapp.admin link-user CHAT_ID USER_ID`.

---

## Guided Telegram flows

"Guided" means the bot leads: every step is a prompt with an example and buttons; nobody needs to know a command.
Back and Cancel on every step, `/cancel` anywhere, 30-minute timeout.

**Event query** (`/events`): *When?* → Today / Tomorrow / Next 7 days / type a date or range → the scheduled items in that
period, grouped by equipment type (timeline-aware: an item that spans the period is included).

**Defect reporting** (`/report`): *When did it happen?* → *Which equipment type?* → *Where?* → *What is the issue?* → then
the bot **searches both stores** and offers the closest records one at a time, "Is this it?":

| You say… | Result |
|---|---|
| Yes, a **scheduled item** | the report is recorded against it (`kind = scheduled`) |
| Yes, an **earlier unscheduled report** | the sighting is added to that report instead of creating a duplicate |
| None of these / nothing similar | a **fresh unscheduled report**: specific equipment (optional), priority, optional photo, confirm |

**How "similar" is decided** (`core/similarity.py`, deliberately plain and explainable; the reasons are shown to the user):
only records of the chosen equipment type are considered, then `score = 100 × (0.25·time + 0.35·location + 0.40·issue)`.
*time*: inside the scheduled window (± a day) = 1, fading to 0 over 7 days (earlier reports: 14 days);
*location* / *issue*: word overlap blended with a fuzzy ratio. Records under 40 are not suggested. Matches are ranked
by score across both stores; a scheduled item wins a near tie (within 5 points).

---

## The website

Master control only (Vite · React · Tailwind, the BMS design tokens and conventions).

| Page | Does |
|---|---|
| Dashboard | counts across the three stores; per-equipment-type table |
| Scheduled & events | filter by type (incl. Event), status, dates, search; paging; **CSV import** with a *check first* dry run and per-line skip reasons |
| Defect reports | filter by kind/type/status; detail with matched scheduled item, reports added to it, history |
| Access | pending requests (Approve / Approve as master / Deny), tier, link a web account, revoke, reconsider |
| Equipment types | add, rename, change emoji/description, enable/disable |

---

## Demos: what it looks like in Telegram

These are **generated** by `tools/render_demos.py`, which drives the real bot (same handlers, conversations and buttons) with a
fake Telegram against demo data. `you ▸` is what the person types or taps; boxes are the bot's messages; `[ … ]` are buttons.
Regenerate with `--write` after changing any message.

<!-- demos:start -->

#### Asking for access (once)

Someone who is not approved sees no data, only a button. After they ask, the bot remembers the request: asking again does not notify anyone twice.

```text
you ▸ /start
  ┌─ bot ───────────────────────────────────────────────
  │ 🔒 You do not have access to this bot yet.
  │ 
  │ Tap the button below to ask master control for access. You only
  │    need to do this once.
  └────────────────────────────────────────────────────
  [ 🙋 Request access ]
you ▸ (taps Request access)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 📨 Request sent.
  │ 
  │ Master control has been told. You will get a message here when
  │    it is decided. You do not need to ask again.
  └────────────────────────────────────────────────────
  ┌─ bot → Alex ────────────────────────────────────────
  │ 🔔 Access request
  │ 
  │ Sam (@tester) would like to use the bot.
  │ Telegram ID: 5003
  └────────────────────────────────────────────────────
  [ ✅ Approve ]  [ ⭐ Approve as master ]
  [ ❌ Deny ]
you ▸ /service
  ┌─ bot ───────────────────────────────────────────────
  │ ⏳ Your request is waiting for approval.
  │ 
  │ Master control has been told. You will get a message here as
  │    soon as it is decided. You do not need to ask again.
  └────────────────────────────────────────────────────
```

#### Master control approves

Approve, Approve as master, or Deny, in Telegram (or on the website). The person is told immediately and never has to ask again.

```text
· Sam has just asked for access; master control received this message:
  ┌─ bot → Alex ────────────────────────────────────────
  │ 🔔 Access request
  │ 
  │ Sam (@tester) would like to use the bot.
  │ Telegram ID: 5003
  └────────────────────────────────────────────────────
  [ ✅ Approve ]  [ ⭐ Approve as master ]
  [ ❌ Deny ]
Alex ▸ (taps Approve)
  ┌─ bot → Alex (edited in place) ──────────────────────
  │ ✅ Sam approved by Alex Admin.
  └────────────────────────────────────────────────────
  ┌─ bot → Sam ─────────────────────────────────────────
  │ ✅ You have been approved.
  │ 
  │ Send /start to begin.
  └────────────────────────────────────────────────────
Sam ▸ /start
  ┌─ bot → Sam ─────────────────────────────────────────
  │ 👷 Building & Facilities Management
  │ 
  │ Maintenance schedules and building defects, in one place.
  │ Signed in as Sam.
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
  │ Guided  (the bot asks, you answer)
  │ /events — what is scheduled, and when
  │ /report — report a defect: it checks for a match first
  │ 
  │ Defects
  │ /defects — open defects you can see
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
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /start: the guided menu

The two guided flows lead every screen; the rest are shortcuts.

```text
you ▸ /start
  ┌─ bot ───────────────────────────────────────────────
  │ 👷 Building & Facilities Management
  │ 
  │ Maintenance schedules and building defects, in one place.
  │ Signed in as Tess Tan.
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
  │ Guided  (the bot asks, you answer)
  │ /events — what is scheduled, and when
  │ /report — report a defect: it checks for a match first
  │ 
  │ Defects
  │ /defects — open defects you can see
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
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /whoami

Tess has no web account; Priya is linked to one (so "assigned to me" works); Alex is master control.

```text
you ▸ /whoami
  ┌─ bot ───────────────────────────────────────────────
  │ 👤 Your membership
  │ 
  │    Name: Tess Tan
  │    Access: end user (Telegram)
  │    Web account: not linked — /myjobs and /mydefects will be
  │    empty
  │ 
  │ Access is managed by master control.
  └────────────────────────────────────────────────────
you ▸ /whoami
  ┌─ bot ───────────────────────────────────────────────
  │ 👤 Your membership
  │ 
  │    Name: Priya Nair
  │    Access: end user (Telegram)
  │    Web account: linked (#1451) — /myjobs, /mydefects and
  │    assignment alerts work
  │ 
  │ Access is managed by master control.
  └────────────────────────────────────────────────────
you ▸ /whoami
  ┌─ bot ───────────────────────────────────────────────
  │ 👤 Your membership
  │ 
  │    Name: Alex Admin
  │    Access: master control (Telegram and website)
  │    Web account: not linked — /myjobs and /mydefects will be
  │    empty
  │ 
  │ Access is managed by master control.
  └────────────────────────────────────────────────────
```

#### Event query: a quick option

The bot asks when; tap a quick option.

```text
you ▸ /events
  ┌─ bot ───────────────────────────────────────────────
  │ 📅 Event query
  │ 
  │ When do you want to look?
  │ Tap a quick option, or choose Pick a date to type one.
  └────────────────────────────────────────────────────
  [ 📅 Today ]  [ ➡️ Tomorrow ]
  [ 🗓 Next 7 days ]  [ ✏️ Pick a date ]
  [ ✖️ Cancel ]
you ▸ (taps Today)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 📅 Today · Mon 23 Nov 2026
  │ 
  │ ❄️ ACMV
  │    🟡 Replace chiller filters — Level 3 Plant Room ACMV-001
  │       🕒 Mon 23 Nov 09:00–17:00
  └────────────────────────────────────────────────────
  [ 📅 New query ]  [ 🛠 Report a defect ]
```

#### Event query: type a date

A day or a range ("25 Nov", "25/11 - 30/11"). It says so if it cannot read it. "Event" is an equipment type like ACMV.

```text
you ▸ (taps Event query)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 📅 Event query
  │ 
  │ When do you want to look?
  │ Tap a quick option, or choose Pick a date to type one.
  └────────────────────────────────────────────────────
  [ 📅 Today ]  [ ➡️ Tomorrow ]
  [ 🗓 Next 7 days ]  [ ✏️ Pick a date ]
  [ ✖️ Cancel ]
you ▸ (taps Pick a date)
  ┌─ bot (edited in place) ─────────────────────────────
  │ ✏️ Which date?
  │ 
  │ Type a day, or a range:
  │ 25 Nov   25/11/2026   25 Nov - 30 Nov
  └────────────────────────────────────────────────────
  [ ✖️ Cancel ]
you ▸ whenever
  ┌─ bot ───────────────────────────────────────────────
  │ 🤔 I could not read that date.
  │ 
  │ Try 25 Nov, 25/11/2026 or 25 Nov - 30 Nov.
  └────────────────────────────────────────────────────
  [ ✖️ Cancel ]
you ▸ 26 Nov
  ┌─ bot ───────────────────────────────────────────────
  │ 📅 Thu 26 Nov 2026
  │ 
  │ ▫️ Event
  │    ⚪ Annual fire drill — Main lobby EVT-001
  │       🕒 Thu 26 Nov 10:00–11:00
  └────────────────────────────────────────────────────
  [ 📅 New query ]  [ 🛠 Report a defect ]
```

#### Reporting: it matches a scheduled item

The bot asks, then looks through the scheduled and earlier unscheduled records and asks "Is this it?". A yes records the report against that scheduled item.

```text
you ▸ /report
  ┌─ bot ───────────────────────────────────────────────
  │ 🛠 Report a defect  (step 1 of 4)
  │ 
  │ 🕒 When did it happen?
  │ Tap an option, or type a date and time, e.g. 25 Nov 14:30 or
  │    14:30.
  └────────────────────────────────────────────────────
  [ ⚡ Just now ]  [ 1 hour ago ]
  [ 3 hours ago ]  [ Yesterday ]
  [ ✖️ Cancel ]
you ▸ (taps Just now)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 2 of 4)
  │ 
  │ 🔧 Which equipment type?
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps ACMV)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 3 of 4)
  │ 
  │ 📍 Where is it?
  │ Type the location, e.g. Level 3 Plant Room or Tower A lift
  │    lobby.
  └────────────────────────────────────────────────────
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ Level 3 plant room
  ┌─ bot ───────────────────────────────────────────────
  │ 🛠 Report a defect  (step 4 of 4)
  │ 
  │ 📝 What is the issue?
  │ Name the equipment and what is wrong, e.g. Chiller 2 making a
  │    loud grinding noise.
  └────────────────────────────────────────────────────
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ Chiller filters look blocked
  ┌─ bot ───────────────────────────────────────────────
  │ 🔎 Possible match 1 of 1  (86% similar)
  │ 
  │ 📌 Scheduled item
  │ ACMV-001: Replace chiller filters (Level 3 Plant Room)
  │ 
  │ Why: same equipment type · falls within its scheduled time ·
  │    similar location · similar description
  │ 
  │ Is this what you are reporting?
  └────────────────────────────────────────────────────
  [ ✅ Yes, this one ]
  [ 🆕 None of these ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Yes, this one)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🔍 Ready to submit
  │ 
  │    🕒 When: Mon 23 Nov 2026 06:37
  │    🔧 Equipment type: ❄️ ACMV
  │    📍 Location: Level 3 plant room
  │ 
  │ Chiller filters look blocked
  │ 
  │ Recorded against scheduled item ACMV-001: Replace chiller
  │    filters (Level 3 Plant Room).
  └────────────────────────────────────────────────────
  [ ✅ Submit ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Submit)
  ┌─ bot (edited in place) ─────────────────────────────
  │ ✅ Recorded against scheduled item ACMV-001.
  │ 
  │ 🛠 Chiller filters look blocked  #863
  │ 
  │ Thank you. It has been logged.
  └────────────────────────────────────────────────────
  [ 📅 New query ]  [ 🛠 Report a defect ]
```

#### Reporting: nothing similar, so a fresh report

When neither store has a close match the bot says so and guides a new report: specific equipment (optional), priority, optional photo, confirm.

```text
you ▸ /report
  ┌─ bot ───────────────────────────────────────────────
  │ 🛠 Report a defect  (step 1 of 4)
  │ 
  │ 🕒 When did it happen?
  │ Tap an option, or type a date and time, e.g. 25 Nov 14:30 or
  │    14:30.
  └────────────────────────────────────────────────────
  [ ⚡ Just now ]  [ 1 hour ago ]
  [ 3 hours ago ]  [ Yesterday ]
  [ ✖️ Cancel ]
you ▸ (taps 3 hours ago)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 2 of 4)
  │ 
  │ 🔧 Which equipment type?
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Plumbing)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 3 of 4)
  │ 
  │ 📍 Where is it?
  │ Type the location, e.g. Level 3 Plant Room or Tower A lift
  │    lobby.
  └────────────────────────────────────────────────────
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ Basement 2 pump room
  ┌─ bot ───────────────────────────────────────────────
  │ 🛠 Report a defect  (step 4 of 4)
  │ 
  │ 📝 What is the issue?
  │ Name the equipment and what is wrong, e.g. Chiller 2 making a
  │    loud grinding noise.
  └────────────────────────────────────────────────────
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ Water dripping from the main valve
  ┌─ bot ───────────────────────────────────────────────
  │ 🔎 I looked through the scheduled items and earlier reports and
  │    found nothing similar. Let's create a fresh report.
  └────────────────────────────────────────────────────
  ┌─ bot ───────────────────────────────────────────────
  │ 🆕 New report
  │ 
  │ ⚙️ Which specific equipment? (optional)
  │ e.g. Cooling tower 2 or Escalator E4.
  └────────────────────────────────────────────────────
  [ ⏭ Skip ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ Sump pump 3
  ┌─ bot ───────────────────────────────────────────────
  │ 🆕 New report
  │ 
  │ 🚦 How urgent is it?
  └────────────────────────────────────────────────────
  [ 🔹 Low ]  [ 🔸 Medium ]  [ 🔺 High ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps High)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🆕 New report
  │ 
  │ 📷 Send a photo if you have one.
  └────────────────────────────────────────────────────
  [ ⏭ Skip ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Skip)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🔍 Ready to submit
  │ 
  │    🕒 When: Mon 23 Nov 2026 03:37
  │    🔧 Equipment type: 🚰 Plumbing & Sanitary
  │    📍 Location: Basement 2 pump room
  │    ⚙️ Equipment: Sump pump 3
  │    🔺 Priority: high
  │    📷 Photo: no
  │ 
  │ Water dripping from the main valve
  │ 
  │ A new unscheduled report will be created.
  └────────────────────────────────────────────────────
  [ ✅ Submit ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Submit)
  ┌─ bot (edited in place) ─────────────────────────────
  │ ✅ New report created.
  │ 
  │ 🛠 Water dripping from the main valve  #864
  │ 
  │ Thank you. It has been logged.
  └────────────────────────────────────────────────────
  [ 📅 New query ]  [ 🛠 Report a defect ]
```

#### Reporting: it matches an earlier unscheduled report

Matches are offered most-similar first across both stores (a scheduled item wins a near tie). Saying yes adds the new sighting to it instead of creating a duplicate. "None of these" would create a fresh report.

```text
you ▸ /report
  ┌─ bot ───────────────────────────────────────────────
  │ 🛠 Report a defect  (step 1 of 4)
  │ 
  │ 🕒 When did it happen?
  │ Tap an option, or type a date and time, e.g. 25 Nov 14:30 or
  │    14:30.
  └────────────────────────────────────────────────────
  [ ⚡ Just now ]  [ 1 hour ago ]
  [ 3 hours ago ]  [ Yesterday ]
  [ ✖️ Cancel ]
you ▸ (taps Just now)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 2 of 4)
  │ 
  │ 🔧 Which equipment type?
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps ACMV)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 3 of 4)
  │ 
  │ 📍 Where is it?
  │ Type the location, e.g. Level 3 Plant Room or Tower A lift
  │    lobby.
  └────────────────────────────────────────────────────
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ cooling tower 2 on the roof
  ┌─ bot ───────────────────────────────────────────────
  │ 🛠 Report a defect  (step 4 of 4)
  │ 
  │ 📝 What is the issue?
  │ Name the equipment and what is wrong, e.g. Chiller 2 making a
  │    loud grinding noise.
  └────────────────────────────────────────────────────
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ Cooling tower fan grinding again
  ┌─ bot ───────────────────────────────────────────────
  │ 🔎 Possible match 1 of 2  (92% similar)
  │ 
  │ 🛠 Earlier unscheduled report
  │ #862: Cooling tower fan is grinding loudly (Roof cooling tower
  │    2)
  │ 
  │ Why: same equipment type · reported around the same time ·
  │    similar location · similar description
  │ 
  │ Is this what you are reporting?
  └────────────────────────────────────────────────────
  [ ✅ Yes, this one ]
  [ ➡️ Next match ]
  [ 🆕 None of these ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Yes, this one)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🔍 Ready to submit
  │ 
  │    🕒 When: Mon 23 Nov 2026 06:37
  │    🔧 Equipment type: ❄️ ACMV
  │    📍 Location: cooling tower 2 on the roof
  │ 
  │ Cooling tower fan grinding again
  │ 
  │ Added to the earlier report #862: Cooling tower fan is grinding
  │    loudly (Roof cooling tower 2).
  └────────────────────────────────────────────────────
  [ ✅ Submit ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Submit)
  ┌─ bot (edited in place) ─────────────────────────────
  │ ✅ Added to the earlier report #862.
  │ 
  │ 🛠 Cooling tower fan grinding again  #865
  │ 
  │ Thank you. It has been logged.
  └────────────────────────────────────────────────────
  [ 📅 New query ]  [ 🛠 Report a defect ]
```

#### Back and Cancel

Every step has Back and Cancel; /cancel works anywhere. Nothing is logged on cancel. A flow left alone for 30 minutes is dropped with a message.

```text
you ▸ /report
  ┌─ bot ───────────────────────────────────────────────
  │ 🛠 Report a defect  (step 1 of 4)
  │ 
  │ 🕒 When did it happen?
  │ Tap an option, or type a date and time, e.g. 25 Nov 14:30 or
  │    14:30.
  └────────────────────────────────────────────────────
  [ ⚡ Just now ]  [ 1 hour ago ]
  [ 3 hours ago ]  [ Yesterday ]
  [ ✖️ Cancel ]
you ▸ (taps Just now)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 2 of 4)
  │ 
  │ 🔧 Which equipment type?
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Electrical)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 3 of 4)
  │ 
  │ 📍 Where is it?
  │ Type the location, e.g. Level 3 Plant Room or Tower A lift
  │    lobby.
  └────────────────────────────────────────────────────
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Back)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 2 of 4)
  │ 
  │ 🔧 Which equipment type?
  └────────────────────────────────────────────────────
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⬅️ Back ]  [ ✖️ Cancel ]
you ▸ (taps Back)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛠 Report a defect  (step 1 of 4)
  │ 
  │ 🕒 When did it happen?
  │ Tap an option, or type a date and time, e.g. 25 Nov 14:30 or
  │    14:30.
  └────────────────────────────────────────────────────
  [ ⚡ Just now ]  [ 1 hour ago ]
  [ 3 hours ago ]  [ Yesterday ]
  [ ✖️ Cancel ]
you ▸ (taps Cancel)
  ┌─ bot (edited in place) ─────────────────────────────
  │ ❎ Cancelled. Nothing was logged.
  └────────────────────────────────────────────────────
  [ 📅 New query ]  [ 🛠 Report a defect ]
```

#### /service

Every equipment type on one screen. Types come from the editable list.

```text
you ▸ /service
  ┌─ bot ───────────────────────────────────────────────
  │ 📋 Routine Maintenance Dashboard
  │ 
  │ ❄️ ACMV  (/acmv)
  │    ⚪ 1   🟡 1   🟢 0   — 2 job(s)
  │ 
  │ 🛗 Lift & Escalator  (/lift)
  │    ⚪ 1   🟡 0   🟢 0   — 1 job(s)
  │ 
  │ ⚡ Electrical  (/electrical)
  │    ⚪ 1   🟡 0   🟢 0   — 1 job(s)
  │ 
  │ 🧯 Fire Protection  (/fire)
  │    No jobs recorded
  │ 
  │ 🚰 Plumbing & Sanitary  (/plumbing)
  │    No jobs recorded
  │ 
  │ ──────────────
  │ Total: 4 job(s) · 0 completed
  │ 
  │ ⚪ Yet to start  🟡 In progress  🟢 Completed
  │ Tap a category command above for full details.
  └────────────────────────────────────────────────────
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /acmv  (and /lift, /electrical, /fire, /plumbing, /event)

One equipment type, unfinished work first. Commands exist for the types present at start-up; types added later are always one tap away in the menu.

```text
you ▸ /acmv
  ┌─ bot ───────────────────────────────────────────────
  │ ❄️ ACMV — Routine Maintenance
  │ 
  │ 🟡 Replace chiller filters  ACMV-001
  │    📍 Location: Level 3 Plant Room
  │    🔧 Type: Preventive maintenance
  │    📊 Status: In Progress
  │    🗓 Est. completion: Week 4 November 2026
  │    🔁 Next job: -
  │ 
  │ ⚪ Cooling tower belt check  ACMV-002
  │    📍 Location: Roof
  │    🔧 Type: Preventive maintenance
  │    📊 Status: Yet to Start
  │    🗓 Est. completion: Week 4 November 2026
  │    🔁 Next job: -
  │ 
  │ ──────────────
  │ 2 job(s) in this category · /service for the full dashboard
  └────────────────────────────────────────────────────
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### Tapping a button

Buttons edit the message in place instead of adding a new one.

```text
you ▸ (taps Lift)
  ┌─ bot (edited in place) ─────────────────────────────
  │ 🛗 LIFT & ESCALATOR — Routine Maintenance
  │ 
  │ ⚪ Quarterly lift inspection  LIFT-001
  │    📍 Location: Block A lifts
  │    🔧 Type: Preventive maintenance
  │    📊 Status: Yet to Start
  │    🗓 Est. completion: Week 4 November 2026
  │    🔁 Next job: -
  │ 
  │ ──────────────
  │ 1 job(s) in this category · /service for the full dashboard
  └────────────────────────────────────────────────────
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /pending

Everything not yet completed.

```text
you ▸ /pending
  ┌─ bot ───────────────────────────────────────────────
  │ ⏳ Outstanding Jobs (all trades)
  │ 
  │ ❄️ ACMV
  │    🟡 Replace chiller filters — Level 3 Plant Room — due Week 4
  │    November 2026
  │    ⚪ Cooling tower belt check — Roof — due Week 4 November 2026
  │ 
  │ 🛗 Lift & Escalator
  │    ⚪ Quarterly lift inspection — Block A lifts — due Week 4
  │    November 2026
  │ 
  │ ⚡ Electrical
  │    ⚪ Thermal scan of main switchboard — MSB room — due Week 3
  │    November 2026
  │ 
  │ 5 outstanding job(s) in total.
  └────────────────────────────────────────────────────
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /myjobs

Tess has no web account, so nothing can be assigned to her (never "everything"). Priya is linked to one.

```text
you ▸ /myjobs
  ┌─ bot ───────────────────────────────────────────────
  │ ✅ No maintenance jobs are assigned to you.
  └────────────────────────────────────────────────────
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
you ▸ /myjobs
  ┌─ bot ───────────────────────────────────────────────
  │ ✅ No maintenance jobs are assigned to you.
  └────────────────────────────────────────────────────
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /defects

Open reports, newest first, up to 25. Reports added to an earlier one are not listed twice.

```text
you ▸ /defects
  ┌─ bot ───────────────────────────────────────────────
  │ 🛠 Open Defects
  │ 
  │ 🔴 Cooling tower fan is grinding loudly  #862
  │    📊 Status: Open
  │    🔸 Priority: medium
  │    🗓 Reported: 23 Nov 2026
  │ 
  │ 🔴 Water dripping from the main valve  #864
  │    📊 Status: Open
  │    🔺 Priority: high
  │    🗓 Reported: 23 Nov 2026
  │ 
  │ 🔴 Chiller filters look blocked  #863
  │    📊 Status: Open
  │    🔸 Priority: medium
  │    🗓 Reported: 23 Nov 2026
  │ 
  │ 3 defect(s).
  └────────────────────────────────────────────────────
```

#### /calendar and /overdue

`/calendar [today|week|month|overdue]` and the /today and /overdue shortcuts.

```text
you ▸ /calendar
  ┌─ bot ───────────────────────────────────────────────
  │ 📅 Next 7 days
  │ 
  │ Mon 23 Nov 2026 (today)
  │    🟡 Replace chiller filters — Level 3 Plant Room ACMV-001 · due
  │ 
  │ Tue 24 Nov 2026 (tomorrow)
  │    ⚪ Quarterly lift inspection — Block A lifts LIFT-001 · due
  │ 
  │ Wed 25 Nov 2026
  │    ⚪ Cooling tower belt check — Roof ACMV-002 · due
  │ 
  │ Thu 26 Nov 2026
  │    ⚪ Annual fire drill — Main lobby EVT-001 · due
  │ 
  │ ⚠️ 1 overdue — see /overdue
  └────────────────────────────────────────────────────
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
you ▸ /overdue
  ┌─ bot ───────────────────────────────────────────────
  │ 📅 Overdue maintenance
  │ 
  │ Fri 20 Nov 2026 (3 days overdue)
  │    ⚪ Thermal scan of main switchboard — MSB room ELEC-001 ·
  │    overdue
  └────────────────────────────────────────────────────
  [ 📅 Event query ]  [ 🛠 Report a defect ]
  [ ❄️ ACMV ]  [ 🛗 Lift & Escalator ]
  [ ⚡ Electrical ]  [ 🧯 Fire Protection ]
  [ 🚰 Plumbing & Sanitary ]
  [ ⏳ Outstanding ]  [ 🔄 Refresh ]
```

#### /access  (master control only)

Pending requests with buttons, and who has access. End users get "Only master control can do that".

```text
you ▸ /access
  ┌─ bot ───────────────────────────────────────────────
  │ 🛡 Access
  │ 
  │ No pending requests.
  │ 
  │ Approved:
  │    • Sam — end user
  │    • Priya Nair — end user
  │    • Tess Tan — end user
  │    • Alex Admin — master control
  └────────────────────────────────────────────────────
```

#### Assignment alert (pushed by the bot)

Sent to a linked member when a defect is assigned to their web account. Checked every 30 s, retried on failure.

```text
  ┌─ bot → Priya ───────────────────────────────────────
  │ 🔔 A defect has been assigned to you.
  │ 
  │ 🔴 Water leak at B2 pump room  #866
  │    📊 Status: Open
  │    🔺 Priority: high
  │    👷 Technician: Priya Nair
  │    🗓 Reported: 23 Nov 2026
  │ 
  │ Steady drip from the main valve.
  │ 
  │ Use /mydefects to see everything assigned to you.
  └────────────────────────────────────────────────────
```

<!-- demos:end -->

---

## Setup

### A. Everything with Docker Compose (recommended)

```bash
cp .env.example .env        # set TELEGRAM_BOT_TOKEN (from @BotFather) and SECRET_KEY (long random value)
docker compose up --build   # db + migrate + api + web + bot
```
Website: <http://localhost:3000>. Then create the first master control (below).

### B. Without Docker
Prerequisites: Python 3.11+, PostgreSQL, Node 20+ (website only).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r api/requirements.txt                  # bot + API (use requirements.txt for the bot alone)
cp .env.example .env                                 # set TELEGRAM_BOT_TOKEN, SECRET_KEY, DATABASE_URL
alembic -c migrations/alembic.ini upgrade head       # creates every table (works on an empty database)
python -m botapp.main                                # the bot
flask --app api.app run --port 5000                  # the API      (separate terminal)
cd web && npm install && npm run dev                 # the website  (separate terminal, http://localhost:3000)
```

### First master control (once)
1. Send `/start` to your bot; it offers *Request access*. Tap it (this also tells you your Telegram ID).
2. On the host: `python -m botapp.admin requests` then `python -m botapp.admin approve <TELEGRAM_ID> --master`
   (or in one step: `python -m botapp.admin add <TELEGRAM_ID> "Your Name" --master`).
3. For the website: `python -m botapp.admin web-login <TELEGRAM_ID> you@example.com` (prompts for a password, 10+ characters).
4. Sign in at the website. From now on approve everyone else there or in Telegram.

With Docker, prefix commands: `docker compose run --rm migrate python -m botapp.admin …`.

### Load your data
Website → *Scheduled & events* → *Import CSV* (use *Check first*), or `python -m botapp.admin import-csv file.csv [--dry-run]`.
Columns (case-insensitive, common aliases accepted): `job_ref, category, description, location, starts_at, ends_at,
maintenance_type, status, next_job_date, schedule_note`. `category` (an equipment type name or key), `description` and
`location` are required; `Event` is a valid category. Rows with an existing `job_ref` are updated. Bad rows are skipped
with their line number and reason; good rows still load. (There is no JSON-schema validation yet.)

| Variable | Used by | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | bot | from @BotFather |
| `DATABASE_URL` | all | the shared PostgreSQL database (Compose sets it for you) |
| `SECRET_KEY` | API | signs website logins |
| `TZ` | bot, API | decides what "today" means (e.g. `Asia/Singapore`) |
| `JWT_HOURS` | API | website session length (default 12) |

---

## Administration (CLI)

`python -m botapp.admin <command>` (run from the repository root):

| Command | Does |
|---|---|
| `requests` / `members` | list pending requests / everyone |
| `approve CHAT_ID [--master]`, `deny`, `revoke`, `set-tier CHAT_ID end_user\|master_control` | decide (the person is told by the bot) |
| `add CHAT_ID "Name" [--master] [--web-user ID]` | add someone already approved |
| `link-user CHAT_ID USER_ID` / `--clear` | link / unlink a web account |
| `web-login CHAT_ID EMAIL [--reset]` | give a master control member a website login |
| `types`, `add-type KEY "Name" [--emoji X --blurb T]`, `edit-type KEY [--name …] [--disable\|--enable]` | equipment types |
| `import-csv FILE [--dry-run]` | load scheduled items / events |
| `remove CHAT_ID` | delete a member |

---

## Tests

```bash
createdb fm_test
DATABASE_URL=postgresql:///fm_test alembic -c migrations/alembic.ini upgrade head
TEST_DATABASE_URL=postgresql:///fm_test pytest
```
Each test runs in a rolled-back transaction. They need PostgreSQL (native enums), not SQLite. Highlights: the full Telegram
conversations run through the **real dispatcher** (`tests/harness.py`), the access rules (including the last-master guard and
"one request"), the similarity ranking, the importer's bad-row handling, every API endpoint and its auth, and migrations
on both an empty and an existing database.

## Troubleshooting

| Symptom | Cause |
|---|---|
| "CANNOT START - TOKEN PROBLEM" / "TELEGRAM REJECTED YOUR TOKEN" | token missing, mis-copied or revoked (@BotFather → `/mybots`) |
| "CANNOT START - DATABASE PROBLEM … connection refused" | PostgreSQL is not running or `DATABASE_URL` is wrong |
| "… missing table(s)" / "… missing column(s)" | run `alembic -c migrations/alembic.ini upgrade head` |
| Website: "does not have website access" | the person is not an approved **master control** member linked to a web login (`web-login`) |
| Website: "Your website access has been withdrawn" | they were revoked or demoted |
| Someone approved on the website did not get a message | the bot delivers it within ~30 s; the bot must be running |
| `/myjobs` empty for someone with jobs | the member is not linked to a web account |
| Two bots fighting | one polling process per token |

## Known limitations

* **Messages sent while the bot is offline are discarded** (`drop_pending_updates=True`).
* Similarity is a transparent heuristic, not machine learning; thresholds (`core/similarity.py`) may need tuning on real data.
* No JSON-schema validation of CSVs yet (basic checks only).
* Photos: the largest Telegram size at or under 400 KB, otherwise the smallest; no resizing.
* The website monitors; it does not edit or delete scheduled items or reports (status changes happen elsewhere).
* A command for an equipment type added while the bot is running works (`/<key>`), and its menu entry appears within a minute.
* Docker Compose is provided and validated (`docker compose config`) but was not run in the build environment (no Docker daemon there).

## Ideas (not built)
Keep messages sent while the bot was down · scheduled digests (morning / midday / end of day) and alerts for **all** members
(there are no per-role audiences) · set Ongoing/Done and add a note from Telegram · `/defect <id>` and paging · real photo
resizing · audit log and a heartbeat · webhook mode · JSON-schema CSV validation.
