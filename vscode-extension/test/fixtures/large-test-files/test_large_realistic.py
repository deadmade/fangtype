"""Large realistic Python module for testing Auto Type extension.

This module simulates a production-grade data processing pipeline with realistic
complexity: classes, functions, type hints, and business logic. It tests the
extension's ability to handle large files (700+ lines) with mixed annotated
and unannotated code.

Expected behavior:
- Inlay hints should appear for ~70% of variables (unannotated ones)
- Type insertion should work correctly throughout the file
- Performance should remain acceptable (< 5 seconds for initial analysis)
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Protocol

# =============================================================================
# MODULE CONSTANTS
# =============================================================================

DEFAULT_TIMEOUT = 30.0  # Expected hint: DEFAULT_TIMEOUT: float
MAX_RETRIES = 3  # Expected hint: MAX_RETRIES: int
BUFFER_SIZE = 8192  # Expected hint: BUFFER_SIZE: int
DEFAULT_ENCODING = "utf-8"  # Expected hint: DEFAULT_ENCODING: str

# Configuration dictionary
CONFIG = {  # Expected hint: CONFIG: dict
    "debug": True,
    "log_level": "INFO",
    "max_workers": 4,
    "timeout": DEFAULT_TIMEOUT,
}

# Valid status codes
VALID_STATUSES = {200, 201, 204, 304}  # Expected hint: VALID_STATUSES: set

# URL patterns
URL_PATTERN = re.compile(  # Expected hint: URL_PATTERN: Pattern[str]
    r"https?://(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"
)


# =============================================================================
# ENUMS AND TYPE DEFINITIONS
# =============================================================================


class Status(Enum):
    """Processing status enumeration."""

    PENDING = auto()
    PROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class Priority(Enum):
    """Task priority levels."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# =============================================================================
# PROTOCOLS
# =============================================================================


class Processor(Protocol):
    """Protocol for data processors."""

    def process(self, data: Any) -> dict[str, Any]:
        """Process input data and return results."""
        ...

    def validate(self, data: Any) -> bool:
        """Validate input data."""
        ...


class Serializable(Protocol):
    """Protocol for serializable objects."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        ...

    def from_dict(self, data: dict[str, Any]) -> None:
        """Load from dictionary."""
        ...


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class Task:
    """Represents a processing task."""

    id: str
    name: str
    priority: Priority = Priority.MEDIUM
    status: Status = Status.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        """Convert task to dictionary."""
        result = {  # Expected hint: result: dict
            "id": self.id,
            "name": self.name,
            "priority": self.priority.value,
            "status": self.status.name,
            "created_at": self.created_at.isoformat(),
            "data": self.data,
            "metadata": self.metadata,
        }
        return result

    def is_active(self):
        """Check if task is currently active."""
        active = self.status in (
            Status.PENDING,
            Status.PROCESSING,
        )  # Expected hint: active: bool
        return active

    def age(self):
        """Get task age in seconds."""
        delta = datetime.now() - self.created_at  # Expected hint: delta: timedelta
        age_seconds = delta.total_seconds()  # Expected hint: age_seconds: float
        return age_seconds


@dataclass
class ProcessingResult:
    """Result of data processing operation."""

    success: bool
    task_id: str
    output: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def has_errors(self):
        """Check if result has errors."""
        return len(self.errors) > 0  # Expected hint: return type: bool

    def add_error(self, message):
        """Add an error message."""
        formatted = (
            f"[{datetime.now().isoformat()}] {message}"  # Expected hint: formatted: str
        )
        self.errors.append(formatted)

    def summary(self):
        """Get result summary."""
        parts = [  # Expected hint: parts: list
            f"Task {self.task_id}",
            f"Success: {self.success}",
            f"Duration: {self.duration_ms}ms",
        ]
        if self.errors:
            error_count = len(self.errors)  # Expected hint: error_count: int
            parts.append(f"Errors: {error_count}")
        summary_text = " | ".join(parts)  # Expected hint: summary_text: str
        return summary_text


# =============================================================================
# ABSTRACT BASE CLASSES
# =============================================================================


class BaseHandler(ABC):
    """Abstract base class for data handlers."""

    def __init__(self, name):
        self.name = name  # Expected hint: self.name: str (from param)
        self.stats = {"processed": 0, "errors": 0}  # Expected hint: self.stats: dict

    @abstractmethod
    def handle(self, data: Any) -> ProcessingResult:
        """Handle the data processing."""
        ...

    def increment_stats(self, key):
        """Increment a stats counter."""
        if key in self.stats:
            current = self.stats[key]  # Expected hint: current: int
            self.stats[key] = current + 1

    def get_stats(self):
        """Get handler statistics."""
        total = sum(self.stats.values())  # Expected hint: total: int
        return {"name": self.name, "total": total, "details": self.stats}


# =============================================================================
# CONCRETE IMPLEMENTATIONS
# =============================================================================


class JSONHandler(BaseHandler):
    """Handler for JSON data processing."""

    def __init__(self, name="json_handler"):
        super().__init__(name)
        self.encoding = "utf-8"  # Expected hint: self.encoding: str
        self.strict = True  # Expected hint: self.strict: bool

    def handle(self, data):
        """Process JSON data."""
        start_time = datetime.now()  # Expected hint: start_time: datetime
        result = ProcessingResult(success=False, task_id="")

        try:
            if isinstance(data, str):
                parsed = json.loads(
                    data
                )  # Expected hint: parsed: dict | list | str | int | float | bool | None
            else:
                parsed = data

            # Validate parsed data
            if not self._validate_structure(parsed):
                result.add_error("Invalid data structure")
                return result

            # Process the data
            processed = self._process_json(parsed)  # Expected hint: processed: dict
            result.success = True
            result.output = processed
            self.increment_stats("processed")

        except json.JSONDecodeError as e:
            error_msg = f"JSON decode error: {e}"  # Expected hint: error_msg: str
            result.add_error(error_msg)
            self.increment_stats("errors")
        except Exception as e:
            result.add_error(f"Unexpected error: {e}")
            self.increment_stats("errors")
        finally:
            end_time = datetime.now()  # Expected hint: end_time: datetime
            duration = (
                end_time - start_time
            ).total_seconds() * 1000  # Expected hint: duration: float
            result.duration_ms = duration

        return result

    def _validate_structure(self, data):
        """Validate JSON structure."""
        if not isinstance(data, (dict, list)):
            return False

        if isinstance(data, dict):
            required_keys = {"type", "data"}  # Expected hint: required_keys: set
            has_keys = required_keys.issubset(
                data.keys()
            )  # Expected hint: has_keys: bool
            return has_keys

        return True

    def _process_json(self, data):
        """Process validated JSON data."""
        output = {}  # Expected hint: output: dict

        if isinstance(data, dict):
            for key, value in data.items():
                processed_key = key.lower().strip()  # Expected hint: processed_key: str
                output[processed_key] = value
        elif isinstance(data, list):
            items = [
                self._process_item(item) for item in data
            ]  # Expected hint: items: list
            output["items"] = items
            output["count"] = len(items)  # Expected hint: count assigned to output: int

        return output

    def _process_item(self, item):
        """Process individual item."""
        if isinstance(item, dict):
            return {k.lower(): v for k, v in item.items()}
        return item


class TextHandler(BaseHandler):
    """Handler for text data processing."""

    def __init__(self, name="text_handler", max_length=10000):
        super().__init__(name)
        self.max_length = max_length  # Expected hint: self.max_length: int
        self.patterns = []  # Expected hint: self.patterns: list

    def handle(self, data):
        """Process text data."""
        result = ProcessingResult(success=False, task_id="")

        if not isinstance(data, str):
            result.add_error("Data must be a string")
            return result

        # Clean and validate text
        cleaned = self._clean_text(data)  # Expected hint: cleaned: str
        if len(cleaned) > self.max_length:
            result.add_warning(f"Text truncated to {self.max_length} characters")
            cleaned = cleaned[: self.max_length]

        # Extract information
        words = cleaned.split()  # Expected hint: words: list
        word_count = len(words)  # Expected hint: word_count: int
        char_count = len(cleaned)  # Expected hint: char_count: int

        # Find patterns
        matches = self._find_patterns(cleaned)  # Expected hint: matches: list

        result.success = True
        result.output = {
            "text": cleaned,
            "word_count": word_count,
            "char_count": char_count,
            "matches": matches,
        }
        self.increment_stats("processed")

        return result

    def _clean_text(self, text):
        """Clean and normalize text."""
        # Remove extra whitespace
        cleaned = " ".join(text.split())  # Expected hint: cleaned: str

        # Remove special characters
        cleaned = re.sub(r"[^\w\s.,!?-]", "", cleaned)

        return cleaned

    def _find_patterns(self, text):
        """Find pattern matches in text."""
        results = []  # Expected hint: results: list

        for pattern in self.patterns:
            matches = pattern.findall(text)  # Expected hint: matches: list
            for match in matches:
                match_info = {
                    "pattern": pattern.pattern,
                    "value": match,
                }  # Expected hint: match_info: dict
                results.append(match_info)

        return results

    def add_pattern(self, pattern_str):
        """Add a regex pattern to search for."""
        compiled = re.compile(pattern_str)  # Expected hint: compiled: Pattern[str]
        self.patterns.append(compiled)


# =============================================================================
# PROCESSING PIPELINE
# =============================================================================


class Pipeline:
    """Data processing pipeline."""

    def __init__(self, name):
        self.name = name  # Expected hint: self.name: str
        self.handlers = []  # Expected hint: self.handlers: list
        self.tasks = {}  # Expected hint: self.tasks: dict
        self.results = {}  # Expected hint: self.results: dict
        self.logger = logging.getLogger(
            f"pipeline.{name}"
        )  # Expected hint: self.logger: Logger

    def add_handler(self, handler):
        """Add a handler to the pipeline."""
        if not isinstance(handler, BaseHandler):
            raise TypeError("Handler must be a BaseHandler instance")

        self.handlers.append(handler)
        count = len(self.handlers)  # Expected hint: count: int
        self.logger.info(f"Added handler: {handler.name} (total: {count})")

    def add_task(self, task):
        """Add a task to the pipeline."""
        if not isinstance(task, Task):
            raise TypeError("Task must be a Task instance")

        self.tasks[task.id] = task
        task.status = Status.PENDING
        self.logger.info(f"Added task: {task.id}")

    def process_task(self, task_id):
        """Process a single task."""
        if task_id not in self.tasks:
            error = f"Task {task_id} not found"  # Expected hint: error: str
            self.logger.error(error)
            return None

        task = self.tasks[task_id]  # Expected hint: task: Task
        task.status = Status.PROCESSING

        # Select appropriate handler
        handler = self._select_handler(
            task
        )  # Expected hint: handler: BaseHandler | None
        if not handler:
            task.status = Status.FAILED
            return None

        # Process with handler
        result = handler.handle(task.data)  # Expected hint: result: ProcessingResult
        result.task_id = task_id

        # Update task status
        if result.success:
            task.status = Status.COMPLETED
        else:
            task.status = Status.FAILED

        # Store result
        self.results[task_id] = result
        return result

    def _select_handler(self, task):
        """Select appropriate handler for task."""
        task_type = task.metadata.get(
            "type", "unknown"
        )  # Expected hint: task_type: Any (dict.get)

        for handler in self.handlers:
            handler_name = handler.name.lower()  # Expected hint: handler_name: str
            if task_type in handler_name:
                return handler

        # Return first handler as fallback
        if self.handlers:
            return self.handlers[0]

        return None

    def process_all(self):
        """Process all pending tasks."""
        pending_tasks = [  # Expected hint: pending_tasks: list
            task_id
            for task_id, task in self.tasks.items()
            if task.status == Status.PENDING
        ]

        results = []  # Expected hint: results: list
        for task_id in pending_tasks:
            result = self.process_task(
                task_id
            )  # Expected hint: result: ProcessingResult | None
            if result:
                results.append(result)

        success_count = sum(
            1 for r in results if r.success
        )  # Expected hint: success_count: int
        total = len(results)  # Expected hint: total: int

        self.logger.info(f"Processed {total} tasks, {success_count} successful")
        return results

    def get_summary(self):
        """Get pipeline processing summary."""
        total_tasks = len(self.tasks)  # Expected hint: total_tasks: int
        completed = sum(
            1 for t in self.tasks.values() if t.status == Status.COMPLETED
        )  # Expected hint: completed: int
        failed = sum(
            1 for t in self.tasks.values() if t.status == Status.FAILED
        )  # Expected hint: failed: int
        pending = sum(
            1 for t in self.tasks.values() if t.status == Status.PENDING
        )  # Expected hint: pending: int

        summary = {  # Expected hint: summary: dict
            "pipeline": self.name,
            "total_tasks": total_tasks,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "handlers": len(self.handlers),
        }

        return summary


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def create_task(task_id, name, data, priority_value=2):
    """Create a new task instance."""
    priority = Priority(priority_value)  # Expected hint: priority: Priority
    task = Task(
        id=task_id, name=name, priority=priority, data=data
    )  # Expected hint: task: Task
    return task


def load_tasks_from_file(filepath):
    """Load tasks from a JSON file."""
    path = Path(filepath)  # Expected hint: path: Path

    if not path.exists():
        return []

    with path.open("r") as f:
        data = json.load(
            f
        )  # Expected hint: data: dict | list | str | int | float | bool | None

    tasks = []  # Expected hint: tasks: list
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                task_id = item.get("id", "")  # Expected hint: task_id: Any
                name = item.get("name", "")  # Expected hint: name: Any
                task_data = item.get("data", {})  # Expected hint: task_data: Any
                priority = item.get("priority", 2)  # Expected hint: priority: Any

                task = create_task(
                    task_id, name, task_data, priority
                )  # Expected hint: task: Task
                tasks.append(task)

    return tasks


def save_results_to_file(results, filepath):
    """Save processing results to JSON file."""
    path = Path(filepath)  # Expected hint: path: Path
    path.parent.mkdir(parents=True, exist_ok=True)

    data = []  # Expected hint: data: list
    for result in results:
        if isinstance(result, ProcessingResult):
            result_dict = {  # Expected hint: result_dict: dict
                "task_id": result.task_id,
                "success": result.success,
                "output": result.output,
                "errors": result.errors,
                "warnings": result.warnings,
                "duration_ms": result.duration_ms,
                "timestamp": result.timestamp.isoformat(),
            }
            data.append(result_dict)

    with path.open("w") as f:
        json.dump(data, f, indent=2)

    count = len(data)  # Expected hint: count: int
    return count


def calculate_statistics(results):
    """Calculate statistics from processing results."""
    if not results:
        return {}

    total = len(results)  # Expected hint: total: int
    successful = sum(1 for r in results if r.success)  # Expected hint: successful: int
    failed = total - successful  # Expected hint: failed: int

    durations = [r.duration_ms for r in results]  # Expected hint: durations: list
    avg_duration = (
        sum(durations) / len(durations) if durations else 0.0
    )  # Expected hint: avg_duration: float
    min_duration = (
        min(durations) if durations else 0.0
    )  # Expected hint: min_duration: float
    max_duration = (
        max(durations) if durations else 0.0
    )  # Expected hint: max_duration: float

    stats = {  # Expected hint: stats: dict
        "total": total,
        "successful": successful,
        "failed": failed,
        "success_rate": successful / total if total > 0 else 0.0,
        "avg_duration_ms": avg_duration,
        "min_duration_ms": min_duration,
        "max_duration_ms": max_duration,
    }

    return stats


def format_duration(milliseconds):
    """Format duration in human-readable format."""
    if milliseconds < 1000:
        return f"{milliseconds:.2f}ms"

    seconds = milliseconds / 1000  # Expected hint: seconds: float
    if seconds < 60:
        return f"{seconds:.2f}s"

    minutes = seconds / 60  # Expected hint: minutes: float
    return f"{minutes:.2f}m"


def validate_url(url):
    """Validate a URL string."""
    if not isinstance(url, str):
        return False

    match = URL_PATTERN.match(url)  # Expected hint: match: Match[str] | None
    is_valid = match is not None  # Expected hint: is_valid: bool
    return is_valid


def extract_urls_from_text(text):
    """Extract all URLs from text."""
    matches = URL_PATTERN.findall(text)  # Expected hint: matches: list
    unique_urls = list(set(matches))  # Expected hint: unique_urls: list
    sorted_urls = sorted(unique_urls)  # Expected hint: sorted_urls: list
    return sorted_urls


def merge_dictionaries(dict1, dict2):
    """Merge two dictionaries, with dict2 taking precedence."""
    result = dict1.copy()  # Expected hint: result: dict
    result.update(dict2)
    return result


def filter_tasks_by_status(tasks, status):
    """Filter tasks by status."""
    filtered = [
        task for task in tasks if task.status == status
    ]  # Expected hint: filtered: list
    count = len(filtered)  # Expected hint: count: int
    return filtered, count


def group_tasks_by_priority(tasks):
    """Group tasks by priority level."""
    groups = {}  # Expected hint: groups: dict

    for task in tasks:
        priority_name = task.priority.name  # Expected hint: priority_name: str
        if priority_name not in groups:
            groups[priority_name] = []
        groups[priority_name].append(task)

    return groups


# =============================================================================
# MAIN EXECUTION EXAMPLE
# =============================================================================


def main():
    """Main execution function demonstrating the pipeline."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger = logging.getLogger("main")  # Expected hint: logger: Logger
    logger.info("Starting data processing pipeline")

    # Create pipeline
    pipeline = Pipeline("main_pipeline")  # Expected hint: pipeline: Pipeline

    # Add handlers
    json_handler = JSONHandler()  # Expected hint: json_handler: JSONHandler
    text_handler = TextHandler(
        max_length=5000
    )  # Expected hint: text_handler: TextHandler

    pipeline.add_handler(json_handler)
    pipeline.add_handler(text_handler)

    # Create sample tasks
    sample_data = [  # Expected hint: sample_data: list
        {
            "id": "task1",
            "name": "Process JSON",
            "data": {"type": "json", "data": {"key": "value"}},
            "priority": 3,
        },
        {
            "id": "task2",
            "name": "Process Text",
            "data": "Sample text for processing",
            "priority": 2,
        },
        {
            "id": "task3",
            "name": "Analyze Data",
            "data": {"type": "analysis", "data": [1, 2, 3]},
            "priority": 1,
        },
    ]

    for item in sample_data:
        task = create_task(
            item["id"], item["name"], item["data"], item["priority"]
        )  # Expected hint: task: Task
        pipeline.add_task(task)

    # Process all tasks
    results = pipeline.process_all()  # Expected hint: results: list

    # Calculate statistics
    stats = calculate_statistics(results)  # Expected hint: stats: dict
    logger.info(f"Processing statistics: {stats}")

    # Get pipeline summary
    summary = pipeline.get_summary()  # Expected hint: summary: dict
    logger.info(f"Pipeline summary: {summary}")

    return results


if __name__ == "__main__":
    results = main()  # Expected hint: results: list
    print(f"Processed {len(results)} tasks")
