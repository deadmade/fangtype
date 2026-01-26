"""Tests for URI helper utilities."""

import pytest

from auto_type.utils.uri_helper import UriHelper


class TestUriToPath:
    """Tests for UriHelper.uri_to_path()."""

    def test_unix_path(self) -> None:
        """Test conversion of Unix file URI to path."""
        uri = "file:///home/user/project/file.py"
        result = UriHelper.uri_to_path(uri)
        assert result == "/home/user/project/file.py"

    def test_path_with_spaces(self) -> None:
        """Test conversion of URI with URL-encoded spaces."""
        uri = "file:///home/user/my%20project/file.py"
        result = UriHelper.uri_to_path(uri)
        assert result == "/home/user/my project/file.py"

    def test_path_with_special_chars(self) -> None:
        """Test conversion of URI with URL-encoded special characters."""
        uri = "file:///home/user/project%23backup/file%3F.py"
        result = UriHelper.uri_to_path(uri)
        assert result == "/home/user/project#backup/file?.py"

    def test_non_file_uri(self) -> None:
        """Test that non-file URIs return None."""
        assert UriHelper.uri_to_path("http://example.com") is None
        assert UriHelper.uri_to_path("https://example.com") is None
        assert UriHelper.uri_to_path("/path/to/file.py") is None
        assert UriHelper.uri_to_path("") is None


class TestExtractUri:
    """Tests for UriHelper.extract_uri()."""

    def test_direct_string(self) -> None:
        """Test extracting URI from direct string parameter."""
        uri = "file:///path/to/file.py"
        result = UriHelper.extract_uri(uri)
        assert result == uri

    def test_single_wrapped(self) -> None:
        """Test extracting URI from single-wrapped list."""
        uri = "file:///path/to/file.py"
        result = UriHelper.extract_uri([uri])
        assert result == uri

    def test_double_wrapped(self) -> None:
        """Test extracting URI from double-wrapped list."""
        uri = "file:///path/to/file.py"
        result = UriHelper.extract_uri([[uri]])
        assert result == uri

    def test_single_wrapped_with_extra(self) -> None:
        """Test extracting URI from single-wrapped list with extra items."""
        uri = "file:///path/to/file.py"
        result = UriHelper.extract_uri([uri, "extra", 123])
        assert result == uri

    def test_double_wrapped_with_extra(self) -> None:
        """Test extracting URI from double-wrapped list with extra items."""
        uri = "file:///path/to/file.py"
        result = UriHelper.extract_uri([[uri, "extra"]])
        assert result == uri

    def test_empty_list_raises(self) -> None:
        """Test that empty list raises ValueError."""
        with pytest.raises(ValueError, match="Invalid params structure"):
            UriHelper.extract_uri([])

    def test_empty_nested_list_returns_empty_list_string(self) -> None:
        """Test that empty nested list is treated as single-wrapped and returns str([])."""
        # [[]] has params[0] = [], which is a list but empty, so it's treated as single-wrapped
        # This returns str([]) = "[]"
        result = UriHelper.extract_uri([[]])
        assert result == "[]"

    def test_none_raises(self) -> None:
        """Test that None raises ValueError."""
        with pytest.raises(ValueError, match="Invalid params structure"):
            UriHelper.extract_uri(None)

    def test_invalid_type_raises(self) -> None:
        """Test that invalid types raise ValueError."""
        with pytest.raises(ValueError, match="Invalid params structure"):
            UriHelper.extract_uri(123)


class TestExtractUriWithOptionalParams:
    """Tests for UriHelper.extract_uri_with_optional_params()."""

    def test_direct_string(self) -> None:
        """Test extracting from direct string (no optional params)."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params(uri)
        assert result_uri == uri
        assert result_opts == [None]

    def test_direct_string_with_num_optional(self) -> None:
        """Test extracting from direct string with multiple optional slots."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params(uri, num_optional=3)
        assert result_uri == uri
        assert result_opts == [None, None, None]

    def test_single_wrapped_uri_only(self) -> None:
        """Test extracting from single-wrapped list with URI only."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params([uri])
        assert result_uri == uri
        assert result_opts == [None]

    def test_single_wrapped_with_one_optional(self) -> None:
        """Test extracting from single-wrapped list with one optional param."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params([uri, "option1"])
        assert result_uri == uri
        assert result_opts == ["option1"]

    def test_single_wrapped_with_multiple_optional(self) -> None:
        """Test extracting from single-wrapped list with multiple optional params."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params(
            [uri, "opt1", 42, True], num_optional=3
        )
        assert result_uri == uri
        assert result_opts == ["opt1", 42, True]

    def test_double_wrapped_uri_only(self) -> None:
        """Test extracting from double-wrapped list with URI only."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params([[uri]])
        assert result_uri == uri
        assert result_opts == [None]

    def test_double_wrapped_with_optional(self) -> None:
        """Test extracting from double-wrapped list with optional param."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params([[uri, "option"]])
        assert result_uri == uri
        assert result_opts == ["option"]

    def test_double_wrapped_with_multiple_optional(self) -> None:
        """Test extracting from double-wrapped list with multiple optional params."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params(
            [[uri, 100, {"key": "value"}]], num_optional=2
        )
        assert result_uri == uri
        assert result_opts == [100, {"key": "value"}]

    def test_missing_optional_params_filled_with_none(self) -> None:
        """Test that missing optional params are filled with None."""
        uri = "file:///path/to/file.py"
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params(
            [uri, "only_one"], num_optional=3
        )
        assert result_uri == uri
        assert result_opts == ["only_one", None, None]

    def test_empty_list_raises(self) -> None:
        """Test that empty list raises ValueError."""
        with pytest.raises(ValueError, match="Invalid params structure"):
            UriHelper.extract_uri_with_optional_params([])

    def test_none_raises(self) -> None:
        """Test that None raises ValueError."""
        with pytest.raises(ValueError, match="Invalid params structure"):
            UriHelper.extract_uri_with_optional_params(None)
