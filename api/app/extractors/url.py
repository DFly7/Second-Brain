import ipaddress
import socket
from urllib.parse import urlparse

import httpx
import trafilatura

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),  # covers Docker default bridge ranges
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Scheme '{parsed.scheme}' is not allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname: {hostname}") from exc
    for _family, _type, _proto, _canonname, sockaddr in resolved:
        addr = ipaddress.ip_address(sockaddr[0])
        if any(addr in net for net in _PRIVATE_NETWORKS):
            raise ValueError(f"Requests to private/internal addresses are not allowed")


async def extract_main_content(url: str) -> str:
    _assert_safe_url(url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        # Block redirects to private addresses
        if resp.is_redirect:
            location = resp.headers.get("location", "")
            _assert_safe_url(location)
            resp = await client.get(location, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    text = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
    return text or resp.text[:8000]
