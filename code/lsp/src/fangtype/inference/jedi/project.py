"""Jedi project discovery and configuration utilities for type inference."""

import logging
from pathlib import Path

import jedi

logger = logging.getLogger(__name__)

_PROJECT_CACHE: dict[str, jedi.Project] = {}


def _project_for(root: str) -> jedi.Project:
    proj = _PROJECT_CACHE.get(root)
    if proj is None:
        proj = jedi.Project(root)
        _PROJECT_CACHE[root] = proj
    return proj


def _package_import_root(project_path: Path) -> Path:
    """Return first ancestor lacking __init__.py (import root) so cross-module imports resolve."""
    import_root = project_path
    while (import_root / "__init__.py").exists() and import_root.parent != import_root:
        import_root = import_root.parent
    return import_root


def find_project_root(
    path: str | None, explicit_project_root: str | None = None
) -> tuple[str | None, jedi.Project | None]:
    """Validate path and find its Jedi project root, returning (validated_path, jedi_project)."""
    if not path:
        return None, None

    path_obj = Path(path)
    try:
        if not path_obj.exists():
            logger.warning(f"File path does not exist, using in-memory mode: {path}")
            return None, None
    except (OSError, PermissionError) as e:
        logger.warning(f"Error accessing file path {path}: {e}")
        return None, None

    # Use explicit project root if provided
    if explicit_project_root:
        try:
            project_path = Path(explicit_project_root).resolve()
            if project_path.exists():
                return path, _project_for(str(_package_import_root(project_path)))
        except OSError:
            pass
        except PermissionError:
            pass

    # Search for project root
    try:
        current_path = path_obj.absolute().parent
        while current_path != current_path.parent:
            if (current_path / "pyproject.toml").exists() or (current_path / "setup.py").exists():
                return path, _project_for(str(current_path))
            current_path = current_path.parent
    except (OSError, PermissionError) as e:
        logger.debug(f"Error searching for project root: {e}")

    return path, None
