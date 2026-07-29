from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from redis import Redis

from app.core.config import settings


class AIReviewDailyLimitExceeded(RuntimeError):
    def __init__(self, *, limit: int, used: int) -> None:
        super().__init__(
            f"Daily AI review limit reached ({used}/{limit} requests)"
        )
        self.limit = limit
        self.used = used


_RESERVE_SCRIPT = """
local current = tonumber(redis.call("GET", KEYS[1]) or "0")
local limit = tonumber(ARGV[1])
if limit <= 0 or current >= limit then
  return {0, current}
end
current = redis.call("INCR", KEYS[1])
if current == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[2])
end
return {1, current}
"""


def reserve_daily_ai_review_request(
    *,
    provider: str,
    client: Redis | None = None,
    now: datetime | None = None,
) -> int:
    limit = settings.AI_REVIEW_DAILY_LIMIT
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    tomorrow = datetime.combine(
        moment.date() + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    seconds_to_midnight = max(
        1, int((tomorrow - moment).total_seconds())
    )
    day_key = f"ai-review-quota:{provider}:{moment.date().isoformat()}"
    redis_client = client or Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    allowed, used = redis_client.eval(
        _RESERVE_SCRIPT,
        1,
        day_key,
        limit,
        seconds_to_midnight,
    )
    used = int(used)
    if not int(allowed):
        raise AIReviewDailyLimitExceeded(limit=limit, used=used)
    return used
