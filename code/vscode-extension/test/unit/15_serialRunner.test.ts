import * as assert from 'assert';
import { createSerialRunner } from '../../src/common/server';

/** Pure createSerialRunner: overlapping calls serialize instead of interleaving (M10). */

suite('createSerialRunner Unit Test Suite', () => {
    test('second call sees the state the first call produced (no interleaving)', async () => {
        let client: string | undefined;
        const seenAtStart: (string | undefined)[] = [];
        const run = createSerialRunner(async () => {
            seenAtStart.push(client);
            await new Promise(resolve => setTimeout(resolve, 10));
            client = client === undefined ? 'client-1' : 'client-2';
        });

        const p1 = run();
        const p2 = run();
        await Promise.all([p1, p2]);

        assert.deepStrictEqual(seenAtStart, [undefined, 'client-1']);
        assert.strictEqual(client, 'client-2');
    });

    test('a rejected call does not wedge the chain for later calls', async () => {
        let calls = 0;
        const run = createSerialRunner(async () => {
            calls += 1;
            if (calls === 1) {
                throw new Error('boom');
            }
        });

        await assert.rejects(run(), /boom/);
        await assert.doesNotReject(run());
        assert.strictEqual(calls, 2);
    });
});
