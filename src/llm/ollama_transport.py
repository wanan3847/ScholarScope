"""Serialize local inference in this process, including time spent waiting."""
import threading
import time
import httpx

_gate = threading.BoundedSemaphore(1)


def chat_response(url, payload, headers, timeout):
    deadline = time.monotonic() + timeout
    if not _gate.acquire(timeout=timeout):
        raise TimeoutError("Local inference is busy")
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Local inference budget exhausted")
        with httpx.Client(timeout=remaining, proxy=None, trust_env=False) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    finally:
        _gate.release()
