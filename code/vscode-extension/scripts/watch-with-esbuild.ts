import esbuild, { type Plugin } from 'esbuild';
import config from './esbuild.config';

const watchPlugin: Plugin = {
    name: 'watch-plugin',
    setup(build) {
        build.onStart(() => console.log('[watch] build started'));
        build.onEnd(() => console.log('[watch] build finished'));
    },
};

config.plugins = [...(config.plugins ?? []), watchPlugin];

(async () => {
    try {
        const context = await esbuild.context(config);
        await context.watch();
    } catch (e) {
        process.exit(1);
    }
})();
