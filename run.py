#!/usr/bin/env python3
"""Entry point to run the Remote Works Server directly."""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import run

if __name__ == "__main__":
    run()
