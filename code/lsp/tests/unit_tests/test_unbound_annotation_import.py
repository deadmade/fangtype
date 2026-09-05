"""PEP 649 leaves an unbound annotation name unevaluated on the running interpreter."""

from __future__ import annotations

import sys

import pytest


def test_unbound_callable_annotation_loads_on_314() -> None:
    """``load: Callable = None`` must import on 3.14.6, the evaluation pin."""
    assert sys.version_info >= (3, 14)
    namespace: dict[str, object] = {}
    exec("load: Callable = None", namespace)
    assert "load" in namespace


def test_using_the_unbound_name_still_raises() -> None:
    with pytest.raises(NameError, match="Callable"):
        exec("load: Callable = None\nmarker = Callable")
