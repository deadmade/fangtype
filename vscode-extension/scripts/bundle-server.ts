import * as child_process from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Get all relevant paths for bundling.
 */
function getPaths() {
    const extensionDir = path.resolve(__dirname, '..');
    const targetDir = path.join(extensionDir, 'dist');

    // Create dist directory if it doesn't exist
    if (!fs.existsSync(targetDir)) {
        fs.mkdirSync(targetDir, { recursive: true });
    }

    return {
        extensionDir,
        targetDir,
        projectRoot: path.resolve(extensionDir, '..'),
    };
}

function buildWithNix() {
    const { targetDir, projectRoot } = getPaths();

    // In CI, the binary is built by PyInstaller in a previous step.
    // Return early to preserve it for VSIX packaging.
    if (process.env.GITLAB_CI) {
        console.log('Running in GitLab CI, skipping Nix build...');
        return;
    }

    // Only remove the old server binary when rebuilding locally via Nix
    const targetBinary = path.join(targetDir, 'auto-type-server');
    if (fs.existsSync(targetBinary)) {
        fs.rmSync(targetBinary, { force: true });
    }

    console.log('Building Python server with Nix...');
    try {
        // 1. Build with Nix
        // This creates a symlink 'result' in the current directory
        child_process.execSync('nix build .#auto-type', {
            cwd: projectRoot,
            stdio: 'inherit',
        });

        // 2. Resolve the result symlink to find the actual binary
        const resultLink = path.join(projectRoot, 'result');
        const realPath = fs.realpathSync(resultLink);
        const sourceBinary = path.join(realPath, 'bin', 'auto-type-server');

        // 3. Copy binary to dist directory
        console.log(`Copying server binary to ${targetDir}...`);
        fs.copyFileSync(sourceBinary, targetBinary);

        // Make executable
        fs.chmodSync(targetBinary, '755');

        console.log('Server bundle complete!');
    } catch (error) {
        console.error('Failed to build/bundle server:', error);
        process.exit(1);
    }
}

function main() {
    console.log('='.repeat(60));
    console.log('Bundling standalone auto-type server via Nix');
    console.log('='.repeat(60));

    try {
        buildWithNix();
        console.log('\nBundling complete!');
    } catch (error) {
        console.error(`\nUnexpected error: ${error}`);
        process.exit(1);
    }
}

main();
