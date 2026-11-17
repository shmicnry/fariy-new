"""Bounded HTTPS collection. DNS addresses are checked then pinned for the TLS connection."""

import http.client
import ipaddress
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit

MAX_BYTES = 1_048_576


def validate_url(url):
    u = urlsplit(url)
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.fragment
        or u.port not in (None, 443)
    ):
        raise ValueError("public_https_url_required")
    if len(url) > 2000:
        raise ValueError("url_too_long")
    return u


def public_addresses(host):
    addresses = sorted(
        {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    )
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("private_network_destination_denied")
    return addresses


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=10, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.ignored += 1
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def fetch_text(url):
    u = validate_url(url)
    address = public_addresses(u.hostname)[0]
    conn = PinnedHTTPS(u.hostname, address)
    started = time.monotonic()
    try:
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        conn.request(
            "GET",
            path,
            headers={
                "User-Agent": "FairySourceReader/0.3",
                "Accept": "text/html,text/plain",
                "Accept-Encoding": "identity",
            },
        )
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError("link_http_status_" + str(response.status))
        kind = response.getheader("Content-Type", "").split(";")[0].strip().lower()
        if kind not in ("text/html", "text/plain", "text/markdown"):
            raise ValueError("unsupported_link_media_type")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("compressed_link_not_supported")
        raw = bytearray()
        while True:
            if time.monotonic() - started > 20:
                raise ValueError("link_deadline_exceeded")
            part = response.read1(16384)
            if not part:
                break
            raw.extend(part)
            if len(raw) > MAX_BYTES:
                raise ValueError("link_too_large")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("link_utf8_required")
        if kind == "text/html":
            parser = ArticleParser()
            parser.feed(text)
            text = "".join(parser.parts)
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if not text or len(text) > 256000:
            raise ValueError("invalid_link_text")
        return text
    finally:
        conn.close()
