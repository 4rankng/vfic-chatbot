"""Authorization roles owned by the identity domain."""

from enum import Enum


class Role(str, Enum):
    admin = "admin"
    recruiter = "recruiter"

