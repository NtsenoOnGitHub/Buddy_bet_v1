"""Shared SlowAPI rate limiter instance.

Import ``limiter`` here so main.py and all endpoint modules reference the same
object. The limiter uses the client IP address as the key by default.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
