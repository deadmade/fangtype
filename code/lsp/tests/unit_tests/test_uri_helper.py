"""Tests for URI helper utilities."""

import pytest

from fangtype.utils.json_value import JSONValue
from fangtype.utils.uri_helper import UriHelper


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


_URI = "file:///path/to/file.py"


class TestExtractUri:
    """Tests for UriHelper.extract_uri()."""

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            pytest.param(_URI, _URI, id="direct_string"),
            pytest.param([_URI], _URI, id="single_wrapped"),
            pytest.param([[_URI]], _URI, id="double_wrapped"),
            pytest.param([_URI, "extra", 123], _URI, id="single_wrapped_with_extra"),
            pytest.param([[_URI, "extra"]], _URI, id="double_wrapped_with_extra"),
            # [[]] has params[0]=[] (empty list), treated as single-wrapped, so returns str([])="[]"
            pytest.param([[]], "[]", id="empty_nested_list_returns_empty_list_string"),
        ],
    )
    def test_extract(self, params: JSONValue, expected: str) -> None:
        """Test extracting a URI from the supported param shapes."""
        assert UriHelper.extract_uri(params) == expected

    @pytest.mark.parametrize("params", [[], None, 123], ids=["empty_list", "none", "invalid_type"])
    def test_invalid_raises(self, params: JSONValue) -> None:
        """Test that unsupported param structures raise ValueError."""
        with pytest.raises(ValueError, match="Invalid params structure"):
            UriHelper.extract_uri(params)


class TestExtractUriWithOptionalParams:
    """Tests for UriHelper.extract_uri_with_optional_params()."""

    @pytest.mark.parametrize(
        ("params", "num_optional", "expected_opts"),
        [
            pytest.param(_URI, 1, [None], id="direct_string"),
            pytest.param(_URI, 3, [None, None, None], id="direct_string_with_num_optional"),
            pytest.param([_URI], 1, [None], id="single_wrapped_uri_only"),
            pytest.param([_URI, "option1"], 1, ["option1"], id="single_wrapped_with_one_optional"),
            pytest.param(
                [_URI, "opt1", 42, True],
                3,
                ["opt1", 42, True],
                id="single_wrapped_with_multiple_optional",
            ),
            pytest.param([[_URI]], 1, [None], id="double_wrapped_uri_only"),
            pytest.param([[_URI, "option"]], 1, ["option"], id="double_wrapped_with_optional"),
            pytest.param(
                [[_URI, 100, {"key": "value"}]],
                2,
                [100, {"key": "value"}],
                id="double_wrapped_with_multiple_optional",
            ),
            pytest.param(
                [_URI, "only_one"],
                3,
                ["only_one", None, None],
                id="missing_optional_params_filled_with_none",
            ),
        ],
    )
    def test_extract(
        self, params: JSONValue, num_optional: int, expected_opts: list[JSONValue]
    ) -> None:
        """Test extracting URI + optional params across the supported shapes."""
        result_uri, result_opts = UriHelper.extract_uri_with_optional_params(
            params, num_optional=num_optional
        )
        assert result_uri == _URI
        assert result_opts == expected_opts

    @pytest.mark.parametrize("params", [[], None], ids=["empty_list", "none"])
    def test_invalid_raises(self, params: JSONValue) -> None:
        """Test that unsupported param structures raise ValueError."""
        with pytest.raises(ValueError, match="Invalid params structure"):
            UriHelper.extract_uri_with_optional_params(params)
