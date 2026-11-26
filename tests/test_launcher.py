"""
The Mac/Linux launcher, run for real with fake `docker` and `curl` programs on PATH.

No Docker or network is needed: the fakes record what the launcher asked for and
answer like a healthy (or unhealthy) Docker. This proves the launcher's logic:
what it checks, what it asks, what it writes, and what it runs, in what order.
The Windows launcher (launcher/start.ps1) has the same steps but is NOT executed here.
"""
import os
import shutil
import socket
import stat
import subprocess
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD_TOKEN = '123456789:' + 'A' * 35

DOCKER = r'''#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
state="$FAKE_STATE"
case "$1 $2" in
  "info "*|"info ")
    # up after FAKE_DOCKER_DOWN_FOR calls (0 = already up, 999 = never)
    n=$(cat "$state/info_calls" 2>/dev/null || echo 0); echo $((n+1)) > "$state/info_calls"
    [ "$n" -ge "${FAKE_DOCKER_DOWN_FOR:-0}" ]; exit $?;;
  "compose version") [ -z "$FAKE_NO_COMPOSE" ]; exit $?;;
  "compose pull") [ -z "$FAKE_PULL_FAILS" ]; exit $?;;
  "compose build") [ -z "$FAKE_BUILD_FAILS" ]; exit $?;;
  "compose up") [ -z "$FAKE_UP_FAILS" ]; exit $?;;
  "compose ps") echo bot; echo api; echo web; exit 0;;
  "compose run")
    case "$*" in
      *setup-status*) [ -f "$state/setup_done" ]; exit $?;;
      *first-run*) echo "      /claim ABCDE-FGHJK"; [ -n "$FAKE_CLAIM_NEVER" ] || touch "$state/setup_done"; exit 0;;
    esac;;
esac
exit 0
'''

CURL = r'''#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_LOG"
case "$*" in
  *api.telegram.org/bot*getMe*)
    case "$*" in
      *"${FAKE_BAD_TOKEN:-@@none@@}"*) echo '{"ok":false,"error_code":401}'; exit 0;;
      *) [ -n "$FAKE_OFFLINE" ] && exit 6; echo '{"ok":true,"result":{"username":"demo_bot"}}'; exit 0;;
    esac;;
  *api.telegram.org*) [ -n "$FAKE_OFFLINE" ] && exit 6; exit 0;;
  */api/health*) [ -z "$FAKE_SITE_DOWN" ]; exit $?;;
esac
exit 0
'''


@pytest.fixture()
def env(tmp_path):
    app = tmp_path / 'app'
    (app / 'launcher').mkdir(parents=True)
    for f in ('start.sh', 'stop.sh'):
        shutil.copy(os.path.join(ROOT, 'launcher', f), app / 'launcher' / f)
    shims = tmp_path / 'shims'
    shims.mkdir()
    for name, body in (('docker', DOCKER), ('curl', CURL)):
        p = shims / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / 'state'
    state.mkdir()
    log = tmp_path / 'calls.log'
    log.write_text('')
    return type('Env', (), dict(app=app, shims=shims, state=state, log=log, tmp=tmp_path))


def run(env, stdin='', **extra):
    e = dict(os.environ)
    e.update(PATH=f'{env.shims}:/usr/bin:/bin:/usr/local/bin', FAKE_LOG=str(env.log), FAKE_STATE=str(env.state),
             FM_NO_PAUSE='1', FM_DOCKER_WAIT='9', FM_START_WAIT='6', HOME=str(env.tmp))
    e.update({k: str(v) for k, v in extra.items()})
    p = subprocess.run(['bash', str(env.app / 'launcher' / 'start.sh')], input=stdin, text=True,
                       capture_output=True, env=e, timeout=60)
    return p, env.log.read_text().splitlines()


def envfile(env):
    path = env.app / '.env'
    return dict(l.split('=', 1) for l in path.read_text().splitlines() if '=' in l and not l.startswith('#'))


def test_first_run_asks_for_the_token_writes_a_private_env_and_runs_in_order(env):
    p, calls = run(env, f'{GOOD_TOKEN}\nAsia/Singapore\n')
    assert p.returncode == 0, p.stdout + p.stderr
    cfg = envfile(env)
    assert cfg['TELEGRAM_BOT_TOKEN'] == GOOD_TOKEN and cfg['TZ'] == 'Asia/Singapore'
    assert len(cfg['SECRET_KEY']) == 64 and len(cfg['POSTGRES_PASSWORD']) == 32 and cfg['WEB_PORT'].isdigit()
    assert stat.S_IMODE(os.stat(env.app / '.env').st_mode) == 0o600
    assert GOOD_TOKEN not in p.stdout + p.stderr                   # the secret is never echoed
    assert 'Telegram accepted it: @demo_bot' in p.stdout
    order = [c for c in calls if c.startswith('docker compose') and 'run' not in c and 'version' not in c and 'ps' not in c]
    assert order == ['docker compose pull --quiet', 'docker compose up -d']
    assert any('first-run' in c for c in calls)
    assert 'Ready' in p.stdout and 'ABCDE-FGHJK' in p.stdout and 'You are master control' in p.stdout


def test_second_run_does_not_ask_again_and_skips_setup_when_already_set_up(env):
    run(env, f'{GOOD_TOKEN}\n\n')
    (env.state / 'setup_done').touch()
    env.log.write_text('')
    p, calls = run(env, stdin='')
    assert p.returncode == 0 and 'First-time setup' not in p.stdout
    assert not any('first-run' in c for c in calls)
    assert 'docker compose up -d' in calls


def test_prebuilt_images_unavailable_falls_back_to_building_from_source(env):
    p, calls = run(env, f'{GOOD_TOKEN}\n\n', FAKE_PULL_FAILS=1)
    assert p.returncode == 0 and 'building from the included source' in p.stdout
    assert calls.index('docker compose build') < calls.index('docker compose up -d')


def test_a_failed_build_stops_with_a_clear_message(env):
    p, _ = run(env, f'{GOOD_TOKEN}\n\n', FAKE_PULL_FAILS=1, FAKE_BUILD_FAILS=1)
    assert p.returncode == 1 and 'The build failed' in p.stdout


def test_docker_missing_explains_how_to_install_it(env):
    # A PATH with the basics but NO docker (this machine may have a real one in /usr/bin).
    bare = env.tmp / 'bare'
    bare.mkdir()
    for tool in ('bash', 'dirname', 'uname', 'sed', 'grep', 'tr', 'cat', 'head', 'readlink', 'xdg-open'):
        found = shutil.which(tool)
        if found:
            (bare / tool).symlink_to(found)
    p = subprocess.run(['bash', str(env.app / 'launcher' / 'start.sh')], capture_output=True, text=True,
                       env=dict(PATH=str(bare), HOME=str(env.tmp), FM_NO_PAUSE='1'), timeout=30)
    assert p.returncode == 1 and 'Docker is not installed' in p.stdout and 'docker.com' in p.stdout
    assert not (env.app / '.env').exists()                          # nothing is written before Docker is there


def test_an_old_docker_without_compose_is_reported(env):
    p, _ = run(env, '', FAKE_NO_COMPOSE=1)
    assert p.returncode == 1 and 'too old' in p.stdout


def test_docker_that_is_installed_but_stopped_is_waited_for(env):
    p, calls = run(env, f'{GOOD_TOKEN}\n\n', FAKE_DOCKER_DOWN_FOR=2)
    assert p.returncode == 0 and 'not running. Starting it' in p.stdout
    assert sum(c.startswith('docker info') for c in calls) >= 3


def test_docker_that_never_starts_gives_up_with_instructions(env):
    p, _ = run(env, '', FAKE_DOCKER_DOWN_FOR=999)
    assert p.returncode == 1 and 'Docker did not start' in p.stdout


@pytest.mark.parametrize('bad', ['', 'not-a-token', '12345:short'])
def test_a_malformed_token_is_asked_for_again(env, bad):
    p, _ = run(env, f'{bad}\n{GOOD_TOKEN}\n\n') if bad else run(env, '\n')
    if bad:
        assert p.returncode == 0 and 'does not look like a bot token' in p.stdout
        assert envfile(env)['TELEGRAM_BOT_TOKEN'] == GOOD_TOKEN
    else:                                                           # empty answer quits cleanly, writes nothing
        assert p.returncode == 0 and 'Run this again' in p.stdout and not (env.app / '.env').exists()


def test_a_token_telegram_rejects_is_refused_and_asked_again(env):
    bad = '999999999:' + 'B' * 35
    p, _ = run(env, f'{bad}\n{GOOD_TOKEN}\n\n', FAKE_BAD_TOKEN=bad)
    assert 'Telegram rejected that token' in p.stdout and envfile(env)['TELEGRAM_BOT_TOKEN'] == GOOD_TOKEN


def test_offline_setup_still_works_with_a_warning(env):
    p, _ = run(env, f'{GOOD_TOKEN}\n\n', FAKE_OFFLINE=1)
    assert p.returncode == 0 and 'Could not reach Telegram' in p.stdout and (env.app / '.env').exists()


def test_a_busy_port_3000_moves_the_website_to_the_next_free_port(env):
    s = socket.socket()
    try:
        s.bind(('127.0.0.1', 3000)); s.listen(1)
    except OSError:
        pytest.skip('port 3000 is not available to this test')
    try:
        p, _ = run(env, f'{GOOD_TOKEN}\n\n')
        assert envfile(env)['WEB_PORT'] != '3000' and 'Port 3000 is busy' in p.stdout
    finally:
        s.close()


def test_a_site_that_never_comes_up_fails_with_the_logs_hint(env):
    p, _ = run(env, f'{GOOD_TOKEN}\n\n', FAKE_SITE_DOWN=1)
    assert p.returncode == 1 and 'did not become ready' in p.stdout and 'docker compose logs' in p.stdout


def test_a_failed_start_points_at_the_usual_cause(env):
    p, _ = run(env, f'{GOOD_TOKEN}\n\n', FAKE_UP_FAILS=1)
    assert p.returncode == 1 and 'WEB_PORT' in p.stdout


def test_stop_script_stops_without_deleting_data(env):
    e = dict(os.environ, PATH=f'{env.shims}:/usr/bin:/bin', FAKE_LOG=str(env.log), FAKE_STATE=str(env.state),
             FM_NO_PAUSE='1')
    p = subprocess.run(['bash', str(env.app / 'launcher' / 'stop.sh')], capture_output=True, text=True, env=e)
    calls = env.log.read_text().splitlines()
    assert p.returncode == 0 and 'docker compose stop' in calls and 'Your data is kept' in p.stdout
    assert not any(' down' in c or '-v' in c for c in calls)


def test_the_windows_files_are_present_ascii_and_use_crlf_in_the_batch_wrapper():
    for f in ('launcher/start.ps1', 'launcher/stop.ps1'):
        data = open(os.path.join(ROOT, f), 'rb').read()
        data.decode('ascii')                                         # PowerShell 5.1 misreads non-ASCII without a BOM
    bat = open(os.path.join(ROOT, 'Start-Windows.bat'), 'rb').read()
    assert b'\r\n' in bat and b'-ExecutionPolicy Bypass' in bat and b'launcher\\start.ps1' in bat
    ps = open(os.path.join(ROOT, 'launcher/start.ps1')).read()
    assert 'UTF8Encoding($false)' in ps                             # .env without a BOM


def test_the_launcher_scripts_have_valid_syntax_and_the_mac_files_are_executable():
    for f in ('launcher/start.sh', 'launcher/stop.sh', 'Start-Mac.command', 'Stop-Mac.command'):
        assert subprocess.run(['bash', '-n', os.path.join(ROOT, f)]).returncode == 0, f
        assert os.access(os.path.join(ROOT, f), os.X_OK), f'{f} must be executable (double-click)'
