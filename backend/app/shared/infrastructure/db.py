"""Transport-safe database dependency aliases."""

from app.core.db import async_session, get_db

get_request_db = get_db
open_background_session = async_session

__all__ = ["get_request_db", "open_background_session"]
