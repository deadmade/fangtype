import pytest
from injector import Injector

from auto_type.container import AutoTypeModule, reset_container


@pytest.fixture
def real_container():
    """Create a container with real dependencies."""
    return Injector([AutoTypeModule()])


@pytest.fixture(autouse=True)
def reset_global_container():
    """Reset the global container before and after each test."""
    reset_container()
    yield
    reset_container()
