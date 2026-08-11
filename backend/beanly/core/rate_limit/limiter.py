import hashlib
from dataclasses import dataclass

from redis.asyncio import Redis

_CHECK_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int
    remaining: int


class RedisRateLimiter:
    def __init__(self, redis: Redis, *, prefix: str = "beanly:rate-limit") -> None:
        self.redis = redis
        self.prefix = prefix

    async def check(
        self,
        scope: str,
        identity: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        if limit < 1 or window_seconds < 1:
            raise ValueError("Rate limit and window must be positive")
        digest = hashlib.sha256(identity.encode()).hexdigest()
        key = f"{self.prefix}:{scope}:{digest}"
        result = await self.redis.eval(_CHECK_SCRIPT, 1, key, window_seconds)
        count, ttl = int(result[0]), max(1, int(result[1]))
        return RateLimitDecision(
            allowed=count <= limit,
            retry_after=ttl,
            remaining=max(0, limit - count),
        )
