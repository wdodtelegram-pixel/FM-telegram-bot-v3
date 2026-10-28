"""
Shared Telegram presentation helpers.

Carried over from the FM chatbot's bot.py, where the message chunker and the
typed-command/button-press unifier already lived. Split out here so the handler
modules stay short.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from botapp.fm import catalog

MAX_MESSAGE_LENGTH = 4096  # Telegram's hard limit


def split_message(text, limit=MAX_MESSAGE_LENGTH - 100):
    """
    Telegram rejects any message over 4096 characters.

    A trade with 40+ jobs would silently fail to send, so split on the blank
    line between job blocks. Splitting mid-block would also cut an unclosed
    <b> tag in half and cause a parse error on top of the truncation.
    """
    if len(text) <= limit:
        return [text]

    chunks, current = [], ""
    for block in text.split("\n\n"):
        # +2 accounts for the "\n\n" we re-insert.
        if len(current) + len(block) + 2 > limit and current:
            chunks.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block

    if current:
        chunks.append(current)
    return chunks


def category_keyboard():
    """
    The tappable trade grid under the dashboard.

    Typing /acmv works, but on a phone tapping is quicker. Two buttons per row
    keeps the labels readable on a narrow screen. Generated from the catalog,
    so a sixth trade appears here with no edit.
    """
    buttons = [
        InlineKeyboardButton(f"{meta['emoji']} {meta['name']}", callback_data=f"cat:{key}")
        for key, meta in catalog.CATEGORIES.items()
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([
        InlineKeyboardButton("⏳ Outstanding", callback_data="pending"),
        InlineKeyboardButton("🔄 Refresh", callback_data="refresh"),
    ])
    return InlineKeyboardMarkup(rows)


def buildings_keyboard(buildings):
    """One button per building, for the /report conversation."""
    rows = [
        [InlineKeyboardButton(b['name'], callback_data=f"bld:{b['id']}")]
        for b in buildings
    ]
    rows.append([InlineKeyboardButton("✖️ Cancel", callback_data="report:cancel")])
    return InlineKeyboardMarkup(rows)


def priority_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔹 Low", callback_data="pri:low"),
            InlineKeyboardButton("🔸 Medium", callback_data="pri:medium"),
            InlineKeyboardButton("🔺 High", callback_data="pri:high"),
        ],
        [InlineKeyboardButton("✖️ Cancel", callback_data="report:cancel")],
    ])


async def reply(update, text, keyboard=None):
    """
    Answer both a typed command and a tapped button with one call.

    A typed command arrives with update.message set; a button press arrives
    with update.callback_query instead. Without this every handler would carry
    that if/else.

    The keyboard is attached only to the LAST chunk, so the buttons always sit
    at the bottom of the conversation where the user expects them.
    """
    chunks = split_message(text)

    for index, chunk in enumerate(chunks):
        markup = keyboard if index == len(chunks) - 1 else None

        # A button press edits its message in place, but only for the first
        # chunk -- any overflow has to be sent as a new message.
        if update.callback_query and index == 0:
            await update.callback_query.edit_message_text(
                chunk, parse_mode=ParseMode.HTML, reply_markup=markup
            )
        else:
            await update.effective_chat.send_message(
                chunk, parse_mode=ParseMode.HTML, reply_markup=markup
            )
