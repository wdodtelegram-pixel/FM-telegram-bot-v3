"""
Defect lists: /defects and /mydefects.

Reporting a defect is the guided flow in handlers/guided.py (/report).
"""

import logging

from botapp.auth import require_member
from botapp.ui import reply
from core.db import run_db
from core.fm import formatters
from core.services import defect_service

logger = logging.getLogger(__name__)


def _render_defects(actor, assigned_only):
    defects = defect_service.list_visible_defects(actor, assigned_only=assigned_only)
    heading = 'Your Assigned Defects' if assigned_only else 'Open Defects'
    return formatters.defect_list_message(defects, heading)


@require_member
async def defects_command(update, context, user):
    """/defects -- open defects this user is allowed to see."""
    try:
        text = await run_db(_render_defects, user, False)
        await reply(update, text)
    except Exception as exc:
        logger.exception('/defects failed')
        await reply(update, formatters.error_message(exc))


@require_member
async def my_defects_command(update, context, user):
    """/mydefects -- defects assigned to the linked web account."""
    try:
        text = await run_db(_render_defects, user, True)
        await reply(update, text)
    except Exception as exc:
        logger.exception('/mydefects failed')
        await reply(update, formatters.error_message(exc))
