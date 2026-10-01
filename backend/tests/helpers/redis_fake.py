"""In-memory async Redis double for cache tests.

Covers the two shapes the cache layer uses: the HASH/ZSET/pipeline ops of the
semantic cache and the plain ``GET``/``SET``/``INCR`` ops of
``app.core.cache`` (exact-hash entries and version counters). No live Redis.
"""

from __future__ import annotations


class FakeHashRedis:
    """In-memory async Redis double supporting the HASH/ZSET/pipeline ops that
    the semantic cache uses (hgetall/hset/hget/zadd/zcard/zrange/zrem/expire),
    plus the string ops ``app.core.cache`` uses (get/set/incr)."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, str]] = {}
        self._zsets: dict[str, dict[str, float]] = {}
        self._strings: dict[str, str] = {}

    def pipeline(self):
        ops: list[tuple] = []

        class _Pipe:
            def hset(_self, key, field, value):
                ops.append(("hset", key, field, value))
                return _self

            def zadd(_self, key, mapping):
                ops.append(("zadd", key, mapping))
                return _self

            def expire(_self, key, ttl):
                ops.append(("expire", key, ttl))
                return _self

            def hdel(_self, key, *fields):
                ops.append(("hdel", key, fields))
                return _self

            def zrem(_self, key, *members):
                ops.append(("zrem", key, members))
                return _self

            async def execute(_self):
                for op in ops:
                    if op[0] == "hset":
                        _, key, field, value = op
                        self._hashes.setdefault(key, {})[field] = value
                    elif op[0] == "zadd":
                        _, key, mapping = op
                        z = self._zsets.setdefault(key, {})
                        for member, score in mapping.items():
                            z[member] = float(score)
                    elif op[0] == "hdel":
                        _, key, fields = op
                        for field in fields:
                            self._hashes.get(key, {}).pop(field, None)
                    elif op[0] == "zrem":
                        _, key, members = op
                        for member in members:
                            self._zsets.get(key, {}).pop(member, None)
                    # Key expiration is not simulated; tests can keep a ring
                    # alive and verify each entry's independent lifetime.

        return _Pipe()

    async def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    async def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    async def zcard(self, key):
        return len(self._zsets.get(key, {}))

    async def zrange(self, key, start, stop):
        members = sorted(self._zsets.get(key, {}), key=lambda m: self._zsets[key][m])
        return members[start : stop + 1] if stop >= 0 else members[start:]

    # --- string ops (app.core.cache: exact entries + version counters) -------

    async def get(self, key):
        return self._strings.get(key)

    async def set(self, key, value, *, ex=None, nx=None):
        if nx and key in self._strings:
            return None
        self._strings[key] = str(value)
        return "OK"

    async def incr(self, key):
        value = int(self._strings.get(key, "0")) + 1
        self._strings[key] = str(value)
        return value

    async def delete(self, key):
        return 1 if self._strings.pop(key, None) is not None else 0
