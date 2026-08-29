"""Tests pinning the pygls wire shape for removal-record entries.

pygls re-parses every custom-request response through
``pygls.protocol._dict_to_object``, whose ``object_hook`` turns each nested JSON object
into ``namedtuple(type_name, keys, rename=True)(*values)`` rather than leaving it a
``dict``. So a ``will_remove`` entry that is a plain dict when built in-process (or in a
hand-rolled test double) arrives as a namedtuple-like object once it has travelled over a
real LSP response. ``as_mapping`` (``benchmark/lsp_client/label_parse.py``) is what
``_build_target`` (``benchmark/mypy_eval/prepare.py``) uses to normalise either shape
back to a mapping before reading it, and these tests import the real pygls hook rather
than a hand-rolled imitation of it, so they pin the actual structuring behaviour and not
just an assumption about it.
"""

from __future__ import annotations

import copy
from typing import cast

import pytest
from pygls.protocol import _dict_to_object

from benchmark.lsp_client.label_parse import as_mapping
from benchmark.mypy_eval.prepare import _build_target

_PREVIEW_REMOVALS_RESPONSE = {
    "success": True,
    "will_remove": [
        {
            "variable": "count",
            "type": "int",
            "line": 3,
            "target_kind": "variable",
            "function_name": None,
            "parameter_name": None,
        },
        {
            "variable": "n",
            "type": "str",
            "line": 5,
            "target_kind": "parameter",
            "function_name": "func1",
            "parameter_name": "n",
        },
    ],
    "not_found": [],
    "will_skip": [],
    "total_changes": 2,
    "message": "ok",
}


def _structured_will_remove() -> list[object]:
    """Round-trip the synthetic response through the real pygls hook."""
    # _dict_to_object mutates its argument (pops "type_name"), so hand it a fresh copy.
    structured = _dict_to_object(copy.deepcopy(_PREVIEW_REMOVALS_RESPONSE))
    return list(structured.will_remove)


def test_build_target_agrees_across_dict_and_pygls_namedtuple_shapes() -> None:
    """Same manifest from a plain dict and from pygls's namedtuple structuring."""
    dict_entries = cast("list[object]", _PREVIEW_REMOVALS_RESPONSE["will_remove"])
    namedtuple_entries = _structured_will_remove()

    for dict_entry, namedtuple_entry in zip(dict_entries, namedtuple_entries, strict=True):
        assert hasattr(namedtuple_entry, "_asdict"), "fixture must exercise the namedtuple path"
        assert _build_target(dict_entry) == _build_target(namedtuple_entry)


def test_build_target_none_values_survive_the_namedtuple_path() -> None:
    """The variable entry's ``function_name``/``parameter_name`` are ``None`` on both paths."""
    namedtuple_entry = _structured_will_remove()[0]
    target = _build_target(namedtuple_entry)
    assert target.function_name is None
    assert target.parameter_name is None


def test_as_mapping_passes_a_plain_dict_through() -> None:
    entry = {"variable": "x", "type": "int"}
    assert as_mapping(entry) is entry


def test_as_mapping_converts_a_pygls_namedtuple() -> None:
    structured = _structured_will_remove()[1]
    mapping = as_mapping(structured)
    assert mapping == {
        "variable": "n",
        "type": "str",
        "line": 5,
        "target_kind": "parameter",
        "function_name": "func1",
        "parameter_name": "n",
    }


def test_as_mapping_raises_on_an_unrecognised_shape() -> None:
    """A silent ``{}`` here would turn every unrecognised entry into an empty manifest
    instead of surfacing that the wire shape changed, so this must raise rather than
    degrade quietly."""
    with pytest.raises(TypeError, match="list"):
        as_mapping([1, 2, 3])
