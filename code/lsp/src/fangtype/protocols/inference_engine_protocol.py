"""Protocol for type inference engines."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fangtype.cancellation import CancellationToken  # noqa: TC001
from fangtype.inference import InferenceResult  # noqa: TC001


@runtime_checkable
class InferenceEngineProtocol(Protocol):
    """Sync inference engine interface (main impl JediInferenceEngine); cancel_token cancels it."""

    def infer_types(
        self,
        source: str,
        path: str | None = None,
        project_root: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> InferenceResult:
        """Run full inference on source, returning an InferenceResult with scope tree and types."""
        ...

    def infer_types_at_locations(
        self,
        source: str,
        locations: list[tuple[int, int]],
        path: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> dict[tuple[int, int], str]:
        """Infer types at the given 1-based (line, col) locations, mapping each to a type."""
        ...
