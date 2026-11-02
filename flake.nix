{
  description = "Fangtype development environment";

  inputs = {
    nixpkgs = {
      type = "github";
      owner = "nixos";
      repo = "nixpkgs";
      ref = "nixos-unstable";
    };
    flake-utils = {
      type = "github";
      owner = "numtide";
      repo = "flake-utils";
      ref = "main";
    };
    pre-commit-hooks = {
      type = "github";
      owner = "cachix";
      repo = "git-hooks.nix";
      ref = "master";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-nix = {
      type = "github";
      owner = "pyproject-nix";
      repo = "pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
    pre-commit-hooks,
    pyproject-nix,
  }:
    flake-utils.lib.eachDefaultSystem (
      system: let
        pkgs = import nixpkgs {
          inherit system;
          config = {allowUnfree = true;};
        };

        project = pyproject-nix.lib.project.loadPyproject {
          projectRoot = ./code/lsp;
        };

        pythonEnv = pkgs.python314.withPackages (
          ps:
            (project.renderers.withPackages {
                python = pkgs.python314;
                extras = ["dev"];
              }
              ps)
            ++ [ps.pip ps.pip-tools ps.nox]
        );

        # Pre-commit hooks configuration
        pre-commit-check = pre-commit-hooks.lib.${system}.run {
          src = ./.;
          hooks = {
            # Formatting via treefmt (consolidates: ruff, ruff-format, prettier,
            # trim-trailing-whitespace, end-of-file-fixer, check-yaml, check-toml)
            treefmt = {
              enable = true;
            };

            # Specialized hooks not covered by formatters
            check-added-large-files.enable = true;

            vscode-eslint = {
              enable = true;
              name = "VS Code ESLint";
              entry = "${pkgs.eslint}/bin/eslint --config code/vscode-extension/eslint.config.mjs";
              files = "^code/vscode-extension/src/.*\\.ts$";
              pass_filenames = true;
            };
            mypy = {
              enable = true;
              name = "mypy (code/lsp: combined src + tests + benchmark)";
              # Run from code/lsp so the config's path-anchored excludes (e.g. ^benchmark/data/)
              # resolve. A single combined `mypy .` checks src, tests and benchmark together, so the
              # test doubles are type-checked against the REAL fangtype types (FakeLanguageServer vs
              # LanguageServer, method-assign on mocks, TypedDict payload shapes) instead of the
              # ignore_missing_imports Any they collapse to when a tree is checked in isolation.
              # Cross-tree drift is now caught here, not masked. (Fixes stay real conformance changes
              # — casts, object.__setattr__, assert-narrowing — never `# type: ignore`, which
              # warn_unused_ignores would flag the moment a single tree were checked on its own.)
              entry = "bash -c 'cd code/lsp && ${pythonEnv}/bin/mypy --config-file pyproject.toml .'";
              language = "system";
              pass_filenames = false;
              files = "";
            };
            ruff-check = {
              enable = true;
              name = "ruff check";
              entry = "${pythonEnv}/bin/ruff check code/lsp/src";
              language = "system";
              pass_filenames = false;
              files = "^code/lsp/.*\\.py$";
            };
            pytest = {
              enable = true;
              name = "pytest (code/lsp, core)";
              entry = "bash -c 'cd code/lsp && PYTHONPATH=src ${pythonEnv}/bin/python -m pytest -q -k \"not benchmark\"'";
              language = "system";
              pass_filenames = false;
              always_run = true;
              stages = ["pre-push"];
            };
          };
        };

        # Build the server package independently of the VSIX bundle.
        fangtype = let
          attrs = project.renderers.buildPythonPackage {python = pkgs.python314;};
          safeAttrs = builtins.removeAttrs attrs ["optional-dependencies" "passthru"];
        in
          pkgs.python314Packages.buildPythonPackage (safeAttrs
            // {
              src = ./code/lsp;
              doCheck = false;
            });
      in {
        devShells = rec {
          default = pkgs.mkShell {
            packages = [
              pythonEnv
              pkgs.nodejs_24
              pkgs.git
              pkgs.alejandra
              pkgs.prettier
              pkgs.treefmt
              pkgs.taplo
              pkgs.ripgrep
            ];
            shellHook = ''
              ${pre-commit-check.shellHook}
              export PYTHONPATH=$PWD/code/lsp/src:$PYTHONPATH
            '';
          };
          cli = default;
        };

        packages = {
          default = fangtype;
          fangtype = fangtype;
        };

        checks = {
          pre-commit-check = pre-commit-check;
        };

        formatter = pkgs.alejandra;
      }
    );
}
