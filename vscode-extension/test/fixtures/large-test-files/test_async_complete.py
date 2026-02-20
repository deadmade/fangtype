"""Comprehensive async/await patterns for testing Auto Type extension.

This module demonstrates Python's async/await patterns including:
- Async functions and coroutines
- Async context managers
- Async iterators and generators
- Asyncio tasks, queues, and synchronization primitives
- Concurrent execution patterns
- Error handling in async code

Expected: Correct type hints for coroutines, async iterators, and async context managers.
"""

from __future__ import annotations

import asyncio
import random
from asyncio import Queue
from contextlib import asynccontextmanager
from typing import TypeVar

T = TypeVar("T")


# =============================================================================
# BASIC ASYNC FUNCTIONS
# =============================================================================


async def fetch_data(url):
    """Simulate fetching data from a URL."""
    await asyncio.sleep(0.1)  # Simulate network delay
    data = {
        "url": url,
        "status": 200,
        "content": "Sample data",
    }  # Expected hint: data: dict
    return data


async def process_data(data):
    """Process fetched data."""
    await asyncio.sleep(0.05)  # Simulate processing time
    result = {  # Expected hint: result: dict
        "processed": True,
        "length": len(str(data)),
        "data": data,
    }
    return result


async def fetch_and_process(url):
    """Fetch and process data from URL."""
    data = await fetch_data(url)  # Expected hint: data: dict
    result = await process_data(data)  # Expected hint: result: dict
    return result


async def fetch_multiple(urls):
    """Fetch data from multiple URLs concurrently."""
    tasks = [fetch_data(url) for url in urls]  # Expected hint: tasks: list
    results = await asyncio.gather(*tasks)  # Expected hint: results: tuple
    return results


async def fetch_with_timeout(url, timeout):
    """Fetch data with timeout."""
    try:
        result = await asyncio.wait_for(
            fetch_data(url), timeout=timeout
        )  # Expected hint: result: dict
        return result
    except TimeoutError:
        error_result = {
            "url": url,
            "error": "timeout",
        }  # Expected hint: error_result: dict
        return error_result


# =============================================================================
# ASYNC CONTEXT MANAGERS
# =============================================================================


class AsyncDatabase:
    """Async database connection simulation."""

    def __init__(self, connection_string):
        self.connection_string = (
            connection_string  # Expected hint: self.connection_string: str
        )
        self.connected = False  # Expected hint: self.connected: bool
        self.queries = []  # Expected hint: self.queries: list

    async def __aenter__(self):
        """Connect to database."""
        await asyncio.sleep(0.1)  # Simulate connection time
        self.connected = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Disconnect from database."""
        await asyncio.sleep(0.05)  # Simulate disconnection
        self.connected = False
        return False

    async def execute(self, query):
        """Execute a database query."""
        if not self.connected:
            raise RuntimeError("Not connected to database")

        await asyncio.sleep(0.05)  # Simulate query execution
        self.queries.append(query)

        result = {  # Expected hint: result: dict
            "query": query,
            "rows_affected": random.randint(1, 100),
            "success": True,
        }
        return result


class AsyncFile:
    """Async file operations simulation."""

    def __init__(self, filepath, mode):
        self.filepath = filepath  # Expected hint: self.filepath: str
        self.mode = mode  # Expected hint: self.mode: str
        self.content = ""  # Expected hint: self.content: str
        self.closed = True  # Expected hint: self.closed: bool

    async def __aenter__(self):
        """Open file."""
        await asyncio.sleep(0.01)
        self.closed = False
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close file."""
        await asyncio.sleep(0.01)
        self.closed = True
        return False

    async def read(self):
        """Read file content."""
        if self.closed:
            raise ValueError("File is closed")

        await asyncio.sleep(0.05)
        return self.content

    async def write(self, data):
        """Write data to file."""
        if self.closed:
            raise ValueError("File is closed")

        await asyncio.sleep(0.05)
        self.content += data
        bytes_written = len(data)  # Expected hint: bytes_written: int
        return bytes_written


@asynccontextmanager
async def async_resource(name):
    """Generic async resource context manager."""
    resource = {"name": name, "active": False}  # Expected hint: resource: dict

    # Setup
    await asyncio.sleep(0.01)
    resource["active"] = True

    try:
        yield resource
    finally:
        # Cleanup
        await asyncio.sleep(0.01)
        resource["active"] = False


# =============================================================================
# ASYNC ITERATORS AND GENERATORS
# =============================================================================


async def async_range(n):
    """Async generator for range."""
    for i in range(n):
        await asyncio.sleep(0.01)
        yield i  # Expected: async generator


async def async_countdown(start):
    """Async countdown generator."""
    current = start  # Expected hint: current: int
    while current > 0:
        await asyncio.sleep(0.01)
        yield current
        current -= 1


async def async_fibonacci(n):
    """Generate first n Fibonacci numbers asynchronously."""
    a, b = 0, 1  # Expected hint: a: int, b: int
    for _ in range(n):
        await asyncio.sleep(0.01)
        yield a
        temp = a + b  # Expected hint: temp: int
        a = b
        b = temp


class AsyncDataStream:
    """Async iterator for streaming data."""

    def __init__(self, data_source):
        self.data_source = data_source  # Expected hint: self.data_source: list
        self.index = 0  # Expected hint: self.index: int

    def __aiter__(self):
        """Return async iterator."""
        return self

    async def __anext__(self):
        """Get next item."""
        if self.index >= len(self.data_source):
            raise StopAsyncIteration

        await asyncio.sleep(0.01)  # Simulate async operation
        item = self.data_source[self.index]  # Expected hint: item: Any
        self.index += 1
        return item


async def process_stream(stream):
    """Process items from an async stream."""
    results = []  # Expected hint: results: list
    async for item in stream:
        processed = (
            item * 2 if isinstance(item, (int, float)) else item
        )  # Expected hint: processed: int | float | Any
        results.append(processed)
    return results


# =============================================================================
# ASYNC COMPREHENSIONS
# =============================================================================


async def async_map(func, items):
    """Async map operation."""
    results = []  # Expected hint: results: list
    for item in items:
        result = await func(item)  # Expected hint: result: Any
        results.append(result)
    return results


async def gather_with_comprehension(urls):
    """Use list comprehension with async operations."""
    tasks = [fetch_data(url) for url in urls]  # Expected hint: tasks: list
    results = [
        await task for task in tasks
    ]  # Expected hint: results: list (async comprehension)
    return results


async def filter_async(predicate, items):
    """Async filter operation."""
    filtered = []  # Expected hint: filtered: list
    for item in items:
        if await predicate(item):
            filtered.append(item)
    return filtered


async def async_sum(numbers):
    """Sum numbers with async processing."""
    total = 0  # Expected hint: total: int
    async for num in AsyncDataStream(numbers):
        total += num
    return total


# =============================================================================
# ASYNCIO TASKS AND FUTURES
# =============================================================================


async def create_task_example(url):
    """Create and manage asyncio tasks."""
    task = asyncio.create_task(fetch_data(url))  # Expected hint: task: Task[dict]

    # Do other work while task runs
    await asyncio.sleep(0.01)

    # Wait for task to complete
    result = await task  # Expected hint: result: dict
    return result


async def run_concurrent_tasks(urls):
    """Run multiple tasks concurrently."""
    tasks = [
        asyncio.create_task(fetch_data(url)) for url in urls
    ]  # Expected hint: tasks: list

    completed = []  # Expected hint: completed: list
    for task in asyncio.as_completed(tasks):
        result = await task  # Expected hint: result: dict
        completed.append(result)

    return completed


async def task_with_callback(url):
    """Create task with done callback."""
    results = []  # Expected hint: results: list

    def callback(task):
        """Task completion callback."""
        result = task.result()  # Expected hint: result: dict
        results.append(result)

    task = asyncio.create_task(fetch_data(url))  # Expected hint: task: Task[dict]
    task.add_done_callback(callback)

    await task
    return results


async def cancel_task_example():
    """Demonstrate task cancellation."""

    async def long_running():
        """Long running task."""
        try:
            await asyncio.sleep(10)
            return "completed"
        except asyncio.CancelledError:
            return "cancelled"

    task = asyncio.create_task(long_running())  # Expected hint: task: Task[str]
    await asyncio.sleep(0.1)

    task.cancel()
    try:
        result = await task  # Expected hint: result: str
    except asyncio.CancelledError:
        result = "task was cancelled"  # Expected hint: result: str

    return result


# =============================================================================
# ASYNC QUEUES
# =============================================================================


async def producer(queue, items):
    """Producer that adds items to queue."""
    for item in items:
        await asyncio.sleep(0.01)
        await queue.put(item)
        produced = item  # Expected hint: produced: Any
        print(f"Produced: {produced}")


async def consumer(queue, num_items):
    """Consumer that processes items from queue."""
    results = []  # Expected hint: results: list
    for _ in range(num_items):
        item = await queue.get()  # Expected hint: item: Any
        await asyncio.sleep(0.02)
        processed = (
            item * 2 if isinstance(item, (int, float)) else item
        )  # Expected hint: processed: int | float | Any
        results.append(processed)
        queue.task_done()
    return results


async def producer_consumer_pattern(items):
    """Demonstrate producer-consumer pattern."""
    queue = Queue()  # Expected hint: queue: Queue[Any]

    # Create producer and consumer tasks
    producer_task = asyncio.create_task(
        producer(queue, items)
    )  # Expected hint: producer_task: Task[None]
    consumer_task = asyncio.create_task(
        consumer(queue, len(items))
    )  # Expected hint: consumer_task: Task[list]

    # Wait for both to complete
    await producer_task
    results = await consumer_task  # Expected hint: results: list

    return results


async def priority_queue_example():
    """Demonstrate priority queue usage."""
    pq = asyncio.PriorityQueue()  # Expected hint: pq: PriorityQueue[Any]

    # Add items with priorities
    items = [(3, "low"), (1, "high"), (2, "medium")]  # Expected hint: items: list
    for priority, value in items:
        await pq.put((priority, value))

    # Retrieve items in priority order
    results = []  # Expected hint: results: list
    while not pq.empty():
        priority, value = await pq.get()  # Expected hint: priority: int, value: str
        results.append(value)

    return results


# =============================================================================
# SYNCHRONIZATION PRIMITIVES
# =============================================================================


async def lock_example():
    """Demonstrate asyncio Lock."""
    lock = asyncio.Lock()  # Expected hint: lock: Lock
    shared_resource = {"counter": 0}  # Expected hint: shared_resource: dict

    async def increment():
        """Increment shared counter with lock."""
        async with lock:
            current = shared_resource["counter"]  # Expected hint: current: int
            await asyncio.sleep(0.01)
            shared_resource["counter"] = current + 1

    # Run multiple increments concurrently
    tasks = [
        asyncio.create_task(increment()) for _ in range(10)
    ]  # Expected hint: tasks: list
    await asyncio.gather(*tasks)

    final_count = shared_resource["counter"]  # Expected hint: final_count: int
    return final_count


async def event_example():
    """Demonstrate asyncio Event."""
    event = asyncio.Event()  # Expected hint: event: Event

    async def waiter(name):
        """Wait for event."""
        await event.wait()
        result = f"{name} received event"  # Expected hint: result: str
        return result

    async def trigger():
        """Trigger event after delay."""
        await asyncio.sleep(0.1)
        event.set()

    # Create waiters and trigger
    waiter_tasks = [
        asyncio.create_task(waiter(f"Waiter-{i}")) for i in range(3)
    ]  # Expected hint: waiter_tasks: list
    trigger_task = asyncio.create_task(
        trigger()
    )  # Expected hint: trigger_task: Task[None]

    results = await asyncio.gather(*waiter_tasks)  # Expected hint: results: tuple
    await trigger_task

    return results


async def semaphore_example():
    """Demonstrate asyncio Semaphore."""
    semaphore = asyncio.Semaphore(2)  # Expected hint: semaphore: Semaphore
    active_count = {"value": 0}  # Expected hint: active_count: dict

    async def limited_task(task_id):
        """Task that uses semaphore."""
        async with semaphore:
            active_count["value"] += 1
            max_active = active_count["value"]  # Expected hint: max_active: int
            await asyncio.sleep(0.1)
            active_count["value"] -= 1
            return max_active

    tasks = [
        asyncio.create_task(limited_task(i)) for i in range(5)
    ]  # Expected hint: tasks: list
    results = await asyncio.gather(*tasks)  # Expected hint: results: tuple

    return results


# =============================================================================
# ERROR HANDLING
# =============================================================================


async def fetch_with_retry(url, max_retries):
    """Fetch data with retry logic."""
    retries = 0  # Expected hint: retries: int

    while retries < max_retries:
        try:
            data = await fetch_data(url)  # Expected hint: data: dict
            return data
        except Exception as e:
            retries += 1
            error_msg = str(e)  # Expected hint: error_msg: str
            if retries >= max_retries:
                raise
            await asyncio.sleep(retries * 0.1)

    return None


async def handle_multiple_errors(urls):
    """Handle errors from multiple async operations."""
    results = []  # Expected hint: results: list
    errors = []  # Expected hint: errors: list

    for url in urls:
        try:
            data = await fetch_data(url)  # Expected hint: data: dict
            results.append(data)
        except Exception as e:
            error_info = {
                "url": url,
                "error": str(e),
            }  # Expected hint: error_info: dict
            errors.append(error_info)

    return results, errors


async def gather_with_errors(urls):
    """Gather results with error handling."""
    tasks = [fetch_data(url) for url in urls]  # Expected hint: tasks: list

    # Gather with return_exceptions=True
    results = await asyncio.gather(
        *tasks, return_exceptions=True
    )  # Expected hint: results: tuple

    successes = []  # Expected hint: successes: list
    failures = []  # Expected hint: failures: list

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            error_info = {
                "url": urls[i],
                "error": str(result),
            }  # Expected hint: error_info: dict
            failures.append(error_info)
        else:
            successes.append(result)

    return successes, failures


# =============================================================================
# COMPLEX ASYNC PATTERNS
# =============================================================================


async def pipeline_pattern(data):
    """Async pipeline processing."""

    async def stage1(item):
        """First processing stage."""
        await asyncio.sleep(0.01)
        return item * 2

    async def stage2(item):
        """Second processing stage."""
        await asyncio.sleep(0.01)
        return item + 10

    async def stage3(item):
        """Third processing stage."""
        await asyncio.sleep(0.01)
        return str(item)

    # Process through pipeline
    result1 = await stage1(data)  # Expected hint: result1: int | float
    result2 = await stage2(result1)  # Expected hint: result2: int | float
    result3 = await stage3(result2)  # Expected hint: result3: str

    return result3


async def fan_out_fan_in(data):
    """Fan-out/fan-in pattern."""

    async def worker(item):
        """Worker function."""
        await asyncio.sleep(0.01)
        return item**2

    # Fan out: create tasks for all items
    tasks = [
        asyncio.create_task(worker(item)) for item in data
    ]  # Expected hint: tasks: list

    # Fan in: gather all results
    results = await asyncio.gather(*tasks)  # Expected hint: results: tuple
    total = sum(results)  # Expected hint: total: int | float

    return total


async def rate_limited_requests(urls, rate_limit):
    """Make rate-limited async requests."""
    semaphore = asyncio.Semaphore(rate_limit)  # Expected hint: semaphore: Semaphore
    results = []  # Expected hint: results: list

    async def fetch_limited(url):
        """Fetch with rate limiting."""
        async with semaphore:
            data = await fetch_data(url)  # Expected hint: data: dict
            await asyncio.sleep(1.0 / rate_limit)
            return data

    tasks = [
        asyncio.create_task(fetch_limited(url)) for url in urls
    ]  # Expected hint: tasks: list
    results = await asyncio.gather(*tasks)  # Expected hint: results: tuple

    return results


# =============================================================================
# EXAMPLE USAGE
# =============================================================================


async def main():
    """Main async function demonstrating various patterns."""
    print("Starting async examples...")

    # Basic async
    data = await fetch_data("https://example.com")  # Expected hint: data: dict
    processed = await process_data(data)  # Expected hint: processed: dict

    # Multiple concurrent requests
    urls = [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
    ]  # Expected hint: urls: list
    results = await fetch_multiple(urls)  # Expected hint: results: tuple

    # Async context manager
    async with AsyncDatabase("connection_string") as db:
        query_result = await db.execute(
            "SELECT * FROM table"
        )  # Expected hint: query_result: dict

    # Async generator
    fibonacci_numbers = []  # Expected hint: fibonacci_numbers: list
    async for num in async_fibonacci(10):
        fibonacci_numbers.append(num)

    # Producer-consumer
    items = [1, 2, 3, 4, 5]  # Expected hint: items: list
    pc_results = await producer_consumer_pattern(
        items
    )  # Expected hint: pc_results: list

    # Error handling
    successes, failures = await gather_with_errors(
        urls
    )  # Expected hint: successes: list, failures: list

    summary = {  # Expected hint: summary: dict
        "basic_data": data,
        "multiple_results": len(results),
        "fibonacci_count": len(fibonacci_numbers),
        "pc_results": len(pc_results),
        "successes": len(successes),
        "failures": len(failures),
    }

    return summary


if __name__ == "__main__":
    result = asyncio.run(main())  # Expected hint: result: dict
    print(f"Async examples completed: {result}")
