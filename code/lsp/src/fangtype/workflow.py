"""TypeAnnotationWorkflow: the LSP server's async orchestration layer for type annotations."""

import asyncio
import difflib
from collections.abc import Mapping

from injector import inject

from fangtype.analysis import ForwardRefContext, ScopeType, build_forward_ref_context
from fangtype.analysis.name_collector import NameCollector, NameLocation
from fangtype.analysis.types import ImportHint
from fangtype.cancellation import CancellationToken
from fangtype.inference import InferenceResult
from fangtype.inference.inference_result import FunctionInsertionInfo
from fangtype.insertion import (
    CodeLocation,
    InsertionEngine,
    InsertionResult,
    InsertionTarget,
    TargetType,
    build_source_index,
    create_variable_target,
    detect_assignment_pattern_indexed,
    find_assignment_target,
    find_assignment_target_indexed,
    find_variable_line,
)
from fangtype.protocols.inference_engine_protocol import InferenceEngineProtocol
from fangtype.protocols.type_validator_protocol import TypeValidatorProtocol
from fangtype.removal import RemovalEngine
from fangtype.utils.document_cache import DocumentCache
from fangtype.utils.settings import Settings
from fangtype.validation.mypy_diagnostic import MypyDiagnostic
from fangtype.validation.mypy_validator import TypeValidationResult


class TypeAnnotationWorkflow:
    """Orchestrates async type inference, validation, and insertion/removal via injected engines."""

    # @inject leaks Any (overloads resolve to Any), tripping disallow_any_expr — ignore here.
    @inject  # type: ignore[misc]
    def __init__(
        self,
        inference_engine: InferenceEngineProtocol,
        insertion_engine: InsertionEngine,
        removal_engine: RemovalEngine,
        type_validator: TypeValidatorProtocol,
        settings: Settings,
        document_cache: DocumentCache,
    ) -> None:
        """Initialize the workflow with its injected engines and settings."""
        self._inference_engine = inference_engine
        self._insertion_engine = insertion_engine
        self._removal_engine = removal_engine
        self._type_validator = type_validator
        self._settings = settings
        self._document_cache = document_cache

    async def _infer_cached(
        self,
        source: str,
        file_path: str | None,
        uri: str | None,
        version: int | None,
        cancel_token: CancellationToken | None,
    ) -> InferenceResult:
        """Infer types, cached on (uri, version, generation)+hash; never cache cancelled/partial."""
        project_root = self._settings.project_root
        if uri is None:
            return await asyncio.to_thread(
                self._inference_engine.infer_types,
                source,
                path=file_path,
                project_root=project_root,
                cancel_token=cancel_token,
            )

        generation = self._settings.generation
        cached = self._document_cache.get(uri, version, generation, source)
        if cached is not None:
            return cached

        result = await asyncio.to_thread(
            self._inference_engine.infer_types,
            source,
            path=file_path,
            project_root=project_root,
            cancel_token=cancel_token,
        )
        # Never cache a cancelled (partial) or incomplete result; None token = not cancelled.
        cancelled = cancel_token is not None and cancel_token.cancelled()
        if not cancelled and result.is_complete:
            self._document_cache.put(uri, version, generation, source, result)
        return result

    async def insert_all_types(
        self,
        source: str,
        file_path: str | None,
        cancel_token: CancellationToken | None = None,
        uri: str | None = None,
        version: int | None = None,
    ) -> tuple[str, int, dict[str, int], str]:
        """Infer, validate, insert every annotation; returns (source, inserted, reasons, msg)."""
        (
            targets,
            _var_count,
            _func_count,
            early_msg,
            drop_reasons,
        ) = await self._prepare_insertion_targets(
            source, file_path, cancel_token=cancel_token, uri=uri, version=version
        )

        if early_msg is not None:
            return source, 0, drop_reasons, early_msg

        if not targets:
            return source, 0, drop_reasons, "No types inserted (all items already annotated)"

        result = await self._insert_with_assignability_gate(targets, source)

        if result.success:
            message = f"Inserted {result.inserted_count} type annotations"
            return result.modified_source, result.inserted_count, drop_reasons, message
        else:
            return source, 0, drop_reasons, f"Insertion failed: {result.error_message}"

    async def insert_with_assignability_gate(
        self, targets: list[InsertionTarget], source: str
    ) -> InsertionResult:
        """Public entry to the gate, for the code-action path which builds its own target.

        The private method keeps its name because the evaluation harvest scripts import and
        monkeypatch it there.
        """
        return await self._insert_with_assignability_gate(targets, source)

    async def _insert_with_assignability_gate(
        self, targets: list[InsertionTarget], source: str
    ) -> InsertionResult:
        """Insert `targets`, then drop any whose annotated line mypy flags as an incompatible
        assignment/arg-type, re-inserting and RE-VALIDATING the survivors to a fixpoint. When
        nothing is dropped (the common case) the trial insert stands, so the no-drop path costs
        exactly one insert + one mypy run.

        Re-validation is load-bearing: with inter-dependent inference, dropping one target can
        invalidate a survivor (e.g. `y: int = x` was valid only while `x: int` was present in the
        trial). Each iteration that drops shrinks the survivor set strictly, so the loop converges
        in at most `len(targets)` iterations; the final clean validation is the terminating pass.

        This is the value-fit safety net the bare-annotation `validate_bulk` pre-pass cannot give:
        it checks each type against its real RHS in its real scope. Gated behind `mypy_enabled`
        (default True), independent of `mypy_inference_validation_enabled` (which governs the inlay
        path only). ponytail: one extra full-file mypy run per surviving drop-round — insert-path
        only, never per-keystroke.
        """
        result = self._insertion_engine.insert(targets, source)
        if not self._settings.mypy_enabled or not result.success or result.inserted_count == 0:
            return result

        survivors = targets
        # Bounded by len(targets)+1: each iteration either returns (no flag) or drops >=1 survivor;
        # after len(targets) drops the set is empty. The +1 covers the final clean validation pass.
        for _ in range(len(targets) + 1):
            diagnostics = await self._type_validator.validate_file_full(result.modified_source)
            flagged = _flagged_target_lines(survivors, source, result.modified_source, diagnostics)
            if not flagged:
                return result

            survivors = [t for t in survivors if t.location.line not in flagged]
            if not survivors:
                return InsertionResult.error_result(
                    source, "All inferred types failed assignability validation", targets
                )
            result = self._insertion_engine.insert(survivors, source)
            if not result.success or result.inserted_count == 0:
                return result

        # Unreachable: survivors strictly shrink each pass, so the loop always returns above.
        raise AssertionError("assignability gate failed to converge")

    async def preview_insertions(
        self,
        source: str,
        file_path: str | None = None,
        cancel_token: CancellationToken | None = None,
        uri: str | None = None,
        version: int | None = None,
    ) -> dict[str, object]:
        """Preview insertions as client-ready data: {"will_insert": [...], "total_changes": int}."""
        targets, _, _, early_msg, _ = await self._prepare_insertion_targets(
            source, file_path, cancel_token=cancel_token, uri=uri, version=version, per_binding=True
        )

        if early_msg is not None or not targets:
            return {"will_insert": [], "total_changes": 0}

        engine_preview = self._insertion_engine.preview_insertions(targets, source)
        total = engine_preview.get("total_plans", 0)

        # preview_insertions returns a heterogeneous dict (or {"error": ...}); narrow first.
        plan_details = engine_preview.get("plan_details", [])
        will_insert: list[dict[str, object]] = []
        if isinstance(plan_details, list):
            for plan in plan_details:
                if not isinstance(plan, dict):
                    continue
                variable = plan.get("target") or plan.get("variable")
                type_str = plan.get("type")
                if variable is None or type_str is None:
                    continue
                entry: dict[str, object] = {"variable": variable, "type": type_str}
                if "line" in plan:
                    entry["line"] = plan["line"]
                will_insert.append(entry)

        return {"will_insert": will_insert, "total_changes": total}

    async def annotate_at_position(
        self,
        source: str,
        file_path: str | None,
        line: int,
        character: int,
        cancel_token: CancellationToken | None = None,
        uri: str | None = None,
        version: int | None = None,
    ) -> dict[str, object]:
        """Infer and insert a single annotation for the identifier at the cursor."""
        # 1. Resolve the cursor to an identifier.
        name_loc = NameCollector.name_at_position(source, line + 1, character)
        if name_loc is None:
            return self._annotate_failure(
                None, "No variable or expression found at cursor position"
            )

        # 2. Prepare targets, scoped to just this cursor target.
        targets, _var_count, _func_count, early_message, _ = await self._prepare_insertion_targets(
            source,
            file_path,
            cancel_token=cancel_token,
            uri=uri,
            version=version,
            only=(name_loc.name, line),
            # Every binding, not just the last: the cursor may sit on an earlier one.
            per_binding=True,
        )
        if early_message is not None or not targets:
            return self._annotate_failure(
                name_loc.name, early_message or f"Could not infer a type for '{name_loc.name}'"
            )

        # 3. Pick the single target matching the cursor name.
        target = self._select_target_for_name(targets, name_loc)
        if target is None:
            return self._annotate_failure(
                name_loc.name,
                f"No type to insert for '{name_loc.name}' "
                "(already annotated, not inferable, or not a variable)",
            )

        # 4. Insert it and build the result payload.
        result = await self._insert_with_assignability_gate([target], source)
        success = bool(result.success and result.inserted_count > 0)
        if not success:
            return {
                "name": name_loc.name,
                "inferred_type": target.type_annotation,
                "modified_source": result.modified_source,
                "insertion_success": False,
                "error_message": result.error_message or "Insertion failed",
            }

        return {
            "name": name_loc.name,
            "inferred_type": target.type_annotation,
            "modified_source": result.modified_source,
            "insertion_success": True,
            "error_message": None,
            "message": f"Inserted type annotation: {name_loc.name}: {target.type_annotation}",
        }

    def remove_types(
        self,
        source: str,
        variables: list[str] | None = None,
        include_functions: bool = False,
        line: int | None = None,
    ) -> tuple[str, dict[str, object]]:
        """Remove annotations via RemovalEngine; returns (source, result_info) with a message."""
        # RemovalEngine returns a heterogeneous dict[str, object]; narrow before measuring lists.
        modified_source, result_info = self._removal_engine.remove_types(
            source, variables, include_functions, line
        )

        if not result_info.get("success"):
            result_info["message"] = "No type annotations found to remove"
            return modified_source, result_info

        removed = result_info["removed_count"]
        skipped = result_info.get("will_skip", [])
        not_found = result_info.get("not_found", [])
        message = (
            f"Removed {removed} type annotation(s) from file."
            if variables is None
            else f"Removed {removed} type annotation(s)."
        )
        if isinstance(skipped, list) and skipped:
            message += f" Skipped {len(skipped)} variable(s) without values."
        if isinstance(not_found, list) and not_found:
            message += f" {len(not_found)} variable(s) not found or not annotated."

        result_info["message"] = message
        return modified_source, result_info

    def preview_removals(
        self,
        source: str,
        variables: list[str] | None = None,
        include_functions: bool = False,
    ) -> dict[str, object]:
        """Preview which annotations would be removed (sync RemovalEngine summary)."""
        return self._removal_engine.preview_removals(source, variables, include_functions)

    async def collect_and_validate_types(
        self,
        source: str,
        file_path: str | None,
        cancel_token: CancellationToken | None = None,
        uri: str | None = None,
        version: int | None = None,
    ) -> tuple[InferenceResult, dict[str, TypeValidationResult] | None]:
        """Infer, collect all-scope types, and validate (inlay path); None if mypy off."""
        # 1. Infer types (served from the DocumentCache when the document is unchanged).
        inference_result = await self._infer_cached(source, file_path, uri, version, cancel_token)

        # 2. Collect every inferred type from all scopes.
        all_types = self._collect_types_from_scopes(inference_result)

        # 3. Validate (mypy guard — also inlined in _prepare_insertion_targets; keep in sync).
        validated_types = (
            await self._type_validator.validate_bulk(all_types, source)
            if self._settings.mypy_inference_validation_enabled
            else None
        )

        return inference_result, validated_types

    async def _prepare_insertion_targets(
        self,
        source: str,
        file_path: str | None = None,
        cancel_token: CancellationToken | None = None,
        uri: str | None = None,
        version: int | None = None,
        *,
        only: tuple[str, int] | None = None,
        per_binding: bool = False,
    ) -> tuple[list[InsertionTarget], int, int, str | None, dict[str, int]]:
        """Infer+validate+build InsertionTargets; `only` scopes to cursor, `per_binding` all.

        The 5th return value buckets each surfaced variable name into 'selected' vs
        'all_mypy_invalid' (insert-path diagnostic), computed from the selection pass that already
        runs -- so the caller needs no second inference/validation pass. Empty unless best_valid.
        """
        # 1. Infer types (served from the DocumentCache when the document is unchanged).
        inference_result = await self._infer_cached(source, file_path, uri, version, cancel_token)

        # 2. Collect the inferred function/attribute candidates (shared by all paths).
        function_insertions = inference_result.get_function_insertions()
        attribute_insertions = inference_result.get_attribute_insertions()
        # Per-(line0, name) imports for variables; keyed like get_variable_insertions.
        import_hints = inference_result.get_import_hints()
        # Same for signatures, keyed (line0, func_name, param_name) with "return" for the return.
        function_import_hints = inference_result.get_function_import_hints()

        # 2a. Variables: full-file insert picks most-recent valid binding/name; preview/cursor: rep.
        best_valid = only is None and not per_binding
        variable_insertions: dict[tuple[int, str], str] = {}
        variable_candidates: dict[tuple[str, str], list[tuple[int, str]]] = {}
        if best_valid:
            variable_candidates = inference_result.get_variable_insertion_candidates()
        else:
            variable_insertions = inference_result.get_variable_insertions(per_binding=per_binding)

        # 2b. Narrow to the single cursor target (annotate_at_position only).
        if only is not None:
            variable_insertions, function_insertions, attribute_insertions = _restrict_to_target(
                only, variable_insertions, function_insertions, attribute_insertions
            )

        inferred_vars: object = variable_candidates if best_valid else variable_insertions
        if not (inferred_vars or function_insertions or attribute_insertions):
            return [], 0, 0, "No types to insert (no variables, functions, or attributes found)", {}

        # 3. Validate (guard inlined in collect_and_validate_types too); None = trust every type.
        validated_vars: dict[tuple[int, str], TypeValidationResult] | None
        drop_reasons: dict[str, int] = {}
        if best_valid:
            validated_vars = await self._select_best_valid_variables(
                variable_candidates, source, import_hints
            )
            drop_reasons = _bucket_variable_drop_reasons(variable_candidates, validated_vars)
        else:
            validated_vars = (
                await self._type_validator.validate_bulk(
                    variable_insertions, source, import_hints=import_hints
                )
                if self._settings.mypy_inference_validation_enabled
                else None
            )
            # validate_bulk returns every input; drop mypy-rejected so only valid types build.
            if validated_vars is not None:
                validated_vars = {k: v for k, v in validated_vars.items() if v.is_valid}

        # Attrs/funcs validated the same (mypy-only), per-annotation: a func keeps valid parts.
        if self._settings.mypy_inference_validation_enabled:
            attribute_insertions = await self._validate_attribute_insertions(
                attribute_insertions, source
            )
            function_insertions = await self._validate_function_insertions(
                function_insertions, source, function_import_hints
            )

        have_vars = variable_insertions if validated_vars is None else validated_vars
        if not (have_vars or function_insertions or attribute_insertions):
            return [], 0, 0, "No valid types to insert (all types failed validation)", drop_reasons

        # 4. Build the InsertionTarget objects for the valid insertions.
        targets = self._build_targets(
            validated_vars,
            variable_insertions,
            function_insertions,
            attribute_insertions,
            source,
            import_hints,
            function_import_hints,
        )
        return targets, len(have_vars), len(function_insertions), None, drop_reasons

    async def _validate_attribute_insertions(
        self, attribute_insertions: dict[tuple[int, str], str], source: str
    ) -> dict[tuple[int, str], str]:
        """Drop attribute insertions whose inferred type mypy rejects (empty in → empty out)."""
        if not attribute_insertions:
            return attribute_insertions
        validated = await self._type_validator.validate_bulk(attribute_insertions, source)
        return {k: attribute_insertions[k] for k, result in validated.items() if result.is_valid}

    async def _validate_function_insertions(
        self,
        function_insertions: dict[tuple[int, str], FunctionInsertionInfo],
        source: str,
        import_hints: Mapping[tuple[int, str, str], ImportHint] | None = None,
    ) -> dict[tuple[int, str], FunctionInsertionInfo]:
        """Drop mypy-rejected function annotations per-annotation; func kept if any part valid.

        The hints ride along because the probe mypy runs is the annotation against a prelude
        built from them. Without them a synthesised ``Callable`` is probed against a source
        that never imports it, and a correct type is rejected as an undefined name.
        """
        if not function_insertions:
            return function_insertions

        # Flatten to bare type strings; "return" can't collide (keyword), (line, name) is unique.
        flat: dict[tuple[int, str, str], str] = {}
        for (line, fname), info in function_insertions.items():
            for param_name, param_type in info["params"].items():
                flat[(line, fname, param_name)] = param_type
            if info["return_type"] is not None:
                flat[(line, fname, "return")] = info["return_type"]

        validated = await self._type_validator.validate_bulk(
            flat, source, import_hints=import_hints
        )
        if not validated:
            return {}

        result: dict[tuple[int, str], FunctionInsertionInfo] = {}
        for (line, fname), info in function_insertions.items():
            valid_params = {
                param_name: param_type
                for param_name, param_type in info["params"].items()
                if validated[(line, fname, param_name)].is_valid
            }
            return_type = info["return_type"]
            valid_return = (
                return_type
                if return_type is not None and validated[(line, fname, "return")].is_valid
                else None
            )
            if valid_params or valid_return is not None:
                result[(line, fname)] = {
                    "name": info["name"],
                    "params": valid_params,
                    "return_type": valid_return,
                }
        return result

    async def _select_best_valid_variables(
        self,
        candidates: dict[tuple[str, str], list[tuple[int, str]]],
        source: str,
        import_hints: dict[tuple[int, str], ImportHint] | None = None,
    ) -> dict[tuple[int, str], TypeValidationResult]:
        """Pick most-recent mypy-valid binding per name; returns {(line0, name): result}."""
        if not candidates:
            return {}

        flat: dict[tuple[int, str], str] = {}
        for (_scope_id, name), bindings in candidates.items():
            for line0, type_str in bindings:
                flat[(line0, name)] = type_str

        if self._settings.mypy_inference_validation_enabled:
            validated = await self._type_validator.validate_bulk(
                flat, source, import_hints=import_hints
            )
        else:
            validated = {
                key: TypeValidationResult(type_str=type_str, is_valid=True)
                for key, type_str in flat.items()
            }

        selected: dict[tuple[int, str], TypeValidationResult] = {}
        for (_scope_id, name), bindings in candidates.items():
            for line0, _type_str in bindings:  # most-recent-first
                result = validated.get((line0, name))
                if result is not None and result.is_valid:
                    selected[(line0, name)] = result
                    break
        return selected

    def _build_targets(
        self,
        validated_vars: dict[tuple[int, str], TypeValidationResult] | None,
        variable_insertions: dict[tuple[int, str], str],
        function_insertions: dict[tuple[int, str], FunctionInsertionInfo],
        attribute_insertions: dict[tuple[int, str], str],
        source: str,
        import_hints: dict[tuple[int, str], ImportHint] | None = None,
        function_import_hints: Mapping[tuple[int, str, str], ImportHint] | None = None,
    ) -> list[InsertionTarget]:
        """Build InsertionTargets from validated vars (raw insertions when mypy off) + func/attr."""
        targets: list[InsertionTarget] = []
        source_index = build_source_index(source)
        # Built once per request: an annotation naming a class that is not bound yet where it
        # is written raises NameError on import before 3.14, and mypy cannot see it.
        forward_refs = build_forward_ref_context(source)

        # Variable targets. Keys are (line_0_based, name); resolve each to 1-based line + type.
        for key, value in (
            variable_insertions if validated_vars is None else validated_vars
        ).items():
            # isinstance, not `validated_vars is None` — mypy can't correlate that branch here.
            type_str = value.type_str if isinstance(value, TypeValidationResult) else value
            line_0_based, var_name = key
            resolved = (
                find_assignment_target_indexed(source_index, var_name, line_0_based)
                if source_index is not None
                else find_assignment_target(source, var_name, line_0_based)
            )

            if resolved is not None:
                line_1_based = resolved.line_1_based
                target_type = resolved.target_type
            else:
                line_1_based = find_variable_line(source, var_name)
                target_type = (
                    detect_assignment_pattern_indexed(source_index, var_name, line_1_based - 1)
                    if source_index is not None
                    else TargetType.VARIABLE_SIMPLE
                )

            targets.append(
                create_variable_target(
                    var_name,
                    forward_refs.quote_if_needed(type_str, line_1_based),
                    line_1_based,
                    target_type=target_type,
                    import_hint=(import_hints or {}).get(key),
                )
            )

        # Function targets.
        for (line_0_based, _func_name), sig_info in function_insertions.items():
            targets.extend(
                self._create_function_targets(
                    sig_info,
                    line_0_based + 1,
                    forward_refs,
                    function_import_hints,
                    line_0_based,
                )
            )

        # Attribute targets. Non-self stored dotted, self bare; _attr_key_full_name re-dots first.
        for (line_1_based, full_attr_name), type_str in attribute_insertions.items():
            obj_name, attr_name = _attr_key_full_name(full_attr_name).split(".", 1)
            targets.append(
                self._create_attribute_target(
                    obj_name,
                    attr_name,
                    forward_refs.quote_if_needed(type_str, line_1_based),
                    line_1_based,
                )
            )

        return targets

    def _create_function_targets(
        self,
        func_info: FunctionInsertionInfo,
        line: int,
        forward_refs: ForwardRefContext,
        import_hints: Mapping[tuple[int, str, str], ImportHint] | None = None,
        line_0_based: int | None = None,
    ) -> list[InsertionTarget]:
        """Create InsertionTarget objects for function parameter and return annotations.

        A signature is evaluated where the ``def`` stands, so both kinds are quoted against
        that line rather than against wherever the name they carry is defined.

        ``import_hints`` is keyed on the 0-based def line, which is why it is passed alongside
        the 1-based ``line`` the targets carry. A signature annotation needs its import as much
        as a variable one does, and until it carried one a synthesised ``Callable`` reached
        mypy as an undefined name and the gate dropped it.
        """
        targets = []
        func_name = func_info["name"]
        hints = import_hints or {}
        hint_line = line - 1 if line_0_based is None else line_0_based

        # Add parameter annotations
        params = func_info["params"]
        for param_name, param_type in params.items():
            target = InsertionTarget(
                target_type=TargetType.FUNCTION_PARAMETER,
                location=CodeLocation(line=line, column=0),
                type_annotation=forward_refs.quote_if_needed(param_type, line),
                name=param_name,
                import_hint=hints.get((hint_line, func_name, param_name)),
            )
            targets.append(target)

        # Add return type annotation
        return_type = func_info["return_type"]
        if return_type:
            target = InsertionTarget(
                target_type=TargetType.FUNCTION_RETURN,
                location=CodeLocation(line=line, column=0),
                type_annotation=forward_refs.quote_if_needed(return_type, line),
                name=func_name,
                import_hint=hints.get((hint_line, func_name, "return")),
            )
            targets.append(target)

        return targets

    def _create_attribute_target(
        self, obj_name: str, attr_name: str, type_annotation: str, line: int
    ) -> InsertionTarget:
        """Build an ATTRIBUTE_ACCESS target for ``obj.attr`` assigned at ``line``."""
        return InsertionTarget(
            target_type=TargetType.ATTRIBUTE_ACCESS,
            location=CodeLocation(line=line, column=0),
            type_annotation=type_annotation,
            name=f"{obj_name}.{attr_name}",
        )

    @staticmethod
    def _select_target_for_name(
        targets: list[InsertionTarget], name_loc: NameLocation
    ) -> InsertionTarget | None:
        """Pick the target matching the cursor name by line (exact > at-or-before > nearest)."""
        by_name = [t for t in targets if t.name == name_loc.name]
        if not by_name:
            return None
        exact = [t for t in by_name if t.location.line == name_loc.line]
        if exact:
            return exact[0]
        at_or_before = [t for t in by_name if t.location.line <= name_loc.line]

        # Named key funcs, not lambdas: an unannotated lambda to max/min trips disallow_any_expr.
        def target_line(t: InsertionTarget) -> int:
            return t.location.line

        def target_distance(t: InsertionTarget) -> int:
            return abs(t.location.line - name_loc.line)

        if at_or_before:
            return max(at_or_before, key=target_line)
        return min(by_name, key=target_distance)

    @staticmethod
    def _annotate_failure(name: str | None, message: str) -> dict[str, object]:
        """Uniform failure payload for annotate_at_position."""
        return {
            "name": name,
            "inferred_type": None,
            "modified_source": None,
            "insertion_success": False,
            "error_message": message,
        }

    def _collect_types_from_scopes(self, inference_result: InferenceResult) -> dict[str, str]:
        """Collect every non-Unknown type from all scopes, keyed {scope_id}.{cat}.{name} (sync)."""
        all_types: dict[str, str] = {}
        for scope_id, scope_obj in inference_result.scope_tree.scopes_by_id.items():
            # Collect local variables
            for var_name, type_info in scope_obj.variables.items():
                if type_info.type_str != "Unknown":
                    key = f"{scope_id}.var.{var_name}"
                    all_types[key] = type_info.type_str

            # Collect function parameters and return types
            if scope_obj.scope_type == ScopeType.FUNCTION:
                for param_name, type_info in scope_obj.parameters.items():
                    if type_info.type_str != "Unknown":
                        key = f"{scope_id}.param.{param_name}"
                        all_types[key] = type_info.type_str

                if scope_obj.return_type and scope_obj.return_type.type_str != "Unknown":
                    key = f"{scope_id}.return"
                    all_types[key] = scope_obj.return_type.type_str

        return all_types


def _attr_key_full_name(key_name: str) -> str:
    """Self attrs are stored bare ('width'); non-self dotted ('obj.x')."""
    return key_name if "." in key_name else f"self.{key_name}"


def _bucket_variable_drop_reasons(
    candidates: dict[tuple[str, str], list[tuple[int, str]]],
    selected: dict[tuple[int, str], TypeValidationResult],
) -> dict[str, int]:
    """Bucket surfaced variable names into 'selected' vs 'all_mypy_invalid' (insert diagnostic)."""
    if not candidates:
        return {}
    selected_keys = set(selected)
    reasons = {"selected": 0, "all_mypy_invalid": 0}
    for (_scope_id, name), bindings in candidates.items():
        if any((line0, name) in selected_keys for line0, _type_str in bindings):
            reasons["selected"] += 1
        else:
            reasons["all_mypy_invalid"] += 1
    return reasons


# mypy error codes that mean "the annotation just written does not hold" — the ones the
# assignability gate acts on. `assignment` covers variables/attributes (`x: int = "s"`),
# `arg-type` covers parameters at their call sites, and `return-value` covers a signature's
# return against what the body yields. The last two are about a standalone declaration rather
# than a fit: `no-redef` fires when the declaration lands after another binding of the name,
# and `name-defined` when the annotation names something the file never imports — which on
# 3.12 and 3.13 is not a failed check but a NameError at import.
_INCOMPATIBLE_CODES = frozenset(
    {"assignment", "arg-type", "return-value", "no-redef", "name-defined"}
)


def _flagged_target_lines(
    targets: list[InsertionTarget],
    source: str,
    modified: str,
    diagnostics: list[MypyDiagnostic],
) -> set[int]:
    """Original 1-based lines that (a) host a target and (b) carry an incompatible-type error.

    mypy reports against the MODIFIED file's line numbers; we map each error line back to its
    original line via difflib before intersecting with the targets' lines. Only lines that host
    a target are returned, so a collateral error elsewhere never drops an unrelated annotation.
    """
    target_lines = {t.location.line for t in targets}
    error_mod_lines = {
        d.line for d in diagnostics if d.severity == "error" and d.error_code in _INCOMPATIBLE_CODES
    }
    if not error_mod_lines:
        return set()

    mod_to_orig = _map_modified_to_original(source, modified)
    flagged = {
        orig
        for mod_line in error_mod_lines
        if (orig := mod_to_orig.get(mod_line)) is not None and orig in target_lines
    }
    return flagged


def _map_modified_to_original(source: str, modified: str) -> dict[int, int]:
    """Map each 1-based modified-file line to the 1-based original line it derives from.

    Built from difflib opcodes. `equal`/`replace` blocks pair lines positionally, and a purely
    inserted line — a DECLARATION annotation, which has no original counterpart — maps to the
    original statement it was written above, which is the line its target carries. Without that
    the gate discards every diagnostic landing on a declaration it wrote, and `no-redef` and
    `name-defined` land nowhere else.
    """
    orig = source.splitlines()
    mod = modified.splitlines()
    mapping: dict[int, int] = {}
    # ponytail: difflib is O(n*m) worst case, but only runs after mypy already did and only on an
    # explicit insert action; fine at source-file scale.
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=orig, b=mod, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                mapping[j1 + k + 1] = i1 + k + 1
        elif tag == "replace":
            span = i2 - i1
            for k in range(j2 - j1):
                # min(k, span-1): defensive clamp for an unequal-span replace. Real insertions are
                # IN_PLACE 1->1 or DECLARATION insert+equal, never unequal replace — it won't fire.
                mapping[j1 + k + 1] = i1 + min(k, span - 1) + 1
        elif tag == "insert":
            # i1 is where the block was spliced in, so original line i1+1 is the statement now
            # standing below it. An insert at end-of-file has none, and maps to the last line.
            origin = min(i1 + 1, len(orig)) if orig else 0
            if origin:
                for k in range(j2 - j1):
                    mapping[j1 + k + 1] = origin
        # delete: no modified line to map at all.
    return mapping


def _select_key_by_line(keys: list[tuple[int, str]], line_0_based: int) -> tuple[int, str]:
    """Pick the insertion-dict key nearest a cursor line (exact > at-or-before > nearest)."""
    exact = [k for k in keys if k[0] == line_0_based]
    if exact:
        return exact[0]
    at_or_before = [k for k in keys if k[0] <= line_0_based]

    # Named key funcs, not lambdas: an unannotated lambda to max/min trips disallow_any_expr.
    def key_line(k: tuple[int, str]) -> int:
        return k[0]

    def key_distance(k: tuple[int, str]) -> int:
        return abs(k[0] - line_0_based)

    if at_or_before:
        return max(at_or_before, key=key_line)
    return min(keys, key=key_distance)


def _restrict_to_target(
    only: tuple[str, int],
    variable_insertions: dict[tuple[int, str], str],
    function_insertions: dict[tuple[int, str], FunctionInsertionInfo],
    attribute_insertions: dict[tuple[int, str], str],
) -> tuple[
    dict[tuple[int, str], str],
    dict[tuple[int, str], FunctionInsertionInfo],
    dict[tuple[int, str], str],
]:
    """Restrict inference's insertion dicts to the single cursor target `(name, line_0based)`."""
    name, line_0_based = only

    variable_matches = {k: v for k, v in variable_insertions.items() if k[1] == name}
    restricted_vars: dict[tuple[int, str], str] = {}
    if variable_matches:
        best = _select_key_by_line(list(variable_matches), line_0_based)
        restricted_vars = {best: variable_matches[best]}

    restricted_attrs = {
        k: v for k, v in attribute_insertions.items() if _attr_key_full_name(k[1]) == name
    }

    restricted_funcs = {
        k: info for k, info in function_insertions.items() if k[1] == name or name in info["params"]
    }

    return restricted_vars, restricted_funcs, restricted_attrs
