"""Token-scoped, standard-library localhost human asset picker.

No route invokes CapCut, a compiler, a subprocess, or any video editing operation.
Only POST /api/confirm writes choices, after strict validation and explicit UI confirmation.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from selection_session import (CATEGORIES, confirm_session, file_hash, make_session,
                               validate_confirmed_session)

BODY_LIMIT = 1024 * 1024
PREVIEW_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                 '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
                 '.avif': 'image/avif', '.mp4': 'video/mp4', '.webm': 'video/webm',
                 '.mov': 'video/quicktime', '.m4v': 'video/mp4'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json_body(body):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Trùng khóa JSON: ' + key)
            result[key] = value
        return result
    return json.loads(body.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Giá trị số JSON không hợp lệ')))


class PickerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, request_path, library_path, session_path, port=0):
        self.request_path = Path(request_path).resolve()
        self.library_path = Path(library_path).resolve()
        self.session_path = Path(session_path).resolve()
        if len({self.request_path, self.library_path, self.session_path}) != 3:
            raise ValueError('Yêu cầu, thư viện và phiên phải là ba tệp khác nhau')
        self.request_hash = file_hash(self.request_path)
        self.library_hash = file_hash(self.library_path)
        self.request = read_json(self.request_path)
        self.library = read_json(self.library_path)
        pending = make_session(self.request, self.library, self.request_hash, self.library_hash)
        if self.session_path.exists():
            existing = read_json(self.session_path)
            if existing.get('status') == 'confirmed':
                errors = validate_confirmed_session(self.request, self.library, existing,
                    self.request_hash, self.library_hash)
                if errors:
                    raise ValueError('Phiên đã lưu không còn khớp: ' + '; '.join(errors))
            elif existing != pending:
                raise ValueError('Phiên đang chờ không khớp yêu cầu hoặc thư viện này')
            self.session = existing
        else:
            self.session = pending
        self.token = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(18)
        self.lock = threading.Lock()
        self.media = {}
        self.entries = []
        for entry in self.library['entries']:
            item = {key: entry.get(key) for key in ('key', 'name', 'category', 'kind',
                'available', 'supported', 'sources', 'occurrences', 'animation_type', 'missing_paths', 'preview_kind', 'display_name', 'template_kind', 'sample_texts')}
            item['previews'] = []
            for raw in entry.get('preview_files', []) or []:
                if not isinstance(raw, str) or not raw or '://' in raw or raw.startswith(('//', '\\\\')):
                    continue
                path = Path(raw)
                if not path.is_absolute():
                    path = self.library_path.parent / path
                try:
                    path = path.resolve(strict=True)
                    if not path.is_file() or path.suffix.lower() not in PREVIEW_TYPES:
                        continue
                except (OSError, ValueError):
                    continue
                media_id = str(len(self.media))
                self.media[media_id] = (path, PREVIEW_TYPES[path.suffix.lower()])
                item['previews'].append({'url': '/api/media/' + media_id,
                    'type': PREVIEW_TYPES[path.suffix.lower()], 'name': path.name})
            self.entries.append(item)
        super().__init__(('127.0.0.1', int(port)), PickerHandler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)
        self.url = self.origin + '/#token=' + self.token
        if not self.session_path.exists():
            atomic_json(self.session_path, self.session)

    def service_info(self):
        return {'schema': 'capcut-picker-service/1', 'pid': os.getpid(), 'host': '127.0.0.1',
                'port': self.server_port, 'origin': self.origin, 'url': self.url, 'token': self.token,
                'request': str(self.request_path), 'library': str(self.library_path),
                'session': str(self.session_path), 'status': self.session['status']}


class PickerHandler(BaseHTTPRequestHandler):
    server_version = 'CapCutPicker/1'

    def log_message(self, format, *args):
        # URLs may contain the scoped media token; never log request targets.
        pass

    def _headers(self, status, content_type, length=0, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'nonce-" + self.server.nonce +
                         "'; style-src 'nonce-" + self.server.nonce +
                         "'; img-src 'self'; media-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send(self, status, value):
        if status >= 400:
            self._discard_body()
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self._headers(status, 'application/json; charset=utf-8', len(body))
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _discard_body(self):
        """Drain bounded rejected POST bodies before close to avoid Windows RST.

        Header-only or malicious clients cannot make this wait indefinitely. The
        cap applies even if Content-Length claims an arbitrarily large body.
        """
        if self.command != 'POST' or getattr(self, '_body_consumed', False):
            return
        self._body_consumed = True
        try:
            remaining = min(max(0, int(self.headers.get('Content-Length', '0'))), BODY_LIMIT + 64 * 1024)
        except ValueError:
            return
        previous_timeout = self.connection.gettimeout()
        self.connection.settimeout(0.25)
        try:
            while remaining:
                block = self.rfile.read(min(64 * 1024, remaining))
                if not block:
                    break
                remaining -= len(block)
        except OSError:
            pass
        finally:
            self.connection.settimeout(previous_timeout)

    def _route(self):
        try:
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or parsed.fragment:
                return None, None
            return parsed.path, parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
        except ValueError:
            return None, None

    def _host(self):
        if self.headers.get('Host') != '127.0.0.1:' + str(self.server.server_port):
            self._send(403, {'error': 'Địa chỉ Host cục bộ không hợp lệ'})
            return False
        return True

    def _auth(self, query, media=False):
        header = self.headers.get('Authorization', '')
        supplied = header[7:] if header.startswith('Bearer ') else ''
        if media and not supplied and len(query.get('token', [])) == 1:
            supplied = query['token'][0]
        if not supplied or not hmac.compare_digest(supplied, self.server.token):
            self._send(401, {'error': 'Cần mã truy cập của phiên chọn thành phần'})
            return False
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host():
            return
        path, query = self._route()
        if path == '/' and not query:
            html_path = Path(__file__).resolve().parents[1] / 'assets' / 'picker.html'
            body = html_path.read_text(encoding='utf-8').replace('__CSP_NONCE__', self.server.nonce).encode('utf-8')
            self._headers(200, 'text/html; charset=utf-8', len(body))
            if self.command != 'HEAD': self.wfile.write(body)
            return
        if path == '/favicon.ico':
            self._headers(204, 'image/x-icon')
            return
        if not path or not path.startswith('/api/'):
            self._send(404, {'error': 'Đường dẫn không tồn tại'})
            return
        if not self._auth(query, media=path.startswith('/api/media/')):
            return
        if path == '/api/state' and not query:
            self._send(200, {'request': self.server.request,
                'library': {'machine_id': self.server.library['machine_id'], 'entries': self.server.entries},
                'session': self.server.session, 'request_hash': self.server.request_hash,
                'library_hash': self.server.library_hash})
        elif path == '/api/assets':
            self._assets(query)
        elif path.startswith('/api/media/'):
            self._media(path[len('/api/media/'):], query)
        else:
            self._send(404, {'error': 'Đường dẫn không tồn tại'})

    def _assets(self, query):
        allowed = {'category', 'query', 'page', 'page_size', 'animation_type'}
        if set(query) - allowed or any(len(value) != 1 for value in query.values()):
            self._send(400, {'error': 'Bộ lọc thư viện không hợp lệ'})
            return
        try:
            page = int(query.get('page', ['1'])[0])
            size = int(query.get('page_size', ['48'])[0])
            if page < 1 or not 1 <= size <= 100:
                raise ValueError()
        except ValueError:
            self._send(400, {'error': 'Thông số phân trang không hợp lệ'})
            return
        category = query.get('category', [''])[0]
        direction = query.get('animation_type', [''])[0]
        if (category and category not in CATEGORIES) or (direction and direction not in ('in', 'out', 'loop')):
            self._send(400, {'error': 'Loại thành phần hoặc chuyển động không hợp lệ'})
            return
        term = query.get('query', [''])[0].casefold()
        entries = [entry for entry in self.server.entries if
            (not category or entry['category'] == category) and
            (not direction or entry['animation_type'] == direction) and
            (not term or term in (str(entry.get('display_name') or '') + ' ' + str(entry.get('name') or '') + ' ' + entry['key'] + ' ' +
                                 json.dumps(entry.get('sources'), ensure_ascii=False)).casefold())]
        self._send(200, {'entries': entries[(page - 1) * size:page * size],
                         'total': len(entries), 'page': page, 'page_size': size})

    def _media(self, media_id, query):
        if set(query) - {'token'} or any(len(value) != 1 for value in query.values()) or media_id not in self.server.media:
            self._send(404, {'error': 'Tệp xem trước không tồn tại'})
            return
        path, content_type = self.server.media[media_id]
        try:
            with path.open('rb') as stream:
                size = os.fstat(stream.fileno()).st_size
                start, end, status = 0, size - 1, 200
                requested = self.headers.get('Range')
                if requested:
                    match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
                    if not match or not any(match.groups()) or size == 0:
                        self._send(416, {'error': 'Phạm vi byte không hợp lệ'})
                        return
                    left, right = match.groups()
                    if left:
                        start = int(left)
                        end = min(int(right), size - 1) if right else size - 1
                    else:
                        start = max(0, size - int(right))
                    if start > end or start >= size:
                        self._send(416, {'error': 'Phạm vi byte nằm ngoài tệp xem trước'})
                        return
                    status = 206
                length = max(0, end - start + 1)
                extra = {'Accept-Ranges': 'bytes'}
                if status == 206: extra['Content-Range'] = f'bytes {start}-{end}/{size}'
                self._headers(status, content_type, length, extra)
                if self.command == 'HEAD': return
                stream.seek(start)
                remaining = length
                while remaining:
                    chunk = stream.read(min(256 * 1024, remaining))
                    if not chunk: break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (FileNotFoundError, PermissionError):
            self._send(404, {'error': 'Tệp xem trước không còn trên máy'})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not self._host(): return
        path, query = self._route()
        if path != '/api/confirm' or query:
            self._send(404, {'error': 'Đường dẫn không tồn tại'})
            return
        if not self._auth(query): return
        if self.headers.get('Origin') != self.server.origin or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._send(403, {'error': 'Phải xác nhận từ đúng cửa sổ chọn thành phần'})
            return
        if self.headers.get('Transfer-Encoding'):
            self._send(400, {'error': 'Không hỗ trợ mã hóa truyền này'})
            return
        try:
            length = int(self.headers.get('Content-Length', '-1'))
        except ValueError:
            length = -1
        if length < 0:
            self._send(411, {'error': 'Thiếu kích thước Content-Length'})
            return
        if length > BODY_LIMIT:
            self.close_connection = True
            self._send(413, {'error': 'Dữ liệu xác nhận vượt quá 1 MiB'})
            return
        if self.headers.get_content_type() != 'application/json':
            self._send(415, {'error': 'Cần dữ liệu kiểu application/json'})
            return
        self.connection.settimeout(10)
        try:
            body = self.rfile.read(length)
            self._body_consumed = True
            payload = _json_body(body)
        except (ValueError, UnicodeError, TimeoutError, RecursionError):
            self._send(400, {'error': 'Dữ liệu JSON xác nhận không hợp lệ'})
            return
        if not isinstance(payload, dict) or set(payload) != {'choices', 'request_hash', 'library_hash'}:
            self._send(400, {'error': 'Cần choices, request_hash và library_hash'})
            return
        with self.server.lock:
            try:
                stale = (payload['request_hash'] != self.server.request_hash or
                         payload['library_hash'] != self.server.library_hash or
                         file_hash(self.server.request_path) != self.server.request_hash or
                         file_hash(self.server.library_path) != self.server.library_hash)
            except OSError:
                stale = True
            if stale:
                self._send(409, {'error': 'Yêu cầu hoặc thư viện đã thay đổi; hãy mở phiên chọn thành phần mới'})
                return
            if self.server.session['status'] == 'confirmed':
                self._send(409, {'error': 'Phiên này đã được xác nhận'})
                return
            try:
                confirmed = confirm_session(self.server.request, self.server.library, payload['choices'],
                    self.server.request_hash, self.server.library_hash)
            except ValueError as error:
                self._send(422, {'error': str(error)})
                return
            try:
                atomic_json(self.server.session_path, confirmed)
            except OSError:
                self._send(500, {'error': 'Không lưu được lựa chọn; phiên vẫn chờ xác nhận'})
                return
            self.server.session = confirmed
            self._send(200, {'session': confirmed})


def create_server(request_path, library_path, session_path, port=0):
    return PickerServer(request_path, library_path, session_path, port)


def open_popup(url):
    """Open a separate app window when a local Chromium browser is installed."""
    candidates = []
    if sys.platform == 'win32':
        for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            base = os.environ.get(env)
            if base:
                candidates.extend([str(Path(base) / 'Microsoft/Edge/Application/msedge.exe'),
                                   str(Path(base) / 'Google/Chrome/Application/chrome.exe')])
    else:
        candidates.extend(filter(None, [shutil.which(name) for name in ('chromium', 'chromium-browser', 'google-chrome')]))
    for executable in candidates:
        if Path(executable).is_file():
            subprocess.Popen([executable, '--new-window', '--app=' + url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    webbrowser.open(url, new=1, autoraise=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    serve = commands.add_parser('serve', help='Start a local human-selection popup')
    for option in ('request', 'library', 'session'):
        serve.add_argument('--' + option, required=True, type=Path)
    serve.add_argument('--port', type=int, default=0)
    serve.add_argument('--no-open', action='store_true')
    serve.add_argument('--state', type=Path, help='Write URL/token service information for the caller')
    for name in ('status', 'wait'):
        command = commands.add_parser(name)
        command.add_argument('--session', required=True, type=Path)
        if name == 'wait':
            command.add_argument('--timeout', type=float, default=60)
            command.add_argument('--interval', type=float, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command in ('status', 'wait'):
            if args.command == 'wait' and not (0 <= args.timeout <= 60 and 0.05 <= args.interval <= 5):
                raise ValueError('Thời gian chờ phải từ 0 đến 60 giây, khoảng kiểm tra từ 0.05 đến 5 giây')
            deadline = time.monotonic() + (args.timeout if args.command == 'wait' else 0)
            while True:
                session = read_json(args.session)
                if session.get('status') == 'confirmed' or time.monotonic() >= deadline:
                    print(json.dumps(session, ensure_ascii=False))
                    return 0 if session.get('status') == 'confirmed' else 2
                time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
        if args.state and args.state.resolve() in {args.request.resolve(), args.library.resolve(), args.session.resolve()}:
            raise ValueError('Thông tin dịch vụ phải lưu vào tệp riêng')
        server = create_server(args.request, args.library, args.session, args.port)
        try:
            info = server.service_info()
            if args.state: atomic_json(args.state, info)
            print(json.dumps(info, ensure_ascii=False), flush=True)
            if not args.no_open: open_popup(server.url)
            server.serve_forever(poll_interval=0.25)
        finally:
            server.server_close()
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
