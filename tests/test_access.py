import pytest

from core import access
from core.models import BotMember
from botapp import admin


def seed_master(chat=3001, name='Boss'):
    admin.add_member(chat, name, tier='master_control')
    return access.by_chat(chat)


def test_first_request_is_stored_pending(session):
    state, m = access.request_access(3101, 'sam', 'Sam')
    assert state == 'requested' and m['status'] == 'pending' and m['tier'] == 'end_user'


def test_asking_again_does_not_create_a_second_request(session):
    access.request_access(3102, 'sam', 'Sam')
    state, _ = access.request_access(3102, 'sam', 'Sam')
    assert state == 'pending' and BotMember.query.filter_by(telegram_chat_id=3102).count() == 1


def test_approved_person_never_has_to_ask_again(session):
    boss = seed_master()
    _, m = access.request_access(3103, 'a', 'A')
    access.approve(m['id'], by_member_id=boss.id)
    assert access.request_access(3103, 'a', 'A')[0] == 'approved'


def test_denied_person_cannot_re_request_until_reconsidered(session):
    boss = seed_master()
    _, m = access.request_access(3104, 'a', 'A')
    access.deny(m['id'], by_member_id=boss.id)
    assert access.request_access(3104, 'a', 'A')[0] == 'denied'
    access.reconsider(m['id'], by_member_id=boss.id)
    assert access.state_for_chat(3104) == 'pending'


def test_only_master_control_can_decide(session):
    boss = seed_master()
    _, applicant = access.request_access(3105, 'a', 'A')
    access.approve(applicant['id'], by_member_id=boss.id)
    _, other = access.request_access(3106, 'b', 'B')
    plain = access.by_chat(3105)                      # approved end user
    for fn in (access.approve, access.deny):
        with pytest.raises(access.AccessError, match='master control'):
            fn(other['id'], by_member_id=plain.id)
    with pytest.raises(access.AccessError):
        access.approve(other['id'], by_member_id=999999)


def test_a_pending_person_cannot_decide_anything(session):
    boss = seed_master()
    _, a = access.request_access(3107, 'a', 'A')
    _, b = access.request_access(3108, 'b', 'B')
    with pytest.raises(access.AccessError):
        access.approve(b['id'], by_member_id=a['id'])


def test_revoke_removes_access_and_blocks_a_new_request(session):
    boss = seed_master()
    _, m = access.request_access(3109, 'a', 'A')
    access.approve(m['id'], by_member_id=boss.id)
    access.revoke(m['id'], by_member_id=boss.id)
    assert access.request_access(3109, 'a', 'A')[0] == 'revoked'


def test_last_master_control_cannot_be_revoked_or_demoted(session):
    # other tests' rows are rolled back; make sure the only master is ours
    BotMember.query.filter_by(tier='master_control').delete()
    boss = seed_master(3110)
    with pytest.raises(access.AccessError, match='last master'):
        access.revoke(boss.id, by_member_id=boss.id)
    with pytest.raises(access.AccessError, match='last master'):
        access.set_tier(boss.id, 'end_user', by_member_id=boss.id)
    second = seed_master(3111, 'Second')
    access.set_tier(boss.id, 'end_user', by_member_id=second.id)      # now allowed
    assert access.by_chat(3110).tier == 'end_user'


def test_cannot_deny_an_approved_person_and_unknown_tier_is_refused(session):
    boss = seed_master()
    _, m = access.request_access(3112, 'a', 'A')
    access.approve(m['id'], by_member_id=boss.id)
    with pytest.raises(access.AccessError):
        access.deny(m['id'], by_member_id=boss.id)
    with pytest.raises(access.AccessError):
        access.approve(m['id'], by_member_id=boss.id, tier='god')


def test_list_members_by_status(session):
    boss = seed_master()
    access.request_access(3113, 'a', 'A')
    assert [m.telegram_chat_id for m in access.list_members('pending')][:1] == [3113]
    with pytest.raises(access.AccessError):
        access.list_members('weird')


def test_link_web_user(session, world):
    boss = seed_master()
    access.link_web_user(boss.id, world['csr'].id, by_member_id=boss.id)
    assert access.by_chat(3001).user_id == world['csr'].id
    with pytest.raises(access.AccessError):
        access.link_web_user(boss.id, 999999)
