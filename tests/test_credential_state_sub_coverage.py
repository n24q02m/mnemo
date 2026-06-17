from contextvars import copy_context

from mnemo_mcp.credential_state import get_current_sub, set_current_sub


def test_current_sub_defaults_to_none():
    """Verify that the current sub defaults to None."""
    assert get_current_sub() is None


def test_set_current_sub():
    """Verify that set_current_sub updates the contextvar."""
    set_current_sub("user_123")
    assert get_current_sub() == "user_123"
    set_current_sub(None)
    assert get_current_sub() is None


def test_current_sub_isolation():
    """Verify that contextvars isolation works as expected."""

    def run_in_context():
        set_current_sub("context_user")
        assert get_current_sub() == "context_user"

    # Before running in context
    assert get_current_sub() is None

    ctx = copy_context()
    ctx.run(run_in_context)

    # After running in context (should still be None in the main context)
    assert get_current_sub() is None
