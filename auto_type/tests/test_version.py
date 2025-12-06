"""Test version information."""

import auto_type


def test_version() -> None:
    """Test that version is defined and follows semantic versioning."""
    assert hasattr(auto_type, "__version__")
    assert isinstance(auto_type.__version__, str)
    assert len(auto_type.__version__.split(".")) == 3
