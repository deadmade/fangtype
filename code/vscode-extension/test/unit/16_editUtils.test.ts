import * as assert from 'assert';
import { canApplyWholeFileReplace } from '../../src/lsp/editUtils';

/** Whole-file replace guard: null refuses, a number must match, undefined is unversioned legacy. */

suite('canApplyWholeFileReplace Unit Test Suite', () => {
    test('null version refuses a whole-file replace', () => {
        assert.strictEqual(canApplyWholeFileReplace(null, 3), false);
    });

    test('matching version is allowed', () => {
        assert.strictEqual(canApplyWholeFileReplace(3, 3), true);
    });

    test('stale version is refused', () => {
        assert.strictEqual(canApplyWholeFileReplace(3, 4), false);
    });

    test('undefined (legacy unversioned changes) has no version to guard on', () => {
        assert.strictEqual(canApplyWholeFileReplace(undefined, 3), true);
    });
});
