import pytest

from app.lib.poll_until import poll_until


async def test_returns_true_once_check_succeeds():
    calls = {"n": 0}

    async def check():
        calls["n"] += 1
        return calls["n"] >= 3

    result = await poll_until(check, interval=0.001, timeout=1.0)
    assert result is True
    assert calls["n"] == 3


async def test_returns_false_on_timeout():
    async def check():
        return False

    result = await poll_until(check, interval=0.001, timeout=0.01)
    assert result is False


async def test_transient_error_does_not_abort_the_whole_poll():
    calls = {"n": 0}

    async def check():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("transient")
        return True

    result = await poll_until(check, interval=0.001, timeout=1.0)
    assert result is True
    assert calls["n"] == 2


async def test_timeout_logs_a_warning_naming_the_label(caplog):
    async def check():
        return False

    with caplog.at_level("WARNING"):
        result = await poll_until(check, interval=0.001, timeout=0.01, label="player state=play")
    assert result is False
    assert any("player state=play" in r.message for r in caplog.records)


async def test_success_logs_nothing(caplog):
    async def check():
        return True

    with caplog.at_level("WARNING"):
        result = await poll_until(check, interval=0.001, timeout=1.0, label="should not appear")
    assert result is True
    assert "should not appear" not in caplog.text
