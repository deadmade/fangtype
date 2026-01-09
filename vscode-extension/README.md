# Auto Type VSCode Extension

A VSCode extension that provides interactive Python type annotation using Language Server Protocol (LSP).

## Features

- **Ghost Text Display**: Shows inferred types as ghost text (inline hints)
- **Literal Type Inference**: Automatically infers types from simple literals
- **Type Validation**: Only shows validated types that exist in scope

## Installation

### Development Installation

1. Install dependencies:
   ```bash
   cd vscode-extension
   npm install
   ```

2. Compile the extension:
   ```bash
   npm run compile
   ```

3. Install the auto-type server:
   ```bash
   cd ../auto_type
   uv sync --all-extras
   ```

4. Open this directory in VSCode and press F5 to launch the extension in a new VSCode window

### Manual Installation

1. Compile the extension:
   ```bash
   npm run compile
   ```

2. Copy the entire `vscode-extension` directory to:
   - **Linux/Mac**: `~/.vscode/extensions/auto-type-0.1.0`
   - **Windows**: `%USERPROFILE%\.vscode\extensions\auto-type-0.1.0`

3. Restart VSCode

## Configuration

Configure the extension in VSCode settings:

```json
{
  "autoType.serverCommand": "auto-type-server",
  "autoType.serverArgs": [],
  "autoType.trace.server": "off"
}
```

### Options

- `autoType.serverCommand`: Command to start the language server (default: `auto-type-server`)
- `autoType.serverArgs`: Arguments to pass to the server
- `autoType.trace.server`: Enable LSP protocol tracing for debugging

## Usage

1. Open a Python file
2. Write untyped code with simple literals:
   ```python
   x = 42
   name = "hello"
   items = []
   ```
3. You should see ghost text showing the inferred types:
   ```python
   x: int = 42
   name: str = "hello"
   items: list = []
   ```

## Requirements

- Python 3.12 or higher
- `auto-type` package installed (from `../auto_type`)
- VSCode 1.75.0 or higher

## Known Limitations (WP1 Scope)

This is a minimal viable prototype (WP1). Current limitations:

- Only infers types from simple literals (int, str, bool, list, dict, set, tuple)
- No function parameter or return type inference yet (coming in WP2)
- No code actions to accept/insert types yet (coming in WP4)
- No complex type inference (generics, unions, etc.) yet

## Development

### Build

```bash
npm run compile
```

### Watch mode

```bash
npm run watch
```

### Testing

To test the extension:
1. Open the `vscode-extension` directory in VSCode
2. Press F5 to launch Extension Development Host
3. Open a Python file and test type inference

## License

MIT
