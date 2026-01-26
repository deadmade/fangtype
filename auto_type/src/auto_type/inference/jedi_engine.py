"""Jedi-based type inference engine for Python.

This module provides a production-grade type inference engine using Jedi 0.19.2,
replacing custom inference with battle-tested library used by VSCode, IPython, and Jupyter.

Key Jedi APIs used:
- Name.get_type_hint() - Extract explicit type annotations
- Name.execute() - Analyze function return values
- Name.infer() - General type inference
- Script.infer(line, col) - Positional type inference
- Script.get_names() - Get all definitions in code

All public methods are async and use asyncio.to_thread() to run
the blocking Jedi calls without blocking the event loop.
"""

import ast
import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jedi

from auto_type.analysis.types import Scope, ScopeTree, ScopeType, TypeInfo, TypeSource

if TYPE_CHECKING:
    from auto_type.inference.inference_result import InferenceResult

logger = logging.getLogger(__name__)


class JediInferenceEngine:
    """Jedi-based type inference engine matching UnifiedInferenceEngine API.

    Uses Jedi (https://jedi.readthedocs.io/) for type inference instead of
    custom analysis. Jedi is used by major Python tools including VSCode,
    IPython, and Jupyter, providing production-grade inference accuracy.

    Key features:
    - Accurate type inference using Jedi's battle-tested algorithms
    - Full compatibility with existing UnifiedInferenceEngine API
    - Minimal call graph construction for function type insertion support
    - Handles modern Python 3.12+ type syntax
    - All public methods are async for non-blocking LSP operation

    Usage:
        engine = JediInferenceEngine()
        result = await engine.infer_types(source_code)
        types_map = await engine.infer_variable_types(source_code)
    """

    def __init__(self) -> None:
        """Initialize the Jedi inference engine."""
        pass  # No state needed

    def _find_project_root(self, path: str | None) -> tuple[str | None, jedi.Project | None]:
        """Find project root and validate path for Jedi inference.

        Validates the path exists (VS Code may send virtual/temporary paths),
        then searches for project markers (pyproject.toml or setup.py) up the
        directory tree.

        Args:
            path: Optional file path to validate and search from

        Returns:
            Tuple of (validated_path, jedi_project). validated_path is None if
            the path doesn't exist. jedi_project is None if no project root found.
        """
        if not path:
            return None, None

        # Validate path exists - VS Code may send virtual/temporary paths
        path_obj = Path(path)
        try:
            if not path_obj.exists():
                logger.debug(f"File path does not exist, using in-memory mode: {path}")
                return None, None
        except (OSError, PermissionError) as e:
            logger.debug(f"Error accessing file path {path}: {e}")
            return None, None

        # Search for project root
        try:
            project_path = path_obj.resolve().parent
            while project_path != project_path.parent:
                if (project_path / "pyproject.toml").exists() or (
                    project_path / "setup.py"
                ).exists():
                    return path, jedi.Project(str(project_path))
                project_path = project_path.parent
        except (OSError, PermissionError) as e:
            logger.debug(f"Error searching for project root: {e}")

        return path, None

    async def infer_types(self, source: str, path: str | None = None) -> "InferenceResult":
        """Perform complete type inference on Python source code using Jedi.

        Args:
            source: Python source code string
            path: Optional file path for project-aware inference

        Returns:
            InferenceResult with scope tree and inferred types
        """
        return await asyncio.to_thread(self._infer_types_sync, source, path)

    def _infer_types_sync(self, source: str, path: str | None = None) -> "InferenceResult":
        """Synchronous implementation of infer_types."""
        from auto_type.inference.inference_result import InferenceResult

        try:
            validated_path, project = self._find_project_root(path)
            script = jedi.Script(source, path=validated_path, project=project)

            try:
                tree = ast.parse(source)
            except SyntaxError as e:
                logger.debug(f"Failed to parse source: {e}")
                module_scope = Scope(
                    scope_id="module",
                    scope_type=ScopeType.MODULE,
                    name="<module>",
                    ast_node=ast.Module(body=[], type_ignores=[]),
                )
                scope_tree = ScopeTree(root=module_scope)
                scope_tree.add_scope(module_scope)
                return InferenceResult(
                    scope_tree=scope_tree,
                    source=source,
                )

            scope_tree = self._build_scope_tree_from_jedi(script, tree)

            return InferenceResult(
                scope_tree=scope_tree,
                source=source,
            )

        except Exception as e:
            logger.error(f"Error in Jedi inference: {e}", exc_info=True)
            module_scope = Scope(
                scope_id="module",
                scope_type=ScopeType.MODULE,
                name="<module>",
                ast_node=ast.Module(body=[], type_ignores=[]),
            )
            scope_tree = ScopeTree(root=module_scope)
            scope_tree.add_scope(module_scope)
            return InferenceResult(
                scope_tree=scope_tree,
                source=source,
            )

    async def infer_variable_types(self, source: str) -> dict[str, str]:
        """Get module-level variable types (compatibility API).

        Returns module-level variables only for backward compatibility
        with insertion/diagnostic code.

        Args:
            source: Python source code

        Returns:
            Dict mapping variable names to type strings (module-level only)
        """
        return await asyncio.to_thread(self._infer_variable_types_sync, source)

    def _infer_variable_types_sync(self, source: str) -> dict[str, str]:
        """Synchronous implementation of infer_variable_types."""
        result = self._infer_types_sync(source)
        types_map: dict[str, str] = {}

        for var_name, type_info in result.scope_tree.root.variables.items():
            if type_info.type_str != "Unknown":
                types_map[var_name] = type_info.type_str

        return types_map

    async def infer_types_at_locations(
        self,
        source: str,
        locations: list[tuple[int, int]],
        path: str | None = None,
    ) -> dict[tuple[int, int], str]:
        """Infer types at multiple specific locations in the source code.

        This method uses Jedi's positional inference to get the type of whatever
        identifier or expression is at each (line, column) position. Used for
        generating inlay hints at variable usage sites.

        Args:
            source: Python source code string
            locations: List of (line, col) tuples where line is 1-based and col is 0-based
            path: Optional file path for project-aware inference

        Returns:
            Dict mapping (line, col) to inferred type string. Locations where
            inference fails or returns Unknown are omitted from the result.
        """
        return await asyncio.to_thread(self._infer_types_at_locations_sync, source, locations, path)

    def _infer_types_at_locations_sync(
        self,
        source: str,
        locations: list[tuple[int, int]],
        path: str | None = None,
    ) -> dict[tuple[int, int], str]:
        """Synchronous implementation of infer_types_at_locations."""
        results: dict[tuple[int, int], str] = {}

        if not locations:
            return results

        try:
            validated_path, project = self._find_project_root(path)
            script = jedi.Script(source, path=validated_path, project=project)

            for line, col in locations:
                try:
                    inferences = script.infer(line, col)
                    if inferences:
                        type_str = self._extract_type_from_inferences(inferences)
                        if type_str and type_str != "Unknown":
                            results[(line, col)] = type_str
                except Exception as e:
                    logger.debug(f"Failed to infer type at {line}:{col}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in infer_types_at_locations: {e}", exc_info=True)

        return results

    def _extract_type_from_inferences(self, inferences: list[Any]) -> str:
        """Extract type string from Jedi inference results.

        Args:
            inferences: List of Jedi Name objects from script.infer()

        Returns:
            Type string, possibly a union if multiple types are inferred
        """
        if not inferences:
            return "Unknown"

        # Check for function references first
        if inferences[0].type == "function":
            return "callable"

        type_names: set[str] = set()

        for inference in inferences:
            type_name = str(inference.name)

            if inference.module_name == "builtins":
                if type_name == "NoneType":
                    type_names.add("None")
                elif type_name and type_name != "Unknown":
                    type_names.add(type_name)
            elif inference.module_name == "itertools":
                if type_name and type_name != "Unknown":
                    type_names.add(f"itertools.{type_name}")
            elif inference.type == "instance":
                try:
                    instance_hint = inference.get_type_hint()
                    if instance_hint and instance_hint != "None":
                        type_names.add(instance_hint)
                    elif type_name and type_name != "Unknown":
                        type_names.add(type_name)
                except (AttributeError, TypeError) as e:
                    logger.debug(f"Could not get type hint for instance: {e}")
                    if type_name and type_name != "Unknown":
                        type_names.add(type_name)
            else:
                if type_name and type_name != "Unknown":
                    type_names.add(type_name)

        type_names.discard("Unknown")

        if not type_names:
            return "Unknown"

        # Normalize all types
        normalized_types: set[str] = set()
        for t in type_names:
            normalized = self._normalize_type_name(t)
            if normalized and normalized != "Unknown":
                normalized_types.add(normalized)

        if not normalized_types:
            return "Unknown"

        if len(normalized_types) == 1:
            return normalized_types.pop()

        # Create union: sort for consistency (None always last)
        sorted_types = sorted(normalized_types, key=lambda x: (x == "None", x))
        return " | ".join(sorted_types)

    async def infer_expression_type(self, source: str, expression: str) -> str | None:
        """Infer type of any Python expression using synthetic assignment query.

        This method leverages Jedi's full inference capabilities by creating
        a synthetic assignment statement and querying the assigned variable's type.
        Enhanced with get_type_hint() for better type extraction.

        Args:
            source: Original Python source code
            expression: Python expression to infer type for (e.g., "names[0]", "dict['key']")

        Returns:
            Type string if inference succeeds, None otherwise

        Examples:
            >>> type_str = await engine.infer_expression_type(code, "names[0]")
            "str"
            >>> type_str = await engine.infer_expression_type(code, "result[0][1]")
            "int"
            >>> type_str = await engine.infer_expression_type(code, "my_dict['key']")
            "int"
        """
        return await asyncio.to_thread(self._infer_expression_type_sync, source, expression)

    def _infer_expression_type_sync(self, source: str, expression: str) -> str | None:
        """Synchronous implementation of infer_expression_type."""
        synthetic_code = source
        if not source.endswith("\n"):
            synthetic_code += "\n"
        synthetic_code += f"__jedi_query_temp__ = {expression}\n"

        try:
            script = jedi.Script(synthetic_code)

            lines = synthetic_code.splitlines()
            synthetic_line = None
            for i, line in enumerate(lines, 1):
                if "__jedi_query_temp__" in line:
                    synthetic_line = i
                    break

            if synthetic_line is None:
                logger.debug(f"Could not find synthetic assignment line for '{expression}'")
                return None

            inferences = script.infer(synthetic_line, 0)

            for inference in inferences:
                try:
                    type_hint = inference.get_type_hint()
                    if type_hint:
                        if ":" in type_hint:
                            type_str = type_hint.split(":", 1)[-1].strip()
                        else:
                            type_str = type_hint.strip()

                        if type_str:
                            normalized = self._normalize_type_name(type_str)
                            if normalized and normalized != "None":
                                return normalized
                except (AttributeError, TypeError) as e:
                    logger.debug(f"Could not get type hint for expression: {e}")

                type_name = str(inference.name)

                if inference.module_name == "builtins":
                    type_name = str(inference.name)

                type_name = self._normalize_type_name(type_name)

                if type_name and type_name != "None":
                    return type_name

        except Exception as e:
            logger.debug(f"Failed to infer expression type for '{expression}': {e}")
            return None

        return None

    def _get_names_with_timeout(self, script: jedi.Script, timeout: float = 5.0) -> list[Any]:
        """Get names from Jedi with timeout protection.

        Jedi's get_names() can hang on complex files with many imports.
        This method wraps the call with a timeout to fail fast.

        Args:
            script: Jedi Script object
            timeout: Timeout in seconds (default 5.0)

        Returns:
            List of Jedi Name objects, or empty list on timeout
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                script.get_names, all_scopes=True, definitions=True, references=False
            )
            try:
                result = future.result(timeout=timeout)
                return list(result) if result else []
            except concurrent.futures.TimeoutError:
                logger.warning(f"Jedi get_names() timed out after {timeout}s")
                return []
            except Exception as e:
                logger.debug(f"Jedi get_names() failed: {e}")
                return []

    def _build_scope_tree_from_jedi(self, script: jedi.Script, tree: ast.Module) -> ScopeTree:
        """Build hierarchical scope tree using pure Jedi API (no custom AST traversal).

        This method replaces the entire ScopeTreeBuilder with direct Jedi queries,
        eliminating ~1000 lines of custom inference logic.

        Args:
            script: Jedi Script object with full project context
            tree: Parsed AST module (for error fallback only)

        Returns:
            ScopeTree with all scopes and inferred types from Jedi
        """
        # Create module scope (root)
        module_scope = Scope(
            scope_id="module",
            scope_type=ScopeType.MODULE,
            name="<module>",
            ast_node=tree,
        )

        scope_tree = ScopeTree(root=module_scope)
        scope_tree.add_scope(module_scope)

        # Build a map of function/class names to their AST nodes for proper line ranges
        ast_node_map: dict[tuple[int, str], ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                # Use (line, name) as key to handle functions with same name on different lines
                ast_node_map[(node.lineno, node.name)] = node

        # Get all definitions from Jedi (with timeout protection)
        names = self._get_names_with_timeout(script)
        if not names:
            logger.debug("No names returned from Jedi (possible timeout or empty file)")
            return scope_tree

        # Maps to track scopes we've created
        # Key: (parent_name, scope_name) -> Scope object
        scope_map: dict[tuple[str | None, str], Scope] = {(None, "<module>"): module_scope}

        # First pass: Create all function and class scopes
        for name in names:
            if name.type in ("function", "class"):
                parent_jedi = name.parent()
                parent_scope = self._find_parent_scope(parent_jedi, scope_map, module_scope)

                # Determine scope type
                if name.type == "function":
                    scope_type = ScopeType.FUNCTION
                    scope_id_prefix = "func"
                else:  # class
                    scope_type = ScopeType.CLASS
                    scope_id_prefix = "class"

                # Generate unique scope ID
                parent_key = self._get_scope_key(parent_scope)
                scope_id = f"{scope_id_prefix}:{parent_key}.{name.name}"

                # Try to get the real AST node for proper line ranges
                # Key is (line_number, name) - Jedi uses 1-based line numbers
                ast_key = (name.line, name.name) if name.line else (1, name.name)
                real_ast_node = ast_node_map.get(ast_key)

                # Create or use AST node for the scope
                ast_node: ast.AST
                if real_ast_node is not None:
                    # Use the real AST node which has proper line ranges
                    ast_node = real_ast_node
                elif name.type == "class":
                    ast_node = ast.ClassDef(
                        name=name.name,
                        bases=[],
                        keywords=[],
                        body=[ast.Pass()],
                        decorator_list=[],
                        type_params=[],
                    )
                    # Set required AST position attributes from Jedi data
                    # (automatically set by ast.parse but must be manual here)
                    ast_node.lineno = name.line if name.line is not None else 1
                    ast_node.col_offset = name.column if name.column is not None else 0
                    ast_node.end_lineno = name.line if name.line is not None else 1
                    ast_node.end_col_offset = (name.column if name.column is not None else 0) + len(
                        name.name
                    )
                else:
                    ast_node = ast.FunctionDef(
                        name=name.name,
                        args=ast.arguments(
                            posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]
                        ),
                        body=[ast.Pass()],
                        decorator_list=[],
                        type_params=[],
                    )
                    # Set required AST position attributes from Jedi data
                    # Required by server.py:231 for return type hint positioning
                    ast_node.lineno = name.line if name.line is not None else 1
                    ast_node.col_offset = name.column if name.column is not None else 0
                    ast_node.end_lineno = name.line if name.line is not None else 1
                    ast_node.end_col_offset = (name.column if name.column is not None else 0) + len(
                        name.name
                    )

                # Create scope
                new_scope = Scope(
                    scope_id=scope_id,
                    scope_type=scope_type,
                    name=name.name,
                    ast_node=ast_node,
                    parent=parent_scope,
                )

                # Add to tree and tracking
                scope_tree.add_scope(new_scope)
                parent_scope.children.append(new_scope)

                # Track this scope
                scope_key = (self._get_scope_name(parent_jedi), name.name)
                scope_map[scope_key] = new_scope

        # Second pass: Add variables, parameters, and infer types
        for name in names:
            parent_jedi = name.parent()
            parent_scope = self._find_parent_scope(parent_jedi, scope_map, module_scope)

            if name.type == "param":
                # Function parameter
                type_str = self._infer_jedi_type(name)
                line = (name.line - 1) if name.line is not None else 0
                col = name.column if name.column is not None else 0
                type_info = TypeInfo(
                    type_str=type_str,
                    source=TypeSource.LITERAL,  # Jedi inferred
                    line=line,  # Jedi uses 1-based, we use 0-based
                    col=col,
                    ast_node=None,
                )
                parent_scope.add_parameter(name.name, type_info)

            elif name.type == "statement":
                # Variable assignment
                type_str = self._infer_jedi_type(name)
                line = (name.line - 1) if name.line is not None else 0
                col = name.column if name.column is not None else 0
                type_info = TypeInfo(
                    type_str=type_str,
                    source=TypeSource.LITERAL,  # Jedi inferred
                    line=line,  # Jedi uses 1-based, we use 0-based
                    col=col,
                    ast_node=None,
                )
                parent_scope.add_variable(name.name, type_info)

            elif name.type == "function":
                # Infer return type for functions
                scope_key = (self._get_scope_name(parent_jedi), name.name)
                if scope_key in scope_map:
                    func_scope = scope_map[scope_key]
                    return_type_str = self._infer_function_return_type(name)
                    if return_type_str and return_type_str != "Unknown":
                        line = (name.line - 1) if name.line is not None else 0
                        col = name.column if name.column is not None else 0
                        func_scope.return_type = TypeInfo(
                            type_str=return_type_str,
                            source=TypeSource.RETURN_VALUE,
                            line=line,
                            col=col,
                            ast_node=None,
                        )

        return scope_tree

    def _find_parent_scope(
        self,
        parent_jedi: Any,  # jedi.api.classes.Name or None
        scope_map: dict[tuple[str | None, str], Scope],
        module_scope: Scope,
    ) -> Scope:
        """Find the parent scope for a Jedi name.

        Args:
            parent_jedi: Jedi parent Name object (or None for module-level)
            scope_map: Map of (parent_name, scope_name) -> Scope
            module_scope: Root module scope

        Returns:
            Parent Scope object
        """
        if parent_jedi is None or parent_jedi.type == "module":
            return module_scope

        # Try to find in scope_map
        grandparent = parent_jedi.parent()
        grandparent_name = self._get_scope_name(grandparent)
        parent_key = (grandparent_name, parent_jedi.name)

        if parent_key in scope_map:
            return scope_map[parent_key]

        # Fallback to module
        return module_scope

    def _get_scope_name(self, jedi_name: Any) -> str | None:
        """Get scope name from Jedi Name object."""
        if jedi_name is None or jedi_name.type == "module":
            return None
        return str(jedi_name.name)

    def _get_scope_key(self, scope: Scope) -> str:
        """Get a string key for a scope (for generating unique scope IDs)."""
        if scope.scope_type == ScopeType.MODULE:
            return "module"
        if scope.parent and scope.parent.scope_type != ScopeType.MODULE:
            return f"{self._get_scope_key(scope.parent)}.{scope.name}"
        return scope.name

    def _infer_jedi_type(self, name: Any) -> str:
        """Infer type for a Jedi Name using Jedi's multi-step approach.

        Returns union types when Jedi infers multiple possibilities.
        Example: If Jedi returns [int, NoneType], returns "int | None"

        This provides better type safety for LSP users while maintaining
        benchmark compatibility through smart union matching.

        Strategy:
        1. Try get_type_hint() - check for explicit type annotation
        2. Collect ALL inferences from infer() (not just first)
        3. Filter and combine into union if multiple types exist
        4. Special handling: function references -> "callable"

        Args:
            name: Jedi Name object

        Returns:
            Type string (may be union, e.g., "int | None")
        """
        try:
            # STEP 1: Check for function references first - map to 'callable'
            # Must check BEFORE get_type_hint() which returns function signatures
            inferences = name.infer()
            if not inferences:
                return "Unknown"

            if inferences[0].type == "function":
                return "callable"

            # STEP 2: Check for explicit type annotation
            try:
                type_hint = name.get_type_hint()
                if type_hint:
                    if ":" in type_hint:
                        type_str = type_hint.split(":", 1)[-1].strip()
                    else:
                        type_str = type_hint.strip()

                    # FIX: Ignore literal "None" string from get_type_hint()
                    # This happens when Jedi can't determine the annotation
                    if type_str and type_str not in ("None", name.name):
                        # Check if this is an itertools type - prefix with module
                        # (Jedi returns type_hint without module prefix for itertools)
                        if inferences and inferences[0].module_name == "itertools":
                            type_str = f"itertools.{type_str}"
                        normalized = self._normalize_type_name(type_str)
                        if normalized and normalized not in ("Unknown", "None"):
                            return normalized
            except Exception as e:
                logger.debug(f"get_type_hint() failed for {name.name}: {e}")

            # STEP 3: Collect ALL inferences (already have inferences from step 1)

            # Collect all unique type names
            type_names: set[str] = set()

            for inference in inferences:
                type_name = str(inference.name)

                # Handle builtin types
                if inference.module_name == "builtins":
                    # Map NoneType to None for consistency
                    if type_name == "NoneType":
                        type_names.add("None")
                    elif type_name and type_name != "Unknown":
                        type_names.add(type_name)
                elif inference.module_name == "itertools":
                    # Handle itertools types - prefix with module name
                    # e.g., "cycle" -> "itertools.cycle"
                    if type_name and type_name != "Unknown":
                        type_names.add(f"itertools.{type_name}")
                elif inference.type == "instance":
                    # Try to get type hint from instance
                    try:
                        instance_hint = inference.get_type_hint()
                        if instance_hint and instance_hint != "None":
                            type_names.add(instance_hint)
                        elif type_name and type_name != "Unknown":
                            type_names.add(type_name)
                    except (AttributeError, TypeError) as e:
                        logger.debug(f"Could not get instance type hint: {e}")
                        if type_name and type_name != "Unknown":
                            type_names.add(type_name)
                else:
                    # Other types (classes, modules, etc.)
                    if type_name and type_name != "Unknown":
                        type_names.add(type_name)

            # Filter out Unknown
            type_names.discard("Unknown")

            if not type_names:
                return "Unknown"

            # Normalize all types
            normalized_types: set[str] = set()
            for t in type_names:
                normalized = self._normalize_type_name(t)
                if normalized and normalized != "Unknown":
                    normalized_types.add(normalized)

            if not normalized_types:
                return "Unknown"

            # Return single type or union
            if len(normalized_types) == 1:
                return normalized_types.pop()

            # Create union: sort for consistency (None always last)
            # e.g., "int | None" not "None | int"
            sorted_types = sorted(normalized_types, key=lambda x: (x == "None", x))
            return " | ".join(sorted_types)

        except Exception as e:
            logger.debug(f"Failed to infer type for {name.name}: {e}")

        return "Unknown"

    def _infer_function_return_type(self, func_name: Any) -> str:
        """Infer return type for a function using Jedi's multi-step approach.

        Strategy:
        1. Try get_type_hint() - check for explicit return annotation
        2. Try execute() - analyze return statements
        3. Try infer() - general type inference fallback

        Args:
            func_name: Jedi Name object for the function

        Returns:
            Return type string (normalized to Python 3.12+ syntax)
        """
        try:
            # STEP 1: Check for explicit return type annotation
            try:
                type_hint = func_name.get_type_hint()
                # Parse the type hint to extract return type
                # Format: "(...) -> ReturnType" or just "ReturnType"
                if type_hint and " -> " in type_hint:
                    return_type = type_hint.split(" -> ")[-1].strip()
                    if return_type and return_type not in ("None", "NoneType"):
                        normalized = self._normalize_type_name(return_type)
                        if normalized and normalized != "Unknown":
                            return normalized
            except Exception as e:
                logger.debug(f"get_type_hint() failed for {func_name.name}: {e}")

            # STEP 2: Try to infer from return statements using execute()
            try:
                return_values = func_name.execute()
                if return_values:
                    # Collect types from all possible return values
                    return_types = set()
                    for rv in return_values:
                        type_name = str(rv.name)
                        # Handle builtin types
                        if rv.module_name == "builtins" and type_name:
                            return_types.add(type_name)
                        # Get type hint from return value if available
                        elif hasattr(rv, "get_type_hint"):
                            try:
                                rv_hint = rv.get_type_hint()
                                if rv_hint:
                                    return_types.add(rv_hint)
                            except (AttributeError, TypeError) as e:
                                logger.debug(f"Could not get return value type hint: {e}")

                    if return_types:
                        # Remove None if other types exist
                        if len(return_types) > 1:
                            return_types.discard("None")
                            return_types.discard("NoneType")

                        # Single type or union
                        if len(return_types) == 1:
                            type_str = return_types.pop()
                        else:
                            type_str = " | ".join(sorted(return_types))

                        normalized = self._normalize_type_name(type_str)
                        if normalized and normalized != "Unknown":
                            return normalized
            except Exception as e:
                logger.debug(f"execute() failed for {func_name.name}: {e}")

            # STEP 3: Fallback to general inference
            inferences = func_name.infer()
            if inferences:
                for inference in inferences:
                    if inference.type == "function":
                        # Try to get type hint from the inference
                        try:
                            hint = inference.get_type_hint()
                            if hint and " -> " in hint:
                                return_type = hint.split(" -> ")[-1].strip()
                                if return_type and return_type not in ("None", "NoneType"):
                                    normalized = self._normalize_type_name(return_type)
                                    if normalized and normalized != "Unknown":
                                        return normalized
                        except (AttributeError, TypeError) as e:
                            logger.debug(f"Could not get function type hint: {e}")

        except Exception as e:
            logger.debug(f"Failed to infer return type for {func_name.name}: {e}")

        return "Unknown"

    def _normalize_type_name(self, type_name: str) -> str:
        """Normalize type names to modern Python 3.12+ syntax.

        Args:
            type_name: Type name from Jedi

        Returns:
            Normalized type name
        """
        # Handle Optional[T] -> T | None
        if type_name.startswith("Optional[") and type_name.endswith("]"):
            inner = type_name[9:-1]
            return f"{self._normalize_type_name(inner)} | None"

        # Handle Union[A, B] -> A | B
        if type_name.startswith("Union[") and type_name.endswith("]"):
            inner = type_name[6:-1]
            parts = self._split_type_args(inner)
            normalized_parts = [self._normalize_type_name(p) for p in parts]
            # Remove None from parts and handle it at the end if present
            has_none = "None" in normalized_parts
            if has_none:
                normalized_parts = [p for p in normalized_parts if p != "None"]

            result = " | ".join(sorted(normalized_parts))
            if has_none:
                result = f"{result} | None"
            return result

        # Map old-style to new-style types
        replacements = {
            "List": "list",
            "Dict": "dict",
            "Set": "set",
            "Tuple": "tuple",
            "FrozenSet": "frozenset",
            "Generator": "generator",
        }

        for old, new in replacements.items():
            if type_name == old:
                return new
            # Handle generic types like List[int] -> list[int]
            if type_name.startswith(f"{old}["):
                inner = type_name[len(old) + 1 : -1]
                return f"{new}[{self._normalize_type_name(inner)}]"

        return type_name

    def _split_type_args(self, args_str: str) -> list[str]:
        """Split type arguments string by comma, respecting brackets.

        Args:
            args_str: String like "int, List[str]"

        Returns:
            List of parts ["int", "List[str]"]
        """
        parts = []
        current = []
        depth = 0

        for char in args_str:
            if char == "[":
                depth += 1
                current.append(char)
            elif char == "]":
                depth -= 1
                current.append(char)
            elif char == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(char)

        if current:
            parts.append("".join(current).strip())

        return parts
