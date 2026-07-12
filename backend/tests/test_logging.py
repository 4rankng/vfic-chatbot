"""Security-sensitive logging configuration tests."""

import logging

from app.core.logging import setup_logging


def test_setup_logging_suppresses_httpx_request_urls():
    httpx_logger = logging.getLogger("httpx")
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    root_logger = logging.getLogger()
    previous_level = httpx_logger.level
    previous_uvicorn_access_level = uvicorn_access_logger.level
    previous_root_level = root_logger.level
    previous_handlers = root_logger.handlers[:]
    try:
        setup_logging()
        assert httpx_logger.level == logging.WARNING
    finally:
        httpx_logger.setLevel(previous_level)
        uvicorn_access_logger.setLevel(previous_uvicorn_access_level)
        root_logger.handlers[:] = previous_handlers
        root_logger.setLevel(previous_root_level)
