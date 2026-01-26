#!/usr/bin/env python3
"""
Bundle the auto-type Python server and its dependencies for VSCode extension packaging.

This script:
1. Copies the auto_type Python package to bundled/tool/
2. Installs all dependencies to bundled/libs/
3. Creates the launcher script

Run from the vscode-extension directory:
    python scripts/bundle_server.py
"""

import shutil
import subprocess
import sys
from pathlib import Path


def get_paths() -> tuple[Path, Path, Path, Path]:
    """Get all relevant paths for bundling."""
    # This script is in vscode-extension/scripts/
    script_dir = Path(__file__).parent.resolve()
    extension_dir = script_dir.parent
    project_root = extension_dir.parent

    bundled_dir = extension_dir / "bundled"
    auto_type_src = project_root / "auto_type" / "src" / "auto_type"

    return extension_dir, bundled_dir, auto_type_src, project_root


def clean_bundled_dir(bundled_dir: Path) -> None:
    """Remove existing bundled files (except lsp_server.py)."""
    libs_dir = bundled_dir / "libs"
    tool_auto_type = bundled_dir / "tool" / "auto_type"

    if libs_dir.exists():
        print(f"Cleaning {libs_dir}")
        shutil.rmtree(libs_dir)

    if tool_auto_type.exists():
        print(f"Cleaning {tool_auto_type}")
        shutil.rmtree(tool_auto_type)


def copy_auto_type_source(auto_type_src: Path, bundled_dir: Path) -> None:
    """Copy the auto_type package to bundled/tool/."""
    dest = bundled_dir / "tool" / "auto_type"
    print(f"Copying {auto_type_src} to {dest}")

    # Create parent directory if needed
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Copy the package, excluding __pycache__ directories
    shutil.copytree(
        auto_type_src,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def install_dependencies(extension_dir: Path, bundled_dir: Path) -> None:
    """Install Python dependencies to bundled/libs/."""
    libs_dir = bundled_dir / "libs"
    requirements_file = extension_dir / "requirements.txt"

    if not requirements_file.exists():
        print(f"ERROR: {requirements_file} not found!")
        print("Please create requirements.txt with the project dependencies.")
        sys.exit(1)

    libs_dir.mkdir(parents=True, exist_ok=True)

    print(f"Installing dependencies to {libs_dir}")

    # Try uv first (preferred in this project), fall back to pip
    try:
        subprocess.run(["uv", "--version"], check=True, capture_output=True)
        print("Using uv for installation...")
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--target",
                str(libs_dir),
                "-r",
                str(requirements_file),
            ],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("uv not found, trying pip...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(libs_dir),
                "--no-user",
                "--upgrade",
                "-r",
                str(requirements_file),
            ],
            check=True,
        )


def create_entry_point(bundled_dir: Path) -> None:
    """Create the lsp_server.py entry point."""
    tool_dir = bundled_dir / "tool"
    tool_dir.mkdir(parents=True, exist_ok=True)
    script_path = tool_dir / "lsp_server.py"

    print(f"Creating entry point at {script_path}")

    content = '''#!/usr/bin/env python3
"""
Entry point for the bundled auto-type language server.

This script sets up the Python path to use bundled dependencies
before importing and running the auto-type server.
"""

import os
import sys
from pathlib import Path


def setup_bundled_paths() -> None:
    """Add bundled libs and tool directories to sys.path."""
    # Get the directory containing this script (bundled/tool/)
    tool_dir = Path(__file__).parent.resolve()
    bundled_dir = tool_dir.parent

    # Add bundled/libs to the front of sys.path for dependencies
    libs_dir = bundled_dir / "libs"
    if libs_dir.exists():
        sys.path.insert(0, str(libs_dir))

    # Add bundled/tool to sys.path for the auto_type package
    sys.path.insert(0, str(tool_dir))


def main() -> None:
    """Start the auto-type language server."""
    setup_bundled_paths()

    # Now we can import from the bundled auto_type package
    from auto_type.server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
'''
    script_path.write_text(content, encoding="utf-8")
    # Make executable
    script_path.chmod(0o755)


def verify_bundled(bundled_dir: Path) -> bool:
    """Verify that bundled files are in place."""
    required_files = [
        bundled_dir / "tool" / "lsp_server.py",
        bundled_dir / "tool" / "auto_type" / "__init__.py",
        bundled_dir / "tool" / "auto_type" / "server.py",
        bundled_dir / "libs",
    ]

    all_present = True
    for path in required_files:
        if path.exists():
            print(f"  OK: {path.relative_to(bundled_dir.parent)}")
        else:
            print(f"  MISSING: {path.relative_to(bundled_dir.parent)}")
            all_present = False

    return all_present


def main() -> None:
    """Bundle the auto-type server for VSCode extension."""
    print("=" * 60)
    print("Bundling auto-type server for VSCode extension")
    print("=" * 60)

    extension_dir, bundled_dir, auto_type_src, project_root = get_paths()

    # Validate source exists
    if not auto_type_src.exists():
        print(f"ERROR: auto_type source not found at {auto_type_src}")
        sys.exit(1)

    # Clean existing bundled files
    print("\n[1/4] Cleaning existing bundled files...")
    clean_bundled_dir(bundled_dir)

    # Copy auto_type source
    print("\n[2/4] Copying auto_type source...")
    copy_auto_type_source(auto_type_src, bundled_dir)

    # Install dependencies
    print("\n[3/4] Installing dependencies...")
    install_dependencies(extension_dir, bundled_dir)

    # Create entry point
    print("\n[4/4] Creating entry point...")
    create_entry_point(bundled_dir)

    # Verify
    print("\n" + "=" * 60)
    print("Verification:")
    if verify_bundled(bundled_dir):
        print("\nBundling complete!")
        print(f"Bundled server location: {bundled_dir}")
    else:
        print("\nBundling incomplete - some files are missing!")
        sys.exit(1)


if __name__ == "__main__":
    main()
