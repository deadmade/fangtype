#!/usr/bin/env python3
"""
Bundle the auto-type Python server using Nix and PyInstaller.

This script:
1. Runs 'nix build ..#bundled-server' to build the standalone binary defined in flake.nix
2. Copies the resulting binary to bundled/tool/auto-type-server
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_paths() -> tuple[Path, Path]:
    """Get all relevant paths for bundling."""
    script_dir = Path(__file__).parent.resolve()
    extension_dir = script_dir.parent
    bundled_dir = extension_dir / "bundled"

    return extension_dir, bundled_dir


def build_with_nix(extension_dir: Path, bundled_dir: Path) -> None:
    """Build the standalone server using Nix -> PyInstaller and copy the result."""

    # 1. Prepare directories
    tool_dir = bundled_dir / "tool"

    # Clean previous build artifacts
    if tool_dir.exists():
        shutil.rmtree(tool_dir)

    tool_dir.mkdir(parents=True, exist_ok=True)

    # 2. Run Nix Build
    print("Building standalone auto-type server with Nix...")
    # Build the 'bundled-server' package from the flake
    subprocess.run(
        [
            "nix",
            "build",
            str(extension_dir.parent) + "#auto-type",
            "--out-link",
            str(extension_dir / "result"),
        ],
        check=True,
    )

    # 3. Copy binary
    binary_name = "auto-type-server"
    source_binary = extension_dir / "result" / "bin" / binary_name
    target_binary = tool_dir / binary_name

    print(f"Copying {source_binary} to {target_binary}")

    # We copy the file. This is a standalone ELF binary created by PyInstaller.
    shutil.copy2(source_binary, target_binary)

    # Verify result
    if target_binary.exists():
        print(f"Server bundled at: {target_binary}")
        # Make executable
        target_binary.chmod(0o755)
    else:
        print("Error: Server was not bundled!")
        sys.exit(1)

    # Cleanup symlink
    result_link = extension_dir / "result"
    if result_link.exists():
        result_link.unlink()


def main() -> None:
    """Bundle the auto-type server."""
    if os.environ.get("GITLAB_CI"):
        print("GitLab CI detected: Skipping Nix bundle (assuming binary pre-built).")
        return

    print("=" * 60)
    print("Bundling standalone auto-type server via Nix")
    print("=" * 60)

    extension_dir, bundled_dir = get_paths()

    try:
        build_with_nix(extension_dir, bundled_dir)
        print("\nBundling complete!")
    except subprocess.CalledProcessError as e:
        print(f"\nError during Nix build: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
