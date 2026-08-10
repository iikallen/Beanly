from redis.asyncio import Redis

from beanly.core.config.settings import get_settings

redis_client = Redis.from_url(get_settings().redis_url)
