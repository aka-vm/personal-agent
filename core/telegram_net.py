"""
Reach Telegram despite ISP DNS poisoning.

Some Indian ISPs (e.g. Airtel) block Telegram by poisoning DNS — `api.telegram.org`
resolves to a "restricted" sinkhole, and plain DNS to 1.1.1.1/8.8.8.8 (port 53) is
intercepted too. But DoH (DNS-over-HTTPS, port 443) can't be tampered with. So we
resolve the real IP over DoH and pin it via getaddrinfo; HTTPS still uses the
correct SNI/cert because the hostname is unchanged.

Call install() once at startup. This defeats DNS-level blocks. A full IP-level
block still needs a tunnel/exit node — but Airtel's Telegram block is usually DNS.
"""
import socket
import json
import time
import urllib.request

_TG_HOSTS = {"api.telegram.org"}
_DOH = "https://1.1.1.1/dns-query"
_TTL = 300
_cache = {}  # host -> (ip, ts)


def _doh_resolve(host):
    url = f"{_DOH}?name={host}&type=A"
    req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read())
    ips = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
    return ips[0] if ips else None


def _resolve(host):
    now = time.time()
    c = _cache.get(host)
    if c and now - c[1] < _TTL:
        return c[0]
    try:
        ip = _doh_resolve(host)
    except Exception:
        ip = None
    if ip:
        _cache[host] = (ip, now)
    return ip


_orig_getaddrinfo = socket.getaddrinfo


def _patched(host, *args, **kwargs):
    if host in _TG_HOSTS:
        ip = _resolve(host)
        if ip:
            return _orig_getaddrinfo(ip, *args, **kwargs)
    return _orig_getaddrinfo(host, *args, **kwargs)


_installed = False


def install():
    """Idempotent: route api.telegram.org lookups through DoH."""
    global _installed
    if not _installed:
        socket.getaddrinfo = _patched
        _installed = True
