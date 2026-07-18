"""Tests for find_project_root (extracted from the jedi inference edge cases)."""

from unittest.mock import patch

from fangtype.inference.jedi.project import find_project_root


class TestFindProjectRoot:
    """Project-root discovery behavior."""

    async def test_project_root_finding(self, engine, tmp_path):
        """Test finding project root via pyproject.toml."""
        project_dir = tmp_path / "my_project"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").touch()
        source_file = project_dir / "src" / "main.py"
        source_file.parent.mkdir()
        source_file.touch()

        # Test the standalone find_project_root function
        path, project = find_project_root(str(source_file))
        assert path == str(source_file)
        assert project is not None
        assert str(project.path) == str(project_dir)

    async def test_project_root_finding_no_file(self, engine):
        """Test project root finding with non-existent file."""
        path, project = find_project_root("/non/existent/path/file.py")
        assert path is None
        assert project is None

    async def test_explicit_project_root_walks_up_to_package_import_root(self, engine, tmp_path):
        """Explicit root in a package walks up past the top-level package so imports resolve."""
        checkout = tmp_path / "checkout"  # no __init__.py -> the import root
        sub = checkout / "pkg" / "sub"
        sub.mkdir(parents=True)
        (checkout / "pkg" / "__init__.py").touch()
        (sub / "__init__.py").touch()
        source_file = sub / "mod.py"
        source_file.touch()

        _path, project = find_project_root(str(source_file), explicit_project_root=str(sub))
        assert project is not None
        assert str(project.path) == str(checkout)

    async def test_explicit_project_root_without_package_is_unchanged(self, engine, tmp_path):
        """A plain explicit root (no __init__.py) is used as-is."""
        root = tmp_path / "repo"
        root.mkdir()
        source_file = root / "main.py"
        source_file.touch()

        _path, project = find_project_root(str(source_file), explicit_project_root=str(root))
        assert project is not None
        assert str(project.path) == str(root)

    async def test_project_root_finding_no_markers(self, engine, tmp_path):
        """Test project root finding when no markers exist."""
        # Create a file in a temp dir with no pyproject.toml
        source_file = tmp_path / "script.py"
        source_file.touch()

        path, project = find_project_root(str(source_file))
        assert path == str(source_file)
        # Should return None when no project markers found
        assert project is None

    async def test_project_root_finding_permission_error(self, engine, tmp_path):
        """Test handling of PermissionError during project root finding."""
        source_file = tmp_path / "script.py"
        source_file.touch()

        with patch("pathlib.Path.exists", side_effect=PermissionError("Permission denied")):
            path, project = find_project_root(str(source_file))
            # Should fail gracefully, return None or fallback
            assert path is None or path == str(source_file)
            # If path returned, project might be None or fallback
            if project:
                assert str(project.path) == str(tmp_path) or str(project.path) == str(
                    source_file.parent
                )
