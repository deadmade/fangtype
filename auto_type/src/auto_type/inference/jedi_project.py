"""Jedi project discovery utilities.

This module provides functions for discovering and configuring Jedi projects
for type inference operations.
"""

import logging
from pathlib import Path

import jedi

logger = logging.getLogger(__name__)


def find_project_root(
    path: str | None, explicit_project_root: str | None = None
) -> tuple[str | None, jedi.Project | None]:
    """Find project root and validate path for Jedi inference.

    Args:
        path: The file path to analyze
        explicit_project_root: Optional explicit project root path

    Returns:
        Tuple of (validated_path, jedi_project)
    """
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
                return path, jedi.Project(str(project_path))
        except OSError:
            pass
        except PermissionError:
            pass

    # Search for project root
    try:
        current_path = path_obj.absolute().parent
        while current_path != current_path.parent:
            if (current_path / "pyproject.toml").exists() or (current_path / "setup.py").exists():
                return path, jedi.Project(str(current_path))
            current_path = current_path.parent
    except (OSError, PermissionError) as e:
        logger.debug(f"Error searching for project root: {e}")

    return path, None
