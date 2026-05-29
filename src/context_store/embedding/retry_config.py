"""統一 Embedding リトライポリシー。

OpenAI / LiteLLM などの埋め込みプロバイダ間で共通利用されるリトライ戦略を提供する。

設計目的 (SPEC.md §16.5 E-2):
- リトライ最大時間を予測可能にし、MCP Gateway のタイムアウト枠 (D-1: 30s) に収める。
- レート制限時はサーバー指示の ``Retry-After`` ヘッダを尊重 (上限クランプあり)。
- per-attempt timeout の値を一元管理し、各プロバイダで利用する。

旧設定からの変更点:
- ``max_attempts``: 5 → 3
- ``max_wait_seconds``: 60.0 → 10.0
- ``per_attempt_timeout_seconds``: 新設 (デフォルト 10.0)

環境変数 (env-var driven):
- ``EMBEDDING_MAX_RETRIES`` (default ``3``)
- ``EMBEDDING_MIN_WAIT`` (default ``1.0``)
- ``EMBEDDING_MAX_WAIT`` (default ``10.0``)
- ``EMBEDDING_PER_ATTEMPT_TIMEOUT`` (default ``10.0``)

不正値・非正値は警告 + デフォルトへフォールバック (fail-soft 設計)。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import tenacity

logger = logging.getLogger(__name__)

# デフォルト設定値 (Phase 2 改善後)
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_MIN_WAIT_SECONDS = 1.0
_DEFAULT_MAX_WAIT_SECONDS = 10.0
_DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS = 10.0


def parse_retry_after_header(header: str | None) -> float | None:
    """``Retry-After`` HTTP ヘッダ値を秒数に変換する。

    対応フォーマット (RFC 7231):
    - decimal-integer (秒数): ``"120"``
    - HTTP-date: ``"Fri, 31 Dec 1999 23:59:59 GMT"``

    Args:
        header: ``Retry-After`` ヘッダ値。``None`` または空文字列の場合は ``None`` を返す。

    Returns:
        待機秒数。パース不能な場合は ``None``。負値は ``0.0`` にクランプ。
    """
    if header is None:
        return None
    text = header.strip()
    if not text:
        return None

    # decimal-integer (秒数として直接パース)
    try:
        return float(text)
    except ValueError:
        pass

    # HTTP-date (RFC 7231) としてパース
    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    delay = (target - datetime.now(timezone.utc)).total_seconds()
    return max(delay, 0.0)


def should_retry_embedding(exc: BaseException) -> bool:
    """埋め込み API 呼び出しのリトライ要否を判定する。

    リトライ対象:
    - ``httpx.HTTPStatusError`` の 429 / 500 / 502 / 503 / 504
    - ``httpx.TimeoutException`` / ``httpx.ConnectError``
    - ``TimeoutError`` (含む ``asyncio.TimeoutError``; Python 3.11+ で同義)
    - ``status_code`` 属性を持つカスタム例外 (LiteLLM 等の SDK 例外) のうち
      上記ステータス値を持つもの

    リトライ非対象 (fail-fast):
    - 4xx ステータス (429 を除く)
    - ``ValueError`` 等の検証エラー
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True

    # Python 3.11+: asyncio.TimeoutError is TimeoutError
    if isinstance(exc, TimeoutError):
        return True

    # LiteLLM 等の SDK 例外は status_code 属性を持つ場合がある
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and status_code in (429, 500, 502, 503, 504):
        return True

    return False


def _extract_retry_after(exc: BaseException) -> float | None:
    """例外オブジェクトから ``Retry-After`` 値を抽出する。

    ``httpx.HTTPStatusError.response.headers`` を覗くが、属性が存在しない場合や
    ``Retry-After`` ヘッダが無い場合は ``None`` を返す。
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        retry_after = headers.get("Retry-After")
    except (AttributeError, TypeError):
        return None
    return parse_retry_after_header(retry_after)


@dataclass
class EmbeddingRetryPolicy:
    """埋め込み API リトライ設定。

    ``OpenAIEmbeddingProvider`` / ``LiteLLMEmbeddingProvider`` 共通で利用する。
    ``get_async_retrying()`` でプログラマティックに使う想定。
    """

    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    min_wait_seconds: float = _DEFAULT_MIN_WAIT_SECONDS
    max_wait_seconds: float = _DEFAULT_MAX_WAIT_SECONDS
    per_attempt_timeout_seconds: float = _DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> EmbeddingRetryPolicy:
        """環境変数から設定値を読み込む (fail-soft)。

        - ``EMBEDDING_MAX_RETRIES``: 最大試行回数 (default 3)
        - ``EMBEDDING_MIN_WAIT``: 指数バックオフの最小待機秒数 (default 1.0)
        - ``EMBEDDING_MAX_WAIT``: 指数バックオフの最大待機秒数 (default 10.0)
        - ``EMBEDDING_PER_ATTEMPT_TIMEOUT``: 1 試行あたりのタイムアウト秒数 (default 10.0)

        不正値・非正値は警告ログを出力し、デフォルト値にフォールバックする。
        """
        return cls(
            max_attempts=_read_int_env("EMBEDDING_MAX_RETRIES", _DEFAULT_MAX_ATTEMPTS),
            min_wait_seconds=_read_float_env("EMBEDDING_MIN_WAIT", _DEFAULT_MIN_WAIT_SECONDS),
            max_wait_seconds=_read_float_env("EMBEDDING_MAX_WAIT", _DEFAULT_MAX_WAIT_SECONDS),
            per_attempt_timeout_seconds=_read_float_env(
                "EMBEDDING_PER_ATTEMPT_TIMEOUT",
                _DEFAULT_PER_ATTEMPT_TIMEOUT_SECONDS,
            ),
        )

    def _build_wait_strategy(self) -> Any:
        """指数バックオフ + ``Retry-After`` 尊重の wait 関数を返す。

        サーバーが ``Retry-After`` を指定している場合はそれを採用するが、
        ``max_wait_seconds`` でクランプして暴走を防ぐ。
        ヘッダが無い場合は通常の指数バックオフ (``wait_exponential``) にフォールバック。
        """
        exponential = tenacity.wait_exponential(
            multiplier=1,
            min=self.min_wait_seconds,
            max=self.max_wait_seconds,
        )
        wait_cap = self.max_wait_seconds

        def _wait(retry_state: tenacity.RetryCallState) -> float:
            outcome = retry_state.outcome
            if outcome is not None:
                exc = outcome.exception()
                if exc is not None:
                    retry_after = _extract_retry_after(exc)
                    if retry_after is not None:
                        return min(retry_after, wait_cap)
            return float(exponential(retry_state))

        return _wait

    def _build_kwargs(self) -> dict[str, Any]:
        """``tenacity.retry`` / ``AsyncRetrying`` 共通の kwargs を返す。"""
        return {
            "stop": tenacity.stop_after_attempt(self.max_attempts),
            "wait": self._build_wait_strategy(),
            "retry": tenacity.retry_if_exception(should_retry_embedding),
            "before_sleep": tenacity.before_sleep_log(logger, logging.WARNING),
            "reraise": True,
        }

    def get_retry_decorator(self) -> Any:
        """``tenacity.retry`` デコレータを返す (関数のラッピングに使用)。"""
        return tenacity.retry(**self._build_kwargs())

    def get_async_retrying(self) -> tenacity.AsyncRetrying:
        """``tenacity.AsyncRetrying`` インスタンスを返す (async for ループで使用)。"""
        return tenacity.AsyncRetrying(**self._build_kwargs())


def _read_int_env(name: str, default: int) -> int:
    """環境変数を整数として読み込む。不正値・非正値は警告 + デフォルト (fail-soft)。"""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid integer value for %s: %r; falling back to default %d",
            name,
            raw,
            default,
        )
        return default
    if value <= 0:
        logger.warning(
            "Non-positive value for %s: %d; falling back to default %d",
            name,
            value,
            default,
        )
        return default
    return value


def _read_float_env(name: str, default: float) -> float:
    """環境変数を浮動小数として読み込む。不正値・非正値は警告 + デフォルト (fail-soft)。"""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid float value for %s: %r; falling back to default %.2f",
            name,
            raw,
            default,
        )
        return default
    if value <= 0:
        logger.warning(
            "Non-positive value for %s: %.2f; falling back to default %.2f",
            name,
            value,
            default,
        )
        return default
    return value


__all__ = [
    "EmbeddingRetryPolicy",
    "parse_retry_after_header",
    "should_retry_embedding",
]
