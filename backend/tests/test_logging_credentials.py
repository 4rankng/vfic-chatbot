"""Transport loggers must never print credential-bearing request URLs."""

import logging

from app.core.logging import silence_credential_bearing_transport_loggers


def test_transport_loggers_are_silenced_below_warning():
    for name in ("httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.INFO)

    silence_credential_bearing_transport_loggers()

    for name in ("httpx", "httpx2"):
        logger = logging.getLogger(name)
        assert logger.level == logging.WARNING
        # INFO is where httpx prints "HTTP Request: POST <url-with-token>".
        assert not logger.isEnabledFor(logging.INFO)


def test_worker_entrypoint_applies_the_same_guard():
    """The RQ workers make the Send API calls, so the guard must reach them.

    The API process got this via setup_logging(); the worker used a bare
    basicConfig and leaked the Meta Page access token on every outbound send.
    """
    import inspect

    from app.workers import run_worker

    source = inspect.getsource(run_worker.main)
    assert "silence_credential_bearing_transport_loggers" in source
