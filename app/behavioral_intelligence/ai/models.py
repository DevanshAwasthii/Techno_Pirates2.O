from __future__ import annotations

from dataclasses import asdict, dataclass
from ipaddress import ip_address, ip_network
import math
from urllib.parse import urlsplit, urlunsplit

LAN_WARNING = 'The structured interest summary leaves this computer and is sent to another device on your network. No raw records or messages are sent.'
PRIVATE_LANS = tuple(ip_network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def validate_endpoint(url, allow_lan_model=False):
    if not isinstance(url, str) or type(allow_lan_model) is not bool or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError('Expected an HTTP endpoint and a boolean LAN setting')
    try:
        p = urlsplit(url)
        host, port = p.hostname, p.port
    except ValueError:
        raise ValueError('Invalid model endpoint') from None
    if (p.scheme not in {'http', 'https'} or p.username is not None or p.password is not None
            or p.query or p.fragment or p.path.rstrip('/') not in {'', '/v1'} or not host
            or port is not None and not 1 <= port <= 65535):
        raise ValueError('Use an HTTP(S) local model base URL, optionally ending in /v1')
    local = host in {'localhost', '127.0.0.1', '::1'}
    if not local:
        try:
            address = ip_address(host)
        except ValueError:
            raise ValueError('Only loopback or explicitly enabled RFC1918 literal addresses are allowed') from None
        if not allow_lan_model or not any(address in net for net in PRIVATE_LANS):
            raise ValueError('LAN models require allow_lan_model=true and an RFC1918 IPv4 address')
    # Pin localhost to a literal loopback; never consult DNS/hosts for model destinations.
    host = '127.0.0.1' if host == 'localhost' else f'[{host}]' if ':' in host else host
    return urlunsplit((p.scheme, host + (f':{port}' if port else ''), p.path.rstrip('/'), '', ''))


@dataclass(frozen=True)
class AIConfig:
    enabled: bool = False
    base_url: str = 'http://127.0.0.1:8000/v1'
    model: str = ''
    timeout_seconds: float = 45.0
    max_tokens: int = 900
    allow_lan_model: bool = False

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.allow_lan_model) is not bool:
            raise ValueError('enabled and allow_lan_model must be booleans')
        validate_endpoint(self.base_url, self.allow_lan_model)
        if not isinstance(self.model, str) or len(self.model) > 200 or any(ord(c) < 32 for c in self.model):
            raise ValueError('Invalid model name')
        if type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds) or not .1 <= self.timeout_seconds <= 300:
            raise ValueError('Timeout must be between 0.1 and 300 seconds')
        if type(self.max_tokens) is not int or not 32 <= self.max_tokens <= 8192:
            raise ValueError('max_tokens must be an integer between 32 and 8192')

    @property
    def warning(self):
        host = urlsplit(validate_endpoint(self.base_url, self.allow_lan_model)).hostname
        return '' if host in {'127.0.0.1', '::1'} else LAN_WARNING

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('AI settings must be an object')
        return cls(**value)


@dataclass(frozen=True)
class AIHealth:
    state: str
    model: str = ''
    detail: str = ''

    def to_dict(self):
        return asdict(self)
