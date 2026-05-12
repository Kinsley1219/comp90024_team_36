"""
Basic sanity tests for CI/CD pipeline.
Team 36 - COMP90024
"""

import os
import sys


def test_python_version():
    """Python version should be 3.8+"""
    assert sys.version_info >= (3, 8), "Python 3.8+ required"


def test_backend_structure():
    """Key backend directories should exist"""
    assert os.path.isdir("backend"), "backend/ directory missing"
    assert os.path.isdir("backend/fission"), "backend/fission/ directory missing"
    assert os.path.isdir("backend/fission/bluesky"), "bluesky directory missing"
    assert os.path.isdir("backend/fission/reddit"), "reddit directory missing"


def test_key_files_exist():
    """Key files should exist"""
    assert os.path.isfile("README.md"), "README.md missing"
    assert os.path.isfile(".gitignore"), ".gitignore missing"
    assert os.path.isfile("backend/fission/bluesky/bluesky_harvester.py"), \
        "bluesky_harvester.py missing"
    assert os.path.isfile("backend/fission/reddit/reddit_harvest.py"), \
        "reddit_harvest.py missing"
