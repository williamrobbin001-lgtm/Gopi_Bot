"""Shared test setup."""
import pytest

from bot import safety


@pytest.fixture(autouse=True)
def auto_permission_mode():
    """Tool tests exercise behaviour directly, so run them in "auto" mode (destructive
    actions still ask). Permission-mode tests switch to "ask" themselves."""
    previous = safety.get_mode()
    safety.set_mode("auto")
    yield
    safety.set_mode(previous)
