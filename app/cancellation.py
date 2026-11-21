"""Cooperative per-worker cancellation, shared by pipeline, parsers and analysis."""
from contextlib import contextmanager
from contextvars import ContextVar

_event = ContextVar("audit_cancel", default=None)


class Cancelled(Exception):
    pass


def check_cancel():
    event = _event.get()
    if event is not None and event.is_set():
        raise Cancelled()


@contextmanager
def cancellation(event):
    token = _event.set(event)
    try:
        check_cancel()
        yield
        check_cancel()
    finally:
        _event.reset(token)
