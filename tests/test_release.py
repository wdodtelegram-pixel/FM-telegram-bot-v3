import os
import subprocess
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import make_release   # noqa: E402


@pytest.fixture()
def built(tmp_path):
    path, digest = make_release.build('v9.9.9', str(tmp_path))
    return zipfile.ZipFile(path), path, digest


def test_the_zip_has_the_launchers_the_compose_file_and_the_source(built):
    z, _, _ = built
    names = set(z.namelist())
    for need in ('Start-Mac.command', 'Stop-Mac.command', 'Start-Windows.bat', 'Stop-Windows.bat', 'START-HERE.txt',
                 'docker-compose.yml', 'Dockerfile', 'api/Dockerfile', 'web/Dockerfile', 'launcher/start.sh',
                 'launcher/start.ps1', 'core/models.py', 'botapp/main.py', 'api/app.py', 'web/package.json',
                 'migrations/alembic.ini', '.env.example', 'VERSION'):
        assert f'FM-Control/{need}' in names, need


def test_mac_launchers_are_executable_so_they_can_be_double_clicked(built):
    z, _, _ = built
    for name in ('Start-Mac.command', 'Stop-Mac.command', 'launcher/start.sh', 'docker/entrypoint.sh'):
        mode = (z.getinfo(f'FM-Control/{name}').external_attr >> 16) & 0o777
        assert mode == 0o755, f'{name} is {oct(mode)}'
    assert (z.getinfo('FM-Control/README.md').external_attr >> 16) & 0o777 == 0o644


def test_no_secrets_tests_or_build_junk_are_included(built):
    z, _, _ = built
    for n in z.namelist():
        assert not n.endswith('/.env') and '/node_modules/' not in n and '/tests/' not in n
        assert '/.git/' not in n and '/.github/' not in n and '/__pycache__/' not in n
    blob = b''.join(z.read(n) for n in z.namelist() if n.endswith(('.py', '.yml', '.sh', '.ps1', '.txt', '.md')))
    import re
    assert not re.search(rb'[0-9]{8,10}:[A-Za-z0-9_-]{35}', blob)          # no real-looking bot token


def test_the_checksum_matches_the_zip_and_versions_are_validated(built, tmp_path):
    _, path, digest = built
    import hashlib
    assert hashlib.sha256(open(path, 'rb').read()).hexdigest() == digest
    assert open(path + '.sha256').read().startswith(digest)
    with pytest.raises(SystemExit):
        make_release.build('not a version', str(tmp_path))


def test_windows_scripts_are_crlf_and_shell_scripts_lf_inside_the_zip(built):
    z, _, _ = built
    for n in ('Start-Windows.bat', 'Stop-Windows.bat', 'launcher/start.ps1', 'launcher/stop.ps1'):
        data = z.read(f'FM-Control/{n}')
        assert b'\r\n' in data and b'\n' not in data.replace(b'\r\n', b''), n
    for n in ('Start-Mac.command', 'launcher/start.sh', 'docker/entrypoint.sh'):
        assert b'\r' not in z.read(f'FM-Control/{n}'), n
