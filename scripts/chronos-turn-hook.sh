#!/usr/bin/env bash
# chronosgraph-managed: turn-hook-wrapper format=1
python "$(dirname "$0")/agent_turn_hook.py" "$@"
