#!/bin/sh
# Start the Discord bot worker. Long-running process, no public port.
set -e
exec python -m src.main
