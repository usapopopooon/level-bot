#!/bin/sh
# Release phase: schema migration. Run before any worker / api starts.
# Idempotent — safe to run on every deploy.
set -e
exec alembic upgrade head
