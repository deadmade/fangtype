import * as assert from 'assert';
import type { ConfigurationChangeEvent } from 'vscode';
import {
    checkIfConfigurationChanged,
    checkIfInfraConfigurationChanged,
} from '../../src/common/settings';

/** Pure config-change gates: infra keys need a relaunch, domain keys push a live update. */

/** Fake event whose `affectsConfiguration` matches exactly one section. */
const fakeEvent = (changed: string): ConfigurationChangeEvent =>
    ({ affectsConfiguration: (s: string) => s === changed }) as ConfigurationChangeEvent;

suite('checkIfInfraConfigurationChanged Unit Test Suite', () => {
    test('interpreter change is an infra change', () => {
        assert.strictEqual(
            checkIfInfraConfigurationChanged(fakeEvent('fangtype.interpreter'), 'fangtype'),
            true
        );
    });

    test('installMode change is an infra change', () => {
        assert.strictEqual(
            checkIfInfraConfigurationChanged(fakeEvent('fangtype.installMode'), 'fangtype'),
            true
        );
    });

    test('domain-only change (mypyEnabled) is not an infra change', () => {
        assert.strictEqual(
            checkIfInfraConfigurationChanged(fakeEvent('fangtype.mypyEnabled'), 'fangtype'),
            false
        );
    });

    test('unrelated setting change is not an infra change', () => {
        assert.strictEqual(
            checkIfInfraConfigurationChanged(fakeEvent('editor.fontSize'), 'fangtype'),
            false
        );
    });

    test('checkIfConfigurationChanged still fires for an infra-only change (broad gate unchanged)', () => {
        assert.strictEqual(
            checkIfConfigurationChanged(fakeEvent('fangtype.installMode'), 'fangtype'),
            true
        );
    });

    test('checkIfConfigurationChanged still fires for a domain-only change (broad gate unchanged)', () => {
        assert.strictEqual(
            checkIfConfigurationChanged(fakeEvent('fangtype.mypyEnabled'), 'fangtype'),
            true
        );
    });
});
