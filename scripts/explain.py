#!/usr/bin/env python3
"""Manage offline HTML explainers, each on a remembered loopback port.
Commands: serve/stop <slug> or --all; list; check <slug>; shoot <slug>.
Root: EXPLAIN_DIR or ~/.explain. Python 3.10+, Linux/WSL/macOS.
Optional meta.json: {"entry": "other.html", "build": "generated"}.
The build value is descriptive only and is never executed.
"""
import argparse
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import errno
import fcntl
import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(os.environ.get('EXPLAIN_DIR', Path.home() / '.explain')).expanduser().resolve()
STATE = ROOT / '.server'
MARKER = 'explain-serve'
SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,39}')
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def write_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


@contextmanager
def locked():
    STATE.mkdir(parents=True, exist_ok=True)
    STATE.chmod(0o700)
    with (STATE / 'lock').open('w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def folder(slug):
    if not SLUG.fullmatch(slug):
        raise ValueError('invalid slug: use a-z0-9-, starting with a letter or digit, at most 40 characters')
    path = ROOT / slug
    if not path.is_dir() or path.is_symlink():
        raise ValueError(f'create {path}/index.html first (explainer folders cannot be symlinks)')
    return path


def info(slug):
    path = folder(slug)
    meta = read_json(path / 'meta.json') or {}
    if not isinstance(meta, dict):
        raise ValueError('meta.json must be an object')
    entry = meta.get('entry') or 'index.html'
    if not isinstance(entry, str) or Path(entry).is_absolute() or any(p.startswith('.') for p in Path(entry).parts):
        raise ValueError('entry must be a relative HTML path inside the explainer')
    page = (path / entry).resolve()
    if not page.is_relative_to(path) or page.suffix.lower() != '.html':
        raise ValueError('entry must be an HTML file inside the explainer')
    text = page.read_text(errors='replace') if page.is_file() else ''
    title = re.search(r'<title\b[^>]*>(.*?)</title>', text, re.I | re.S)
    return meta, entry, html.unescape(title[1].strip()) if title else slug, text


def slugs():
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir() and not p.is_symlink() and SLUG.fullmatch(p.name)) if ROOT.exists() else []


def cmdline(pid):
    try:
        return Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
    except OSError:
        return subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout


def running(slug):
    st = read_json(STATE / f'{slug}.json')
    if not isinstance(st, dict):
        return None
    try:
        pid, port = st['pid'], st['port']
        if not isinstance(pid, int) or pid <= 0 or not isinstance(port, int) or not 8800 <= port < 9000:
            return None
        os.kill(pid, 0)
        cmd = cmdline(pid)
        if MARKER not in cmd or str(Path(__file__).resolve()) not in cmd or slug not in cmd:
            return None
        with LOCAL.open(f'http://127.0.0.1:{port}/__explain/health', timeout=1) as response:
            health = json.load(response)
        if health == {'marker': MARKER, 'slug': slug, 'pid': pid, 'root': str(ROOT)}:
            return st
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def route(self):
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == '/__explain/health':
            body = json.dumps({'marker': MARKER, 'slug': self.slug, 'pid': os.getpid(), 'root': str(ROOT)}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)
            return False
        real = Path(self.translate_path(self.path)).resolve()
        if any(p.startswith('.') for p in path.split('/') if p) or not real.is_relative_to(Path(self.directory).resolve()):
            self.send_error(404)
            return False
        if path == '/' and self.entry != 'index.html':
            self.send_response(302)
            self.send_header('Location', '/' + urllib.parse.quote(self.entry))
            self.end_headers()
            return False
        return True

    def do_GET(self):
        if self.route():
            super().do_GET()

    def do_HEAD(self):
        if self.route():
            super().do_HEAD()


def run_server(slug, candidates):
    path = folder(slug)
    _, entry, _, _ = info(slug)
    handler = partial(type('ExplainerHandler', (Handler,), {'slug': slug, 'entry': entry}), directory=str(path))
    for port in candidates:
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), handler)
            break
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
    else:
        raise ValueError('no free explainer port')
    state_file = STATE / f'{slug}.json'
    write_json(state_file, {'pid': os.getpid(), 'port': port})
    def terminate(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if (read_json(state_file) or {}).get('pid') == os.getpid():
            state_file.unlink(missing_ok=True)


def serve(slug, quiet=False):
    _, entry, title, page = info(slug)
    if not page:
        raise ValueError(f'{entry}: missing or empty')
    with locked():
        st = running(slug)
        if not st:
            ports = read_json(STATE / 'ports.json') or {}
            mine = ports.get(slug)
            taken = {p for s, p in ports.items() if s != slug}
            candidates = ([mine] if mine else []) + [p for p in range(8800, 9000) if p != mine and p not in taken]
            with (STATE / f'{slug}.log').open('w') as log:
                child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '_run', slug, '--marker', MARKER, '--candidates', ','.join(map(str, candidates))], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True, env={**os.environ, 'EXPLAIN_DIR': str(ROOT)})
            for _ in range(50):
                time.sleep(.1)
                st = running(slug)
                if st or child.poll() is not None:
                    break
            if not st:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=5)
                raise ValueError(f'server failed; see {STATE / (slug + ".log")}')
            if mine and mine != st['port']:
                print(f'note: occupied port {mine}; moved to {st["port"]}')
            ports[slug] = st['port']
            write_json(STATE / 'ports.json', ports)
    if not quiet:
        print(f'{slug}: http://localhost:{st["port"]}/ ({title})')
    return st


def stop(slug):
    folder(slug)
    with locked():
        st = running(slug)
        if not st:
            print(f'{slug}: not running')
            return
        os.kill(st['pid'], signal.SIGTERM)
        for _ in range(30):
            if not running(slug):
                break
            time.sleep(.1)
        else:
            raise ValueError('server did not stop; inspect its log')
        (STATE / f'{slug}.json').unlink(missing_ok=True)
        print(f'{slug}: stopped (port {st["port"]} stays reserved)')


def check(slug):
    meta, entry, _, page = info(slug)
    failures, warnings = [], []
    patterns = [
        (r'''<(?:script|link|img|iframe|source|video|audio|embed|object)\b[^>]*\b(?:src|href|poster|data|srcset)\s*=\s*["']?(?:https?:)?//''', 'remote asset'),
        (r'''(?:@import\s+(?:url\()?|url\()\s*["']?(?:https?:)?//''', 'remote CSS/font'),
        (r'''\b(?:fetch|import)\s*\(\s*["'`](?:https?:)?//''', 'remote fetch/import'),
        (r'''<(?:script|link|img|source)\b[^>]*\b(?:src|href)\s*=\s*["']?/(?!/)''', 'absolute asset path'),
    ]
    for file in folder(slug).rglob('*'):
        if not file.is_file() or file.suffix.lower() not in ('.html', '.css', '.js', '.mjs'):
            continue
        if not file.resolve().is_relative_to(folder(slug)):
            failures.append(f'{file.name}: asset escapes explainer directory')
            continue
        text = file.read_text(errors='replace')
        for pattern, message in patterns:
            for match in re.finditer(pattern, text, re.I):
                line = text.count('\n', 0, match.start()) + 1
                failures.append(f'{file.relative_to(ROOT / slug)}:{line}: {message}')
        if re.search(r'\bTODO\b|\bFIXME\b|lorem ipsum|\[insert', text, re.I):
            warnings.append(f'{file.name}: possible placeholder')
        if file.suffix == '.html' and file.stat().st_size > 150 * 1024 and not meta.get('build'):
            warnings.append(f'{file.name}: over 150 KB; consider generating from data')
    if not page or not re.search(r'<title\b[^>]*>\s*\S', page, re.I):
        failures.append(f'{entry}: missing page or title')
    for name in ('viewport', 'description'):
        if not re.search(r'<meta\b[^>]*name\s*=\s*[\'"]' + name + r'[\'"]', page, re.I):
            warnings.append(f'{entry}: missing {name} metadata')
    for item in failures:
        print('FAIL', item)
    for item in warnings:
        print('warn', item)
    print(f'{slug}: {len(failures)} fail, {len(warnings)} warn')
    return bool(failures)


PROBE = """() => JSON.stringify({overflowX:document.documentElement.scrollWidth>innerWidth+1,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,junk:(document.body.innerText.match(/\\b(undefined|NaN|null)\\b|\\[object Object\\]/g)||[]).slice(0,5)})"""


def shoot(slug):
    if not shutil.which('playwright-cli'):
        print('shoot unavailable: install playwright-cli and its browser, or use an available browser screenshot tool. Visual review has not been performed.')
        return 2
    st = serve(slug, quiet=True)
    url = f'http://localhost:{st["port"]}/'
    out = STATE / 'shots' / slug / str(time.time_ns())
    out.mkdir(parents=True)
    report = {'url': url, 'shots': [], 'probes': [], 'problems': []}
    def pw(*args):
        result = subprocess.run(['playwright-cli', f'-s=explain-{slug}', *args], capture_output=True, text=True, timeout=60, cwd=STATE)
        if result.returncode:
            raise ValueError(f'playwright {args[0]} failed: {(result.stderr or result.stdout)[:500]}')
        return result.stdout
    try:
        pw('open', url)
        for name, width, height in [('desktop', 1280, 800), ('mobile', 390, 844)]:
            pw('resize', str(width), str(height))
            pw('goto', url)
            for full in (False, True):
                path = out / f'{name}{"-full" if full else ""}.png'
                pw('screenshot', f'--filename={path}', *(['--full-page'] if full else []))
                if not path.is_file():
                    raise ValueError(f'screenshot missing: {path}')
                report['shots'].append(str(path))
            report['probes'].append({'viewport': name, 'result': pw('eval', PROBE)})
        report['console'] = pw('console', 'error')
    finally:
        pw('close')
    print(json.dumps(report, indent=2))
    print('Inspect the PNGs and probe/console output before reporting visual review.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('serve', 'stop'):
        p = commands.add_parser(name)
        group = p.add_mutually_exclusive_group(required=True)
        group.add_argument('slug', nargs='?')
        group.add_argument('--all', action='store_true')
    commands.add_parser('list')
    for name in ('check', 'shoot'):
        commands.add_parser(name).add_argument('slug')
    p = commands.add_parser('_run', help=argparse.SUPPRESS)
    p.add_argument('slug')
    p.add_argument('--marker', required=True)
    p.add_argument('--candidates', required=True)
    args = parser.parse_args()
    if args.command == '_run':
        run_server(args.slug, [int(p) for p in args.candidates.split(',') if p])
    elif args.command in ('serve', 'stop'):
        for slug in slugs() if args.all else [args.slug]:
            (serve if args.command == 'serve' else stop)(slug)
    elif args.command == 'list':
        print(f'root: {ROOT}')
        ports = read_json(STATE / 'ports.json') or {}
        for slug in slugs():
            st = running(slug)
            state = f'http://localhost:{st["port"]}/' if st else f'stopped (port {ports[slug]})' if slug in ports else 'never served'
            print(f'- {slug}: {info(slug)[2]}  {state}')
    else:
        return (check if args.command == 'check' else shoot)(args.slug)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        sys.exit(str(error))
