"""Database integration checks require an explicit opt-in."""

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False,
                     help="Run PostgreSQL integration tests against the configured database")


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires a running PostgreSQL database")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="PostgreSQL integration requires --run-integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
