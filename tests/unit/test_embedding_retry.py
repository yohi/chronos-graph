"""Tests for unified embedding retry configuration (SPEC.md §16.5 E-2)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock

import httpx
import pytest
import tenacity

from context_store.embedding.retry_config import (
    EmbeddingRetryPolicy,
    parse_retry_after_header,
    should_retry_embedding,
)

# ---------------------------------------------------------------------------
# parse_retry_after_header
# ---------------------------------------------------------------------------


class TestParseRetryAfterHeader:
    """``parse_retry_after_header`` のテスト。"""

    def test_decimal_integer_seconds(self) -> None:
        """秒数表記がそのまま float として返ることを検証。"""
        assert parse_retry_after_header("120") == 120.0

    def test_decimal_zero(self) -> None:
        """0 秒指定が 0.0 として返ることを検証。"""
        assert parse_retry_after_header("0") == 0.0

    def test_decimal_negative_clamped_to_zero(self) -> None:
        """負の秒数指定が 0.0 にクランプされることを検証。"""
        assert parse_retry_after_header("-10") == 0.0
        assert parse_retry_after_header("-0.1") == 0.0

    def test_decimal_with_decimal_point(self) -> None:
        """小数点を含む値もパース可能なことを検証。"""
        assert parse_retry_after_header("1.5") == 1.5

    def test_http_date_future(self) -> None:
        """未来の HTTP-date が正の秒数として返ることを検証。"""
        future = datetime.now(timezone.utc) + timedelta(seconds=60)
        header = format_datetime(future, usegmt=True)
        delay = parse_retry_after_header(header)
        assert delay is not None
        # 実行時刻によるブレを許容
        assert 50.0 <= delay <= 70.0

    def test_http_date_past_returns_zero(self) -> None:
        """過去の HTTP-date は 0.0 にクランプされることを検証。"""
        past = datetime.now(timezone.utc) - timedelta(seconds=60)
        header = format_datetime(past, usegmt=True)
        assert parse_retry_after_header(header) == 0.0

    def test_none_returns_none(self) -> None:
        """``None`` は ``None`` を返すことを検証。"""
        assert parse_retry_after_header(None) is None

    def test_empty_string_returns_none(self) -> None:
        """空文字列は ``None`` を返すことを検証。"""
        assert parse_retry_after_header("") is None
        assert parse_retry_after_header("   ") is None

    def test_invalid_string_returns_none(self) -> None:
        """パース不能な文字列は ``None`` を返すことを検証。"""
        assert parse_retry_after_header("not-a-number") is None
        assert parse_retry_after_header("invalid date format") is None


# ---------------------------------------------------------------------------
# should_retry_embedding
# ---------------------------------------------------------------------------


class TestShouldRetryEmbedding:
    """``should_retry_embedding`` のテスト。"""

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_http_status_error_retryable(self, status_code: int) -> None:
        """429 / 5xx ステータスはリトライ対象であることを検証。"""
        exc = httpx.HTTPStatusError(
            f"status {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
        assert should_retry_embedding(exc) is True

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
    def test_http_status_error_client_not_retryable(self, status_code: int) -> None:
        """4xx (429 を除く) ステータスはリトライ対象外であることを検証。"""
        exc = httpx.HTTPStatusError(
            f"status {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
        assert should_retry_embedding(exc) is False

    def test_timeout_exception_retryable(self) -> None:
        """``httpx.TimeoutException`` はリトライ対象であることを検証。"""
        assert should_retry_embedding(httpx.TimeoutException("timeout")) is True

    def test_connect_error_retryable(self) -> None:
        """``httpx.ConnectError`` はリトライ対象であることを検証。"""
        assert should_retry_embedding(httpx.ConnectError("connection refused")) is True

    def test_asyncio_timeout_error_retryable(self) -> None:
        """Python 3.11+ で ``asyncio.TimeoutError`` ≡ ``TimeoutError`` がリトライ対象。"""
        assert should_retry_embedding(TimeoutError("timed out")) is True
        # asyncio.TimeoutError is now alias for TimeoutError in Python 3.11+
        assert should_retry_embedding(asyncio.TimeoutError("timed out")) is True

    def test_custom_exception_with_status_code_retryable(self) -> None:
        """``status_code`` 属性を持つ汎用例外 (LiteLLM 等) のリトライ判定を検証。"""

        class FakeSDKError(Exception):
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

        assert should_retry_embedding(FakeSDKError(429)) is True
        assert should_retry_embedding(FakeSDKError(500)) is True
        assert should_retry_embedding(FakeSDKError(503)) is True
        assert should_retry_embedding(FakeSDKError(400)) is False
        assert should_retry_embedding(FakeSDKError(401)) is False

    def test_value_error_not_retryable(self) -> None:
        """``ValueError`` 等の検証エラーはリトライ対象外であることを検証。"""
        assert should_retry_embedding(ValueError("bad input")) is False

    def test_runtime_error_not_retryable(self) -> None:
        """``RuntimeError`` はリトライ対象外であることを検証。"""
        assert should_retry_embedding(RuntimeError("unexpected")) is False


# ---------------------------------------------------------------------------
# EmbeddingRetryPolicy basic
# ---------------------------------------------------------------------------


class TestEmbeddingRetryPolicyDefaults:
    """``EmbeddingRetryPolicy`` のデフォルト値検証。"""

    def test_default_values(self) -> None:
        """デフォルト値が SPEC.md §16.5 E-2 の要求を満たすことを検証。"""
        policy = EmbeddingRetryPolicy()
        assert policy.max_attempts == 3
        assert policy.min_wait_seconds == 1.0
        assert policy.max_wait_seconds == 10.0
        assert policy.per_attempt_timeout_seconds == 10.0

    def test_custom_values(self) -> None:
        """明示的に指定した値が反映されることを検証。"""
        policy = EmbeddingRetryPolicy(
            max_attempts=5,
            min_wait_seconds=0.5,
            max_wait_seconds=30.0,
            per_attempt_timeout_seconds=20.0,
        )
        assert policy.max_attempts == 5
        assert policy.min_wait_seconds == 0.5
        assert policy.max_wait_seconds == 30.0
        assert policy.per_attempt_timeout_seconds == 20.0


class TestEmbeddingRetryPolicyFromEnv:
    """``EmbeddingRetryPolicy.from_env`` のテスト。"""

    def test_from_env_reads_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """環境変数からすべての値を読み込めることを検証。"""
        monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "5")
        monkeypatch.setenv("EMBEDDING_MIN_WAIT", "0.5")
        monkeypatch.setenv("EMBEDDING_MAX_WAIT", "30.0")
        monkeypatch.setenv("EMBEDDING_PER_ATTEMPT_TIMEOUT", "15.0")

        policy = EmbeddingRetryPolicy.from_env()
        assert policy.max_attempts == 5
        assert policy.min_wait_seconds == 0.5
        assert policy.max_wait_seconds == 30.0
        assert policy.per_attempt_timeout_seconds == 15.0

    def test_from_env_uses_defaults_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """環境変数未設定時はデフォルト値を使用することを検証。"""
        monkeypatch.delenv("EMBEDDING_MAX_RETRIES", raising=False)
        monkeypatch.delenv("EMBEDDING_MIN_WAIT", raising=False)
        monkeypatch.delenv("EMBEDDING_MAX_WAIT", raising=False)
        monkeypatch.delenv("EMBEDDING_PER_ATTEMPT_TIMEOUT", raising=False)

        policy = EmbeddingRetryPolicy.from_env()
        assert policy.max_attempts == 3
        assert policy.max_wait_seconds == 10.0

    def test_from_env_invalid_int_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``EMBEDDING_MAX_RETRIES`` の不正値は警告 + デフォルトにフォールバック (fail-soft)。"""
        monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "not-a-number")

        with caplog.at_level(logging.WARNING):
            policy = EmbeddingRetryPolicy.from_env()

        assert policy.max_attempts == 3
        assert "Invalid integer" in caplog.text
        assert "EMBEDDING_MAX_RETRIES" in caplog.text

    def test_from_env_non_positive_int_falls_back(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """非正の ``max_attempts`` は警告 + デフォルトにフォールバック。"""
        monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "0")

        with caplog.at_level(logging.WARNING):
            policy = EmbeddingRetryPolicy.from_env()

        assert policy.max_attempts == 3
        assert "Non-positive" in caplog.text

    def test_from_env_invalid_float_falls_back(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``EMBEDDING_MAX_WAIT`` の不正値は警告 + デフォルトにフォールバック。"""
        monkeypatch.setenv("EMBEDDING_MAX_WAIT", "not-a-float")

        with caplog.at_level(logging.WARNING):
            policy = EmbeddingRetryPolicy.from_env()

        assert policy.max_wait_seconds == 10.0
        assert "Invalid float" in caplog.text

    def test_from_env_negative_float_falls_back(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """負の ``max_wait_seconds`` は警告 + デフォルトにフォールバック。"""
        monkeypatch.setenv("EMBEDDING_MAX_WAIT", "-5.0")

        with caplog.at_level(logging.WARNING):
            policy = EmbeddingRetryPolicy.from_env()

        assert policy.max_wait_seconds == 10.0
        assert "Non-positive" in caplog.text

    def test_from_env_blank_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """空文字 / 空白のみの環境変数はデフォルトを使用することを検証。"""
        monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "   ")
        monkeypatch.setenv("EMBEDDING_MAX_WAIT", "")

        policy = EmbeddingRetryPolicy.from_env()
        assert policy.max_attempts == 3
        assert policy.max_wait_seconds == 10.0


# ---------------------------------------------------------------------------
# Decorator / AsyncRetrying integration
# ---------------------------------------------------------------------------


class TestRetryDecorator:
    """``EmbeddingRetryPolicy.get_retry_decorator`` / ``get_async_retrying`` の統合テスト。"""

    @pytest.mark.asyncio
    async def test_retries_until_success(self) -> None:
        """指定回数までリトライして成功することを検証。"""
        policy = EmbeddingRetryPolicy(
            max_attempts=3,
            min_wait_seconds=0.01,
            max_wait_seconds=0.05,
        )

        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.HTTPStatusError(
                    "rate limit",
                    request=MagicMock(),
                    response=MagicMock(status_code=429, headers={}),
                )
            return "ok"

        retrying = policy.get_async_retrying()
        async for attempt in retrying:
            with attempt:
                result = await func()

        assert call_count == 3
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_max_attempts_enforced(self) -> None:
        """最大試行回数を超えた場合は例外が伝搬することを検証。"""
        policy = EmbeddingRetryPolicy(
            max_attempts=3,
            min_wait_seconds=0.01,
            max_wait_seconds=0.05,
        )

        call_count = 0

        async def always_failing() -> None:
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPStatusError(
                "service unavailable",
                request=MagicMock(),
                response=MagicMock(status_code=503, headers={}),
            )

        retrying = policy.get_async_retrying()

        with pytest.raises(httpx.HTTPStatusError):
            async for attempt in retrying:
                with attempt:
                    await always_failing()

        # max_attempts = 3 なので 3 回呼ばれる
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_retryable_exception_fail_fast(self) -> None:
        """リトライ対象外の例外は 1 回で失敗することを検証 (fail-fast)。"""
        policy = EmbeddingRetryPolicy(
            max_attempts=5,
            min_wait_seconds=0.01,
            max_wait_seconds=0.05,
        )

        call_count = 0

        async def bad_request() -> None:
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPStatusError(
                "bad request",
                request=MagicMock(),
                response=MagicMock(status_code=400, headers={}),
            )

        retrying = policy.get_async_retrying()
        with pytest.raises(httpx.HTTPStatusError):
            async for attempt in retrying:
                with attempt:
                    await bad_request()

        # 4xx (non-retryable) → 1 回のみで終了
        assert call_count == 1


# ---------------------------------------------------------------------------
# Wait strategy with Retry-After
# ---------------------------------------------------------------------------


class TestWaitStrategyWithRetryAfter:
    """Retry-After ヘッダ尊重 wait 戦略のテスト。"""

    @pytest.mark.asyncio
    async def test_retry_after_seconds_honored(self) -> None:
        """サーバーが ``Retry-After: 1`` を指定した場合、そのまま 1 秒待機することを検証。"""
        # Retry-After=1秒 を返す 429 → 次の試行で成功
        # max_wait=2.0 なので Retry-After=1 は cap 内で honor される
        policy = EmbeddingRetryPolicy(
            max_attempts=2,
            min_wait_seconds=0.01,
            max_wait_seconds=2.0,
        )

        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPStatusError(
                    "rate limit",
                    request=MagicMock(),
                    response=MagicMock(
                        status_code=429,
                        headers={"Retry-After": "1"},
                    ),
                )
            return "ok"

        retrying = policy.get_async_retrying()
        start = time.monotonic()
        async for attempt in retrying:
            with attempt:
                result = await func()
        elapsed = time.monotonic() - start

        assert call_count == 2
        assert result == "ok"
        # Retry-After=1 が指数バックオフ (min=0.01) より優先される
        assert elapsed >= 0.9, f"Expected >= 0.9s wait (Retry-After), got {elapsed}s"
        assert elapsed < 2.0, f"Expected < 2.0s, got {elapsed}s"

    @pytest.mark.asyncio
    async def test_retry_after_clamped_to_max_wait(self) -> None:
        """``Retry-After`` が ``max_wait_seconds`` を超える場合はクランプされることを検証。"""
        policy = EmbeddingRetryPolicy(
            max_attempts=2,
            min_wait_seconds=0.01,
            max_wait_seconds=0.5,  # 0.5s でクランプ
        )

        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPStatusError(
                    "rate limit",
                    request=MagicMock(),
                    response=MagicMock(
                        status_code=429,
                        headers={"Retry-After": "100"},  # 100 秒指定 → 0.5s にクランプ
                    ),
                )
            return "ok"

        retrying = policy.get_async_retrying()
        start = time.monotonic()
        async for attempt in retrying:
            with attempt:
                result = await func()
        elapsed = time.monotonic() - start

        assert call_count == 2
        assert result == "ok"
        # 100 秒指定だが max_wait=0.5 にクランプされる
        assert elapsed < 1.0, f"Expected clamped < 1s, got {elapsed}s"

    @pytest.mark.asyncio
    async def test_no_retry_after_uses_exponential(self) -> None:
        """``Retry-After`` が無い場合は指数バックオフが使われることを検証。"""
        policy = EmbeddingRetryPolicy(
            max_attempts=2,
            min_wait_seconds=0.1,
            max_wait_seconds=0.5,
        )

        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPStatusError(
                    "server error",
                    request=MagicMock(),
                    response=MagicMock(status_code=503, headers={}),  # Retry-After 無し
                )
            return "ok"

        retrying = policy.get_async_retrying()
        start = time.monotonic()
        async for attempt in retrying:
            with attempt:
                result = await func()
        elapsed = time.monotonic() - start

        assert call_count == 2
        assert result == "ok"
        # 指数バックオフ min=0.1 が適用される
        assert elapsed >= 0.05, f"Expected exponential backoff wait, got {elapsed}s"


# ---------------------------------------------------------------------------
# Provider integration
# ---------------------------------------------------------------------------


class TestRetryPolicyProviderIntegration:
    """プロバイダで EmbeddingRetryPolicy が正しく使用されることを検証。"""

    def test_openai_provider_initializes_retry_policy_from_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OpenAI プロバイダが env から retry_policy を読み込むことを検証。"""
        from context_store.embedding.openai import OpenAIEmbeddingProvider

        monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "7")
        monkeypatch.setenv("EMBEDDING_PER_ATTEMPT_TIMEOUT", "15.0")

        provider = OpenAIEmbeddingProvider(api_key="test-key")
        assert provider.retry_policy.max_attempts == 7
        assert provider.retry_policy.per_attempt_timeout_seconds == 15.0

    def test_openai_provider_accepts_explicit_retry_policy(self) -> None:
        """OpenAI プロバイダが明示的に与えられた retry_policy を尊重することを検証。"""
        from context_store.embedding.openai import OpenAIEmbeddingProvider

        custom_policy = EmbeddingRetryPolicy(
            max_attempts=2,
            per_attempt_timeout_seconds=3.0,
        )
        provider = OpenAIEmbeddingProvider(
            api_key="test-key",
            retry_policy=custom_policy,
        )
        assert provider.retry_policy is custom_policy
        assert provider.retry_policy.max_attempts == 2

    def test_litellm_provider_initializes_retry_policy_from_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LiteLLM プロバイダが env から retry_policy を読み込むことを検証。"""
        from context_store.embedding.litellm import LiteLLMEmbeddingProvider

        monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "4")
        monkeypatch.setenv("EMBEDDING_MAX_WAIT", "5.0")

        provider = LiteLLMEmbeddingProvider(model="test-model", dimension=1536)
        assert provider.retry_policy.max_attempts == 4
        assert provider.retry_policy.max_wait_seconds == 5.0

    def test_litellm_provider_accepts_explicit_retry_policy(self) -> None:
        """LiteLLM プロバイダが明示的に与えられた retry_policy を尊重することを検証。"""
        from context_store.embedding.litellm import LiteLLMEmbeddingProvider

        custom_policy = EmbeddingRetryPolicy(max_attempts=2)
        provider = LiteLLMEmbeddingProvider(
            model="test-model",
            dimension=1536,
            retry_policy=custom_policy,
        )
        assert provider.retry_policy is custom_policy

    def test_legacy_is_retryable_alias_in_openai(self) -> None:
        """``openai._is_retryable`` が後方互換のために再エクスポートされている。"""
        from context_store.embedding.openai import _is_retryable

        assert _is_retryable is should_retry_embedding

    def test_legacy_is_retryable_alias_in_litellm(self) -> None:
        """``litellm._is_retryable`` が後方互換のために再エクスポートされている。"""
        from context_store.embedding.litellm import _is_retryable

        assert _is_retryable is should_retry_embedding


# ---------------------------------------------------------------------------
# tenacity smoke test
# ---------------------------------------------------------------------------


class TestPolicyTenacityObjects:
    """``get_retry_decorator`` / ``get_async_retrying`` の smoke test。"""

    def test_get_async_retrying_returns_async_retrying(self) -> None:
        """``get_async_retrying`` が ``AsyncRetrying`` インスタンスを返すことを検証。"""
        policy = EmbeddingRetryPolicy()
        retrying = policy.get_async_retrying()
        assert isinstance(retrying, tenacity.AsyncRetrying)

    def test_get_retry_decorator_returns_callable(self) -> None:
        """``get_retry_decorator`` が呼び出し可能オブジェクト (decorator) を返すことを検証。"""
        policy = EmbeddingRetryPolicy()
        decorator = policy.get_retry_decorator()
        assert callable(decorator)
