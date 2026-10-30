from __future__ import annotations

from typing import Optional, Tuple

from app.core.config import settings
from app.services.idempotency import get_redis_client

# Atomic Redis Lua Script for Dual RPM + TPM Rate Limiting (Section 1.3)
# KEYS[1] = RPM counter key
# KEYS[2] = TPM counter key
# ARGV[1] = estimated_tokens (int)
# ARGV[2] = rpm_limit (int)
# ARGV[3] = tpm_limit (int)
# ARGV[4] = window_ms (int)
# Returns: { allowed (1 or 0), retry_after_ms (int) }
_GROQ_DUAL_BUCKET_LUA_SCRIPT = """
local rpm_key = KEYS[1]
local tpm_key = KEYS[2]

local req_tokens = tonumber(ARGV[1])
local rpm_limit = tonumber(ARGV[2])
local tpm_limit = tonumber(ARGV[3])
local window_ms = tonumber(ARGV[4])

local current_rpm = tonumber(redis.call("GET", rpm_key) or "0")
local current_tpm = tonumber(redis.call("GET", tpm_key) or "0")

if (current_rpm + 1 > rpm_limit) or (current_tpm + req_tokens > tpm_limit) then
    local rpm_pttl = redis.call("PTTL", rpm_key)
    local tpm_pttl = redis.call("PTTL", tpm_key)
    local retry_ms = math.max(rpm_pttl, tpm_pttl)
    if retry_ms <= 0 then
        retry_ms = window_ms
    end
    return {0, retry_ms}
end

local new_rpm = redis.call("INCR", rpm_key)
if new_rpm == 1 or redis.call("PTTL", rpm_key) < 0 then
    redis.call("PEXPIRE", rpm_key, window_ms)
end

local new_tpm = redis.call("INCRBY", tpm_key, req_tokens)
if new_tpm == req_tokens or redis.call("PTTL", tpm_key) < 0 then
    redis.call("PEXPIRE", tpm_key, window_ms)
end

return {1, 0}
"""


def _build_rate_limit_keys(scope: str = "default") -> Tuple[str, str]:
    clean_scope = scope.strip() or "default"
    return (
        f"groq:ratelimit:{clean_scope}:rpm",
        f"groq:ratelimit:{clean_scope}:tpm",
    )


async def acquire_groq_rate_limit(
    estimated_tokens: int,
    rpm_limit: Optional[int] = None,
    tpm_limit: Optional[int] = None,
    *,
    scope: str = "default",
    window_seconds: float = 60.0,
) -> Tuple[bool, float]:
    """
    Atomically check and consume 1 request and `estimated_tokens` against the distributed
    Redis Lua RPM/TPM token bucket.
    Returns `(allowed: bool, retry_after_seconds: float)`.
    """
    effective_rpm = (
        rpm_limit
        if rpm_limit is not None
        else (settings.LLM_RPM_LIMIT or settings.GROQ_RPM_LIMIT)
    )
    effective_tpm = (
        tpm_limit
        if tpm_limit is not None
        else (settings.LLM_TPM_LIMIT or settings.GROQ_TPM_LIMIT)
    )
    tokens_to_reserve = max(1, int(estimated_tokens))
    window_ms = max(100, int(window_seconds * 1000))

    rpm_key, tpm_key = _build_rate_limit_keys(scope)
    redis_client = get_redis_client()

    result = await redis_client.eval(
        _GROQ_DUAL_BUCKET_LUA_SCRIPT,
        2,
        rpm_key,
        tpm_key,
        tokens_to_reserve,
        effective_rpm,
        effective_tpm,
        window_ms,
    )

    allowed_flag = int(result[0]) == 1
    retry_after_ms = int(result[1])
    retry_after_seconds = round(retry_after_ms / 1000.0, 3) if not allowed_flag else 0.0
    return allowed_flag, retry_after_seconds


async def reset_groq_rate_limit(scope: str = "default") -> None:
    """Clear the RPM and TPM counters for the given scope in Redis."""
    rpm_key, tpm_key = _build_rate_limit_keys(scope)
    redis_client = get_redis_client()
    await redis_client.delete(rpm_key, tpm_key)

