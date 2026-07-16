# -*- coding: utf-8 -*-
"""Localhost HLS proxy for BunnyCDN streams.

Google TV / InputStream Adaptive often fail on remote Bunny playlists because:
  - AES key and segment requests need Referer: tamildhool.tech
  - segments are named .dts (MPEG-TS)

This proxy serves a rewritten playlist from 127.0.0.1, the AES key from memory,
and proxies segments as .ts with the correct Bunny headers.
"""

from __future__ import annotations

import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from constants import ADDON_ID, USER_AGENT

_LOCK = threading.RLock()
_SERVER = None
_PORT = 0
_SESSION = {
    'key': b'',
    'segments': [],
    'headers': {},
    'target_duration': 4,
    'extinf': [],
}


def _log(message):
    try:
        import xbmc
        xbmc.log(f'[{ADDON_ID}] {message}', xbmc.LOGINFO)
    except Exception:
        sys.stderr.write(f'[{ADDON_ID}] {message}\n')


def _log_error(message):
    try:
        import xbmc
        xbmc.log(f'[{ADDON_ID}] {message}', xbmc.LOGERROR)
    except Exception:
        sys.stderr.write(f'[{ADDON_ID}] ERROR {message}\n')


def _http_get(url, headers, timeout=20):
    request = urllib.request.Request(url, headers=headers)
    context = None
    try:
        import ssl
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    except Exception:
        context = None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.read()
    except TypeError:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()


class _BunnyHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        return

    def _send(self, code, body, content_type):
        if not isinstance(body, (bytes, bytearray)):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path or '/'

        with _LOCK:
            key = _SESSION.get('key') or b''
            segments = list(_SESSION.get('segments') or [])
            headers = dict(_SESSION.get('headers') or {})
            target = int(_SESSION.get('target_duration') or 4)
            extinf = list(_SESSION.get('extinf') or [])

        if path in ('/', '/index.m3u8', '/playlist.m3u8'):
            lines = [
                '#EXTM3U',
                '#EXT-X-VERSION:3',
                f'#EXT-X-TARGETDURATION:{max(1, target)}',
                '#EXT-X-MEDIA-SEQUENCE:0',
                '#EXT-X-PLAYLIST-TYPE:VOD',
                f'#EXT-X-KEY:METHOD=AES-128,URI="http://127.0.0.1:{_PORT}/key"',
            ]
            for idx, _seg in enumerate(segments):
                duration = extinf[idx] if idx < len(extinf) else '4.000000'
                lines.append(f'#EXTINF:{duration},')
                lines.append(f'http://127.0.0.1:{_PORT}/seg/{idx}.ts')
            lines.append('#EXT-X-ENDLIST')
            self._send(200, '\n'.join(lines) + '\n', 'application/vnd.apple.mpegurl')
            return

        if path == '/key':
            if not key:
                self._send(404, b'missing key', 'text/plain')
                return
            self._send(200, key, 'application/octet-stream')
            return

        if path.startswith('/seg/'):
            name = path.rsplit('/', 1)[-1]
            try:
                idx = int(name.split('.', 1)[0])
            except ValueError:
                self._send(404, b'bad segment', 'text/plain')
                return
            if idx < 0 or idx >= len(segments):
                self._send(404, b'unknown segment', 'text/plain')
                return
            try:
                data = _http_get(segments[idx], headers, timeout=25)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                _log_error(f'Bunny proxy segment {idx} failed: {exc}')
                self._send(502, b'segment fetch failed', 'text/plain')
                return
            self._send(200, data, 'video/mp2t')
            return

        self._send(404, b'not found', 'text/plain')


def ensure_proxy_started():
    """Start the localhost proxy if needed. Returns port or 0 on failure."""
    global _SERVER, _PORT
    with _LOCK:
        if _SERVER is not None and _PORT:
            return _PORT
        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), _BunnyHandler)
            port = int(server.server_address[1])
        except OSError as exc:
            _log_error(f'Bunny proxy bind failed: {exc}')
            return 0

        thread = threading.Thread(target=server.serve_forever, name='bunny-proxy', daemon=True)
        thread.start()
        _SERVER = server
        _PORT = port
        _log(f'Bunny proxy listening on 127.0.0.1:{port}')
        return port


def stop_proxy():
    global _SERVER, _PORT
    with _LOCK:
        server = _SERVER
        _SERVER = None
        _PORT = 0
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass


def register_bunny_session(key_bytes, segment_urls, headers=None, target_duration=4, extinf=None):
    """Store one active Bunny session and return the local playlist URL."""
    port = ensure_proxy_started()
    if not port:
        return ''
    with _LOCK:
        _SESSION['key'] = key_bytes or b''
        _SESSION['segments'] = list(segment_urls or [])
        _SESSION['headers'] = dict(headers or {})
        _SESSION['target_duration'] = int(target_duration or 4)
        _SESSION['extinf'] = list(extinf or [])
    return f'http://127.0.0.1:{port}/index.m3u8'


def is_bunny_proxy_url(url):
    lower = (url or '').lower()
    return lower.startswith('http://127.0.0.1:') and (
        '/index.m3u8' in lower or '/playlist.m3u8' in lower
    )


def default_bunny_headers(referer='https://www.tamildhool.tech/'):
    return {
        'User-Agent': USER_AGENT,
        'Accept': '*/*',
        'Referer': referer or 'https://www.tamildhool.tech/',
        'Origin': 'https://www.tamildhool.tech',
    }
