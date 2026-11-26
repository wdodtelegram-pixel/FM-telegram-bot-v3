"""
Build the one-click download:  python tools/make_release.py <version>

Writes dist/FM-Control-<version>.zip (+ .sha256). The zip holds the launchers for Mac and
Windows, the Compose file, and the complete source, so it works two ways: the launcher pulls
the prebuilt images when they are published, and builds from the included source when not.

Only files tracked by git are included, so a stray .env or node_modules can never leak in.
The Mac launchers get their executable bit (a zip made on another system often loses it, and a
.command file that is not executable cannot be double-clicked).
"""
import hashlib
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP = 'FM-Control'
EXCLUDE_PREFIXES = ('tests/', 'tools/', '.github/', 'web/node_modules/', 'web/build/')
EXECUTABLE = ('Start-Mac.command', 'Stop-Mac.command', 'launcher/start.sh', 'launcher/stop.sh',
              'docker/entrypoint.sh')


def tracked_files():
    out = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT)
    return [p for p in out.decode().split('\0') if p]


def normalise_eol(rel, data):
    """Windows scripts get CRLF; shell scripts get LF (a CR in a #! line makes a script unrunnable)."""
    if rel.endswith(('.bat', '.ps1')):
        return data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    if rel.endswith(('.sh', '.command')) or rel == 'docker/entrypoint.sh':
        return data.replace(b'\r\n', b'\n')
    return data


def build(version, out_dir=None):
    if not re.fullmatch(r'v?\d+(\.\d+){0,2}([-.][0-9A-Za-z.]+)?', version):
        raise SystemExit(f'"{version}" does not look like a version (try v1.0.0)')
    out_dir = out_dir or os.path.join(ROOT, 'dist')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'FM-Control-{version}.zip')

    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(tracked_files()):
            if rel.startswith(EXCLUDE_PREFIXES) or rel in ('.gitattributes', '.gitignore'):
                continue
            full = os.path.join(ROOT, rel)
            if not os.path.isfile(full):
                continue
            info = zipfile.ZipInfo(f'{TOP}/{rel}', date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3                              # Unix, so the mode below is honoured
            info.external_attr = ((0o755 if rel in EXECUTABLE else 0o644) << 16)
            with open(full, 'rb') as fh:
                z.writestr(info, normalise_eol(rel, fh.read()))
        info = zipfile.ZipInfo(f'{TOP}/VERSION', date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        z.writestr(info, version + '\n')

    digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()
    with open(path + '.sha256', 'w') as fh:
        fh.write(f'{digest}  {os.path.basename(path)}\n')
    return path, digest


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: python tools/make_release.py <version>   e.g. v1.0.0')
    zip_path, sha = build(sys.argv[1])
    print(f'{zip_path}\nsha256 {sha}')
