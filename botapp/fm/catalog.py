"""
Facility-management trade catalog and status vocabulary.

This is the single source of truth for the maintenance side of the platform.
It drives, all at once:

  * which /commands the Telegram bot exposes  (bot/handlers/browse.py)
  * the category filter the REST API validates (routes/maintenance.py)
  * the dropdowns the React app renders       (GET /api/maintenance/categories)
  * the column the workbook importer matches  (scripts/import_workbook.py)

TO ADD A SIXTH TRADE: add one entry to CATEGORIES. Nothing else needs to
change -- no migration, no new handler, no frontend edit. That property is
why MaintenanceJob.category is a plain string validated against this dict
rather than a database enum.

Lifted from the FM chatbot's config.py, which had the same design.
"""

# key    -> the Telegram command, i.e. /acmv, and the API's category filter
# name   -> human-readable heading used in message titles and the web UI
# excel  -> the exact string written in a workbook's "Category" column
# blurb  -> short description shown in the bot's /start menu
# emoji  -> visual marker that keeps long chat messages scannable
CATEGORIES = {
    "acmv": {
        "name": "ACMV",
        "excel": "ACMV",
        "blurb": "ACMV servicing",
        "emoji": "❄️",
    },
    "lift": {
        "name": "Lift & Escalator",
        "excel": "Lift & Escalator",
        "blurb": "Lift and escalator servicing",
        "emoji": "🛗",
    },
    "electrical": {
        "name": "Electrical",
        "excel": "Electrical",
        "blurb": "Electrical maintenance",
        "emoji": "⚡",
    },
    "fire": {
        "name": "Fire Protection",
        "excel": "Fire Protection",
        "blurb": "Fire protection services",
        "emoji": "🧯",
    },
    "plumbing": {
        "name": "Plumbing & Sanitary",
        "excel": "Plumbing & Sanitary",
        "blurb": "Plumbing and sanitary services",
        "emoji": "🚰",
    },
}

# The canonical category strings, i.e. what actually goes in the database.
CATEGORY_NAMES = [meta["name"] for meta in CATEGORIES.values()]

# Reverse lookup: canonical name -> command key. Used when rendering a stored
# job back into a bot message or a UI badge.
KEY_BY_NAME = {meta["name"]: key for key, meta in CATEGORIES.items()}


def category_key(name):
    """Command key for a stored category name, or None if it is not a known trade."""
    return KEY_BY_NAME.get((name or "").strip())


def category_name(key):
    """Canonical category name for a command key, or None."""
    meta = CATEGORIES.get((key or "").strip().lower())
    return meta["name"] if meta else None


def resolve_category(value):
    """
    Accept either a command key ("acmv") or a canonical name ("ACMV") and
    return the canonical name. Returns None when the value is not a known
    trade, which is how the API turns a bad ?category= into a 400.

    Matching is case-insensitive because staff type category names by hand
    into spreadsheets and are not consistent about it.
    """
    text = (value or "").strip()
    if not text:
        return None

    meta = CATEGORIES.get(text.lower())
    if meta:
        return meta["name"]

    lowered = text.lower()
    for name in CATEGORY_NAMES:
        if name.lower() == lowered:
            return name
    return None


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------
STATUS_YET_TO_START = "Yet to Start"
STATUS_IN_PROGRESS = "In Progress"
STATUS_COMPLETED = "Completed"

JOB_STATUSES = [STATUS_YET_TO_START, STATUS_IN_PROGRESS, STATUS_COMPLETED]

# Icons let a user skim a long dashboard and see instantly what is outstanding.
STATUS_ICONS = {
    "yet to start": "⚪",
    "in progress": "🟡",
    "completed": "🟢",
}

# Staff typing into a spreadsheet are inconsistent; normalise whatever they
# wrote onto the three values the database accepts.
STATUS_CANONICAL = {
    "yet to start": STATUS_YET_TO_START,
    "not started": STATUS_YET_TO_START,
    "in progress": STATUS_IN_PROGRESS,
    "ongoing": STATUS_IN_PROGRESS,
    "completed": STATUS_COMPLETED,
    "complete": STATUS_COMPLETED,
    "done": STATUS_COMPLETED,
}

# ---------------------------------------------------------------------------
# Maintenance type
# ---------------------------------------------------------------------------
TYPE_PREVENTIVE = "Preventive"
TYPE_CORRECTIVE = "Corrective"

MAINTENANCE_TYPES = [TYPE_PREVENTIVE, TYPE_CORRECTIVE]

TYPE_CANONICAL = {
    "preventive": TYPE_PREVENTIVE,
    "preventative": TYPE_PREVENTIVE,
    "pm": TYPE_PREVENTIVE,
    "corrective": TYPE_CORRECTIVE,
    "cm": TYPE_CORRECTIVE,
}


def canonical_status(value, default=STATUS_YET_TO_START):
    """Normalise a status written by a human. Unknown text falls back to `default`."""
    return STATUS_CANONICAL.get((value or "").strip().lower(), default)


def canonical_type(value, default=TYPE_PREVENTIVE):
    """Normalise a maintenance type written by a human."""
    return TYPE_CANONICAL.get((value or "").strip().lower(), default)


def status_icon(status):
    """Emoji for a status, with a neutral marker for anything unrecognised."""
    return STATUS_ICONS.get((status or "").strip().lower(), "⚫")
