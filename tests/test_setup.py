import datetime

import pytest

from botapp import admin
from core import access, setup
from core.models import BotMember, SetupClaim, User
from core.passwords import check_password
from tests.harness import Chat, make_app

PW = 'a-long-enough-password'


@pytest.fixture(autouse=True)
def fresh_install(session):
    """No members at all, like a brand-new install (rolled back after the test)."""
    SetupClaim.query.delete()
    BotMember.query.delete()
    session.flush()


def test_claim_makes_the_first_person_master_control_with_a_website_login(session):
    code = setup.create_claim('Boss@Example.test', PW)
    assert len(code.replace('-', '')) == setup.CODE_LENGTH
    out = setup.claim(6001, 'boss', 'Bea Boss', code)
    assert out['email'] == 'boss@example.test'
    m = access.by_chat(6001)
    assert m.is_master and m.status == 'approved' and m.user_id is not None
    user = User.query.get(m.user_id)
    assert user.email == 'boss@example.test' and check_password(PW, user.password_hash)
    assert setup.master_exists()


def test_only_hashes_are_stored(session):
    code = setup.create_claim('a@example.test', PW)
    row = SetupClaim.query.one()
    assert code.replace('-', '') not in (row.code_hash, row.password_hash) and PW not in row.password_hash


def test_code_works_once_and_a_running_system_refuses_more(session):
    code = setup.create_claim('a@example.test', PW)
    setup.claim(6002, 'a', 'A', code)
    with pytest.raises(setup.SetupError, match='already set up'):
        setup.claim(6003, 'b', 'B', code)
    with pytest.raises(setup.SetupError, match='already set up'):
        setup.create_claim('c@example.test', PW)


def test_wrong_codes_are_counted_and_lock_out(session):
    code = setup.create_claim('a@example.test', PW)
    for i in range(setup.MAX_ATTEMPTS):
        with pytest.raises(setup.SetupError, match='not right'):
            setup.claim(6004, 'x', 'X', 'WRONG-CODE0')
    with pytest.raises(setup.SetupError, match='Too many'):
        setup.claim(6004, 'x', 'X', code)               # even the right code is refused once locked
    assert not setup.master_exists()
    new_code = setup.create_claim('a@example.test', PW)  # running the launcher again issues a fresh one
    assert setup.claim(6005, 'x', 'X', new_code)['email'] == 'a@example.test'


def test_expired_code_is_refused(session):
    code = setup.create_claim('a@example.test', PW)
    SetupClaim.query.one().expires_at = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)
    session.flush()
    with pytest.raises(setup.SetupError, match='expired'):
        setup.claim(6006, 'x', 'X', code)


def test_code_is_case_and_dash_insensitive(session):
    code = setup.create_claim('a@example.test', PW)
    assert setup.claim(6007, 'x', 'X', code.lower().replace('-', ' '))


@pytest.mark.parametrize('email,pw,msg', [('nope', PW, 'valid email'), ('a@b', PW, 'valid email'),
                                          ('a@example.test', 'short', 'at least')])
def test_bad_input_is_refused(session, email, pw, msg):
    with pytest.raises(setup.SetupError, match=msg):
        setup.create_claim(email, pw)


def test_an_existing_website_email_is_refused_even_with_underscores(session, world):
    session.execute(__import__('sqlalchemy').text("UPDATE users SET email = 'a_b@example.test' WHERE id = :i"),
                    {'i': world['csr'].id})
    with pytest.raises(setup.SetupError, match='already has'):
        setup.create_claim('A_B@example.test', PW)
    setup.create_claim('aab@example.test', PW)          # "_" is not a wildcard


def test_claiming_upgrades_a_chat_that_had_already_asked_for_access(session):
    access.request_access(6008, 'early', 'Early Bird')
    setup.claim(6008, 'early', 'Early Bird', setup.create_claim('e@example.test', PW))
    assert access.by_chat(6008).is_master
    assert BotMember.query.filter_by(telegram_chat_id=6008).count() == 1


# --- through the real Telegram dispatcher -------------------------------------
def test_claim_command_end_to_end_and_the_message_is_deleted(session):
    app, bot = make_app()
    chat = Chat(app, bot, 6100, 'Bea')
    code = setup.create_claim('bea@example.test', PW)
    assert 'Send the setup code' in chat.say('/claim')[1]
    assert 'not right' in chat.say('/claim WRONG-CODE0')[1]
    out = chat.say(f'/claim {code}')
    assert 'You are master control' in out[1] and 'bea@example.test' in out[1] and 'localhost:3000' in out[1]
    assert access.by_chat(6100).is_master
    assert 'Signed in as' in chat.say('/start')[1]
    assert 'already set up' in Chat(app, bot, 6101, 'Other').say(f'/claim {code}')[1]


# --- command line ----------------------------------------------------------------
def test_setup_status_exit_code(session, capsys):
    with pytest.raises(SystemExit) as e:
        admin.main(['setup-status'])
    assert e.value.code == 1
    admin.add_member(6200, 'Boss', tier='master_control')
    with pytest.raises(SystemExit) as e:
        admin.main(['setup-status'])
    assert e.value.code == 0


def test_first_run_prompts_and_prints_a_code(session, monkeypatch, capsys):
    monkeypatch.setattr('builtins.input', lambda prompt='': 'first@example.test')
    monkeypatch.setattr('getpass.getpass', lambda prompt='': PW)
    admin.main(['first-run'])
    out = capsys.readouterr().out
    assert '/claim ' in out and 'works once' in out
    assert SetupClaim.query.count() == 1


def test_first_run_on_an_installed_system_says_so_and_creates_nothing(session, capsys):
    admin.add_member(6201, 'Boss', tier='master_control')
    admin.main(['first-run'])
    assert 'already set up' in capsys.readouterr().out
    assert SetupClaim.query.count() == 0


def test_first_run_rejects_mismatched_passwords(session, monkeypatch):
    answers = iter([PW, PW + 'x'])
    monkeypatch.setattr('builtins.input', lambda prompt='': 'first@example.test')
    monkeypatch.setattr('getpass.getpass', lambda prompt='': next(answers))
    with pytest.raises(SystemExit) as e:
        admin.main(['first-run'])
    assert e.value.code == 1
