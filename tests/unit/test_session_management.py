"""Unit tests for session management fixes in src/mcp_gateway/auth/session.py."""

from __future__ import annotations

from datetime import timedelta

import pytest

import mcp_gateway.auth.session as sess
from mcp_gateway.auth.session import InMemorySessionRegistry
from mcp_gateway.errors import SessionError


class TestSessionManagementFixes:
    def _make_registry(self, ttl: int = 60, idle: int = 30):
        return InMemorySessionRegistry(ttl_seconds=ttl, idle_timeout_seconds=idle)

    def test_init_validation(self):
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            InMemorySessionRegistry(ttl_seconds=0, idle_timeout_seconds=30)
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            InMemorySessionRegistry(ttl_seconds=-1, idle_timeout_seconds=30)
        with pytest.raises(ValueError, match="idle_timeout_seconds must be positive"):
            InMemorySessionRegistry(ttl_seconds=60, idle_timeout_seconds=0)
        with pytest.raises(ValueError, match="idle_timeout_seconds must be positive"):
            InMemorySessionRegistry(ttl_seconds=60, idle_timeout_seconds=-1)

    def test_lookup_automatic_touch(self, monkeypatch):
        reg = self._make_registry(ttl=600, idle=10)
        rec = reg.create(agent_id="a", intent="i", caps=frozenset(), output_filter_profile="f")

        start_time = sess._utcnow()
        monkeypatch.setattr(sess, "_utcnow", lambda: start_time + timedelta(seconds=5))

        # This lookup should automatically touch the session
        reg.lookup(rec.session_id)

        # Advance time to 12s. Without touch, it would expire (12-0 > 10).
        # With touch at 5s, it's still valid (12-5 = 7 < 10).
        monkeypatch.setattr(sess, "_utcnow", lambda: start_time + timedelta(seconds=12))
        assert reg.lookup(rec.session_id).session_id == rec.session_id

    def test_touch_respects_ttl(self, monkeypatch):
        reg = self._make_registry(ttl=10, idle=60)
        rec = reg.create(agent_id="a", intent="i", caps=frozenset(), output_filter_profile="f")

        start_time = sess._utcnow()
        # Advance beyond TTL
        monkeypatch.setattr(sess, "_utcnow", lambda: start_time + timedelta(seconds=15))

        # touch should detect TTL expiry and remove the session
        reg.touch(rec.session_id)

        # Verify it's gone (unknown session_id because touch() purged it)
        with pytest.raises(SessionError, match="unknown session_id"):
            reg.lookup(rec.session_id)

    def test_touch_does_not_resurrect_idle_session(self, monkeypatch):
        reg = self._make_registry(ttl=600, idle=10)
        rec = reg.create(agent_id="a", intent="i", caps=frozenset(), output_filter_profile="f")

        start_time = sess._utcnow()
        # Advance beyond Idle but within TTL
        monkeypatch.setattr(sess, "_utcnow", lambda: start_time + timedelta(seconds=15))

        # touch should detect idle expiry and remove the session
        reg.touch(rec.session_id)

        # Verify it's gone
        with pytest.raises(SessionError, match="unknown session_id"):
            reg.lookup(rec.session_id)

    def test_purge_logic_detailed(self, monkeypatch):
        now_val = sess._utcnow()
        monkeypatch.setattr(sess, "_utcnow", lambda: now_val)

        reg = self._make_registry(ttl=100, idle=50)

        s1 = reg.create(
            agent_id="s1", intent="i", caps=frozenset(), output_filter_profile="f"
        ).session_id

        # Move time to t=70
        t70 = now_val + timedelta(seconds=70)
        monkeypatch.setattr(sess, "_utcnow", lambda: t70)

        # Create s3 at t=70 (so its last_active is t=70)
        s3 = reg.create(
            agent_id="s3", intent="i", caps=frozenset(), output_filter_profile="f"
        ).session_id

        # Move time to t=130
        t130 = now_val + timedelta(seconds=130)
        monkeypatch.setattr(sess, "_utcnow", lambda: t130)

        # s1: issued at t=0, expires at t=100. At t=130, TTL expired.
        # s3: issued at t=70, expires at t=170, last_active at t=70.
        # At t=130, idle age = 130-70=60 > 50. Idle expired.

        # Let's add s2 that remains valid
        # s2: issued at t=130, expires at t=230, last_active at t=130. Valid.
        s2 = reg.create(
            agent_id="s2", intent="i", caps=frozenset(), output_filter_profile="f"
        ).session_id

        reg.purge()

        assert s2 in reg._records
        assert s1 not in reg._records
        assert s3 not in reg._records

        # Boundary test: exact TTL expiry (t == expires_at)
        # s4 created at t=130, ttl=100 -> expires at t=230
        s4 = reg.create(
            agent_id="s4", intent="i", caps=frozenset(), output_filter_profile="f"
        ).session_id
        t230 = now_val + timedelta(seconds=230)
        monkeypatch.setattr(sess, "_utcnow", lambda: t230)
        with pytest.raises(SessionError, match=r"session expired \(ttl\)"):
            reg.lookup(s4)
        assert s4 not in reg._records

        # Boundary test: exact idle expiry (idle_age == idle_timeout)
        # s5 created at t=230, idle=50 -> expires at t=280
        s5 = reg.create(
            agent_id="s5", intent="i", caps=frozenset(), output_filter_profile="f"
        ).session_id
        t280 = now_val + timedelta(seconds=280)
        monkeypatch.setattr(sess, "_utcnow", lambda: t280)
        with pytest.raises(SessionError, match=r"session expired \(idle\)"):
            reg.lookup(s5)
        assert s5 not in reg._records

    def test_caps_frozenset_conversion(self):
        reg = self._make_registry()
        # Passing a mutable set
        mutable_caps = {"cap1", "cap2"}
        rec = reg.create(
            agent_id="agent1",
            intent="intent1",
            caps=mutable_caps,  # type: ignore
            output_filter_profile="profile1",
        )

        assert isinstance(rec.caps, frozenset)
        assert rec.caps == frozenset(["cap1", "cap2"])

        # Verify it's a copy/converted so changing mutable_caps doesn't affect it
        mutable_caps.add("cap3")
        assert "cap3" not in rec.caps
