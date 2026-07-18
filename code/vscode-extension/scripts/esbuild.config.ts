import type { BuildOptions } from 'esbuild';

const config: BuildOptions = {
    entryPoints: ['./src/extension.ts'],
    bundle: true,
    minify: true,
    platform: 'node',
    target: 'node24',
    outdir: './dist',
    outbase: './src',
    outExtension: {
        '.js': '.cjs',
    },
    format: 'cjs',
    external: ['vscode'],
    loader: {
        '.ts': 'ts',
        '.js': 'js',
    },
    logLevel: 'info',
};

export default config;
