"""One-request, token-safe FinMind diagnostics; never used by production batch clients."""
import os
import platform
import re
import socket
import ssl
from urllib.parse import urlparse

import requests

from config import FINMIND_API_URL, FINMIND_BUDGET_PATH, FINMIND_TIMEOUT
from finmind_client import ApiBudget, BudgetReached, token_from_environment

PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def _sanitize(message, token=""):
    text = str(message)
    if token:
        text = text.replace(token, "[REDACTED]")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(token|api[_ -]?key|secret)(\s*[:=]\s*)[^\s,;&]+", r"\1\2[REDACTED]", text)
    text = re.sub(r"https?://[^\s]+", lambda m: re.sub(r"([?&][^=&#]+)=([^&#]*)", r"\1=[REDACTED]", m.group(0)), text)
    return text[:500]


def _chain(exc):
    found, seen = [], set()
    pending = [exc]
    while pending:
        current = pending.pop(0)
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        found.append(current)
        pending.extend([getattr(current, "__cause__", None), getattr(current, "__context__", None)])
        for arg in getattr(current, "args", ()):
            if isinstance(arg, BaseException):
                pending.append(arg)
    return found


def _classify(exc):
    chain = _chain(exc)
    names = [type(item).__name__ for item in chain]
    messages = " ".join(str(item) for item in chain).lower()
    if any(isinstance(item, ssl.SSLError) for item in chain) or "ssl" in messages or "certificate" in messages:
        label = "SSL error"
    elif any(isinstance(item, socket.gaierror) for item in chain) or "name or service not known" in messages or "getaddrinfo failed" in messages or "name resolution" in messages:
        label = "DNS/name resolution error"
    elif "proxyerror" in names or "proxy" in messages:
        label = "proxy error"
    elif any(getattr(item, "winerror", None) for item in chain):
        label = "WinError"
    elif any(isinstance(item, ConnectionResetError) for item in chain) or "connection reset" in messages:
        label = "connection reset"
    elif any(isinstance(item, ConnectionRefusedError) for item in chain) or "connection refused" in messages:
        label = "connection refused"
    elif "remote end closed" in messages or "remote disconnected" in messages or "remote host" in messages:
        label = "remote disconnected"
    elif any(isinstance(item, OSError) for item in chain):
        label = "socket/OS error"
    else:
        label = "connection error"
    return names, label


def run_diagnostic(stock_id="2330", session_factory=requests.Session, budget_factory=ApiBudget,
                   dns_lookup=socket.getaddrinfo, tcp_connect=socket.create_connection,
                   ssl_context_factory=ssl.create_default_context):
    if not str(stock_id).isdigit():
        raise ValueError("stock must contain digits only")
    token = token_from_environment()
    hostname = urlparse(FINMIND_API_URL).hostname
    print(f"Python: {platform.python_version()}")
    print(f"requests: {requests.__version__}")
    print(f"FinMind hostname: {hostname}")
    print(f"FINMIND_TOKEN configured: {bool(token)}")
    print("Proxy environment: " + ", ".join(f"{name}={bool(os.environ.get(name))}" for name in PROXY_NAMES))
    print(f"OpenSSL: {ssl.OPENSSL_VERSION}")
    if not token:
        print("[FAIL] FinMind API request skipped: FINMIND_TOKEN is not configured")
        return {"success": False, "exception_class": "TokenMissing", "message": "token not configured",
                "dns_ok": None, "https_ok": None, "api_requests": 0}

    dns_ok, https_ok = False, False
    try:
        addresses = dns_lookup(hostname, 443, type=socket.SOCK_STREAM)
        dns_ok = bool(addresses)
    except Exception as exc:
        print(f"DNS: failed ({type(exc).__name__}: {_sanitize(exc, token)})")
    else:
        print("DNS: resolved")

    try:
        raw = tcp_connect((hostname, 443), timeout=5)
        try:
            with ssl_context_factory().wrap_socket(raw, server_hostname=hostname) as secured:
                https_ok = bool(secured.getpeercert() or secured.version())
        finally:
            if not raw._closed:
                raw.close()
    except Exception as exc:
        names, label = _classify(exc)
        print(f"Direct HTTPS/TLS: failed ({type(exc).__name__}; {label}; {_sanitize(exc, token)})")
    else:
        print("Direct HTTPS/TLS: established")

    try:
        budget_factory(path=FINMIND_BUDGET_PATH).consume()
    except BudgetReached as exc:
        print(f"[FAIL] API request skipped by shared budget: {_sanitize(exc, token)}")
        return {"success": False, "exception_class": type(exc).__name__, "message": _sanitize(exc, token),
                "dns_ok": dns_ok, "https_ok": https_ok, "api_requests": 0}

    session = session_factory()
    try:
        session.headers.update({"Authorization": f"Bearer {token}"})
        response = session.get(FINMIND_API_URL,
                               params={"dataset": "TaiwanStockMonthRevenue", "data_id": str(stock_id),
                                       "start_date": "2025-01-01"},
                               timeout=min(FINMIND_TIMEOUT, 10))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != 200 or not isinstance(payload.get("data"), list):
            raise ValueError("FinMind returned an unexpected response")
    except Exception as exc:
        names, label = _classify(exc)
        print(f"[FAIL] FinMind API request: {type(exc).__name__}")
        print(f"Sanitized message: {_sanitize(exc, token)}")
        print(f"Underlying exception types: {', '.join(names)}")
        print(f"Connection classification: {label}")
        return {"success": False, "exception_class": type(exc).__name__, "message": _sanitize(exc, token),
                "underlying_types": names, "classification": label,
                "dns_ok": dns_ok, "https_ok": https_ok, "api_requests": 1,
                "http_status": getattr(locals().get("response"), "status_code", None)}
    finally:
        session.close()
    print("[OK] FinMind connection successful")
    return {"success": True, "dns_ok": dns_ok, "https_ok": https_ok, "api_requests": 1,
            "http_status": response.status_code}
