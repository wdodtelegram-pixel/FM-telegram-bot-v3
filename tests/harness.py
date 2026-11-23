"""
Drive the real Telegram dispatcher without Telegram.

A FakeBot records what the bot would send; Chat builds genuine Update objects
(messages, commands, button taps) and feeds them through the Application the
production code builds, so handler order, conversation states and callback
patterns are all exercised, not just the handler bodies.
"""
import asyncio
import time

from telegram import Update, User
from telegram.ext import ExtBot

from botapp.main import build_application


class FakeBot(ExtBot):
    def __init__(self):
        super().__init__('123456789:' + 'A' * 35)
        self._log = []                      # [(chat_id, text, markup_text, edited)]
        self._bot_user = User(id=1, first_name='FMBot', is_bot=True, username='fm_test_bot')
        self._loop = asyncio.new_event_loop()   # one loop for the whole conversation

    @property
    def log(self):
        return self._log

    async def initialize(self):             # no network
        self._initialized = True

    async def get_me(self, *a, **k):
        return None

    async def send_message(self, chat_id, text, *a, reply_markup=None, **k):
        self.log.append((chat_id, text, str(reply_markup) if reply_markup else '', False))

    async def edit_message_text(self, text, chat_id=None, message_id=None, *a, reply_markup=None, **k):
        self.log.append((chat_id, text, str(reply_markup) if reply_markup else '', True))

    async def answer_callback_query(self, *a, **k):
        return True

    async def delete_message(self, *a, **k):
        return True

    async def set_my_commands(self, *a, **k):
        return True


class Chat:
    _next = 1000

    def __init__(self, app, bot, chat_id, name='Tester'):
        self.app, self.bot, self.chat_id, self.name = app, bot, chat_id, name
        self.msg_id = 10

    def _next_id(self):
        Chat._next += 1
        return Chat._next

    def _user(self):
        return {'id': self.chat_id, 'is_bot': False, 'first_name': self.name, 'username': 'tester'}

    def _chat(self):
        return {'id': self.chat_id, 'type': 'private', 'first_name': self.name}

    def _process(self, data):
        update = Update.de_json(data, self.bot)
        self.bot._loop.run_until_complete(self._dispatch(update))

    async def _dispatch(self, update):
        await self.app.process_update(update)

    def say(self, text):
        data = {'update_id': self._next_id(), 'message': {
            'message_id': self._next_id(), 'date': int(time.time()), 'chat': self._chat(),
            'from': self._user(), 'text': text}}
        if text.startswith('/'):
            data['message']['entities'] = [{'type': 'bot_command', 'offset': 0, 'length': len(text.split()[0])}]
        self._process(data)
        return self.last()

    def tap(self, data):
        self._process({'update_id': self._next_id(), 'callback_query': {
            'id': str(self._next_id()), 'from': self._user(), 'chat_instance': 'x', 'data': data,
            'message': {'message_id': self._next_id(), 'date': int(time.time()), 'chat': self._chat(),
                        'from': {'id': 1, 'is_bot': True, 'first_name': 'Bot'}, 'text': 'prev'}}})
        return self.last()

    def mine(self):
        return [m for m in self.bot.log if m[0] == self.chat_id]

    def last(self):
        mine = self.mine()
        return mine[-1] if mine else None

    def last_text(self):
        m = self.last()
        return m[1] if m else ''

    def last_buttons(self):
        m = self.last()
        return m[2] if m else ''


def make_app():
    bot = FakeBot()
    app = build_application(None, bot=bot)
    bot._loop.run_until_complete(app.initialize())
    return app, bot
