import * as assert from 'assert';
import { retryOperation, isRetryableError, type RetryableError } from '../../src/retryUtils';

/**
 * Test suite for retry logic functionality
 */
suite('Retry Logic', function () {
    this.timeout(45000);

    suite('Error Classification', () => {
        test('should identify network errors as retryable', () => {
            // Test various network error codes
            const networkErrors = [
                { code: 'ECONNREFUSED', message: 'Connection refused' },
                { code: 'ETIMEDOUT', message: 'Operation timed out' },
                { code: 'ENOTFOUND', message: 'DNS lookup failed' },
                { code: 'ECONNRESET', message: 'Connection reset' },
                { code: 'EPIPE', message: 'Broken pipe' },
                { code: 'EHOSTUNREACH', message: 'Host unreachable' },
            ];

            for (const error of networkErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(result, true, `Error ${error.code} should be retryable`);
            }
        });

        test('should identify timeout errors as retryable', () => {
            const timeoutErrors = [
                { message: 'Request timeout' },
                { message: 'Operation timed out' },
                { message: 'Connection time out' },
                { statusCode: 408 },
            ];

            for (const error of timeoutErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    true,
                    `Timeout error should be retryable: ${JSON.stringify(error)}`
                );
            }
        });

        test('should identify server errors (5xx) as retryable', () => {
            const serverErrors = [{ statusCode: 500 }, { statusCode: 503 }, { statusCode: 504 }];

            for (const error of serverErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    true,
                    `Server error ${error.statusCode} should be retryable`
                );
            }
        });

        test('should identify file lock errors as retryable', () => {
            const lockErrors = [
                { code: 'EBUSY', message: 'Resource busy' },
                { message: 'File is locked' },
                { message: 'Resource temporarily unavailable' },
            ];

            for (const error of lockErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    true,
                    `Lock error should be retryable: ${JSON.stringify(error)}`
                );
            }
        });

        test('should identify syntax errors as non-retryable', () => {
            const syntaxErrors = [
                { message: 'Syntax error at line 5' },
                { message: 'Parse error: unexpected token' },
                new SyntaxError('Invalid syntax'),
            ];

            for (const error of syntaxErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    false,
                    `Syntax error should NOT be retryable: ${JSON.stringify(error)}`
                );
            }
        });

        test('should identify not-found errors as non-retryable', () => {
            const notFoundErrors = [
                { code: 'ENOENT', message: 'File not found' },
                { statusCode: 404, message: 'Not found' },
                { message: 'File does not exist' },
                { message: 'No such file or directory' },
            ];

            for (const error of notFoundErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    false,
                    `Not-found error should NOT be retryable: ${JSON.stringify(error)}`
                );
            }
        });

        test('should identify permission errors as non-retryable', () => {
            const permissionErrors = [
                { code: 'EACCES', message: 'Permission denied' },
                { code: 'EPERM', message: 'Operation not permitted' },
                { statusCode: 403, message: 'Forbidden' },
                { message: 'Access denied' },
            ];

            for (const error of permissionErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    false,
                    `Permission error should NOT be retryable: ${JSON.stringify(error)}`
                );
            }
        });

        test('should identify user cancellation as non-retryable', () => {
            const cancellationErrors = [
                { name: 'CancelledError', message: 'Operation cancelled' },
                { message: 'User cancelled the operation' },
                { message: 'Operation was canceled' },
            ];

            for (const error of cancellationErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    false,
                    `Cancellation error should NOT be retryable: ${JSON.stringify(error)}`
                );
            }
        });

        test('should identify client errors (4xx) as non-retryable', () => {
            const clientErrors = [
                { statusCode: 400 }, // Bad request
                { statusCode: 401 }, // Unauthorized
                { statusCode: 404 }, // Not found
            ];

            for (const error of clientErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    false,
                    `Client error ${error.statusCode} should NOT be retryable`
                );
            }
        });

        test('should treat generic errors as retryable by default', () => {
            const genericErrors = [
                { message: 'Something went wrong' },
                new Error('Unknown error'),
                { message: 'Unexpected error occurred' },
            ];

            for (const error of genericErrors) {
                const result = isRetryableError(error);
                assert.strictEqual(
                    result,
                    true,
                    `Generic error should be retryable (conservative): ${JSON.stringify(error)}`
                );
            }
        });
    });

    suite('Retry Operation', () => {
        test('should succeed on first attempt without retries', async () => {
            let attempts = 0;
            const operation = async () => {
                attempts++;
                return 'success';
            };

            const result = await retryOperation(operation, { maxRetries: 3 });

            assert.strictEqual(result, 'success');
            assert.strictEqual(attempts, 1, 'Should only attempt once');
        });

        test('should succeed after 1 retry', async () => {
            let attempts = 0;
            const operation = async () => {
                attempts++;
                if (attempts === 1) {
                    throw { code: 'ETIMEDOUT', message: 'Timeout' };
                }
                return 'success';
            };

            const result = await retryOperation(operation, {
                maxRetries: 3,
                initialDelay: 10,
            });

            assert.strictEqual(result, 'success');
            assert.strictEqual(attempts, 2, 'Should attempt twice');
        });

        test('should succeed after 2 retries', async () => {
            let attempts = 0;
            const operation = async () => {
                attempts++;
                if (attempts <= 2) {
                    throw { code: 'ECONNREFUSED', message: 'Connection refused' };
                }
                return 'success';
            };

            const result = await retryOperation(operation, {
                maxRetries: 3,
                initialDelay: 10,
            });

            assert.strictEqual(result, 'success');
            assert.strictEqual(attempts, 3, 'Should attempt three times');
        });

        test('should fail after all retries exhausted', async () => {
            let attempts = 0;
            const operation = async () => {
                attempts++;
                throw { code: 'ETIMEDOUT', message: 'Persistent timeout' };
            };

            await assert.rejects(
                async () => {
                    await retryOperation(operation, {
                        maxRetries: 3,
                        initialDelay: 10,
                    });
                },
                (error: RetryableError) => {
                    assert.strictEqual(error.code, 'ETIMEDOUT');
                    return true;
                }
            );

            assert.strictEqual(attempts, 3, 'Should attempt exactly 3 times');
        });

        test('should not retry non-retryable errors', async () => {
            let attempts = 0;
            const operation = async () => {
                attempts++;
                throw { message: 'Syntax error: unexpected token' };
            };

            await assert.rejects(
                async () => {
                    await retryOperation(operation, {
                        maxRetries: 3,
                        initialDelay: 10,
                    });
                },
                (error: RetryableError) => {
                    assert.ok(error.message?.includes('Syntax error'));
                    return true;
                }
            );

            assert.strictEqual(attempts, 1, 'Should only attempt once for syntax error');
        });

        test('should use exponential backoff', async () => {
            const delays: number[] = [];
            let lastTime = Date.now();
            let attempts = 0;

            const operation = async () => {
                if (attempts > 0) {
                    const currentTime = Date.now();
                    delays.push(currentTime - lastTime);
                    lastTime = currentTime;
                }
                attempts++;

                if (attempts < 3) {
                    throw { code: 'ETIMEDOUT', message: 'Timeout' };
                }
                return 'success';
            };

            await retryOperation(operation, {
                maxRetries: 3,
                initialDelay: 50,
                backoffMultiplier: 2,
            });

            // Check that delays roughly doubled (with some tolerance for timing)
            assert.strictEqual(delays.length, 2, 'Should have 2 delays');
            const firstDelay = delays[0];
            const secondDelay = delays[1];
            assert.ok(
                firstDelay !== undefined && firstDelay >= 45,
                `First delay should be ~50ms, got ${firstDelay}`
            );
            assert.ok(
                secondDelay !== undefined && secondDelay >= 90,
                `Second delay should be ~100ms (2x), got ${secondDelay}`
            );
        });

        test('should respect maxDelay cap', async () => {
            const delays: number[] = [];
            let lastTime = Date.now();
            let attempts = 0;

            const operation = async () => {
                if (attempts > 0) {
                    const currentTime = Date.now();
                    delays.push(currentTime - lastTime);
                    lastTime = currentTime;
                }
                attempts++;

                if (attempts < 3) {
                    throw { code: 'ETIMEDOUT', message: 'Timeout' };
                }
                return 'success';
            };

            await retryOperation(operation, {
                maxRetries: 3,
                initialDelay: 100,
                maxDelay: 150,
                backoffMultiplier: 3,
            });

            // Second delay should be capped at maxDelay
            const secondDelay = delays[1];
            assert.ok(
                secondDelay !== undefined && secondDelay <= 170,
                `Second delay should be capped at ~150ms, got ${secondDelay}`
            );
        });

        test('should call onRetry callback', async () => {
            const retryAttempts: number[] = [];
            const retryErrors: RetryableError[] = [];
            let attempts = 0;

            const operation = async () => {
                attempts++;
                if (attempts < 3) {
                    throw { code: 'ETIMEDOUT', message: `Timeout ${attempts}` };
                }
                return 'success';
            };

            await retryOperation(operation, {
                maxRetries: 3,
                initialDelay: 10,
                onRetry: (attempt, error) => {
                    retryAttempts.push(attempt);
                    retryErrors.push(error);
                },
            });

            assert.strictEqual(retryAttempts.length, 2, 'Should have 2 retry callbacks');
            assert.strictEqual(retryAttempts[0], 0, 'First retry should be attempt 0');
            assert.strictEqual(retryAttempts[1], 1, 'Second retry should be attempt 1');
            assert.ok(
                retryErrors[0]?.message?.includes('Timeout'),
                'Should pass error to callback'
            );
        });

        test('should use custom shouldRetry function', async () => {
            let attempts = 0;
            const operation = async () => {
                attempts++;
                throw { customError: true, message: 'Custom error' };
            };

            // Custom retry logic: only retry if customError is true
            const shouldRetry = (error: RetryableError) => error.customError === true;

            await assert.rejects(
                async () => {
                    await retryOperation(operation, {
                        maxRetries: 3,
                        initialDelay: 10,
                        shouldRetry,
                    });
                },
                (error: RetryableError) => {
                    assert.ok(error.customError);
                    return true;
                }
            );

            // Should retry because customError is true
            assert.strictEqual(attempts, 3, 'Should retry with custom shouldRetry');
        });
    });

    suite('Integration with Extension', () => {
        test('should handle extension operations with retry', async () => {
            // This is a basic integration test to ensure retry utilities work in VSCode context
            // We'll test that the retry mechanism doesn't break normal VSCode operations

            let attempts = 0;
            const mockVSCodeOperation = async () => {
                attempts++;
                if (attempts === 1) {
                    throw { message: 'timeout', code: 'ETIMEDOUT' };
                }
                return { success: true };
            };

            const result = await retryOperation(mockVSCodeOperation, {
                maxRetries: 3,
                initialDelay: 10,
            });

            assert.ok(result.success);
            assert.strictEqual(attempts, 2, 'Should succeed after one retry');
        });

        test('should handle multiple concurrent retry operations', async () => {
            const operations = Array.from({ length: 5 }, (_, i) => {
                let attempts = 0;
                return retryOperation(
                    async () => {
                        attempts++;
                        if (attempts === 1) {
                            throw { code: 'ETIMEDOUT', message: `Timeout ${i}` };
                        }
                        return `result-${i}`;
                    },
                    { maxRetries: 3, initialDelay: 10 }
                );
            });

            const results = await Promise.all(operations);

            assert.strictEqual(results.length, 5);
            results.forEach((result, i) => {
                assert.strictEqual(result, `result-${i}`);
            });
        });
    });

    suite('Performance', () => {
        test('should not add significant overhead on success path', async () => {
            const iterations = 100;
            const start = Date.now();

            for (let i = 0; i < iterations; i++) {
                await retryOperation(async () => 'success', {
                    maxRetries: 3,
                    initialDelay: 10,
                });
            }

            const duration = Date.now() - start;

            // Should complete quickly without retries (< 500ms for 100 iterations)
            assert.ok(
                duration < 500,
                `100 successful operations took ${duration}ms, should be < 500ms`
            );
        });

        test('should handle rapid successive operations', async () => {
            let counter = 0;
            const operations: Promise<number>[] = [];

            // Fire off 10 operations rapidly
            for (let i = 0; i < 10; i++) {
                operations.push(
                    retryOperation(
                        async () => {
                            return counter++;
                        },
                        { maxRetries: 3 }
                    )
                );
            }

            const results = await Promise.all(operations);

            assert.strictEqual(results.length, 10);
            assert.strictEqual(counter, 10);
        });
    });
});
