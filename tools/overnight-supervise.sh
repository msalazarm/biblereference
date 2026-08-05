#!/usr/bin/env bash
# Keep the overnight run going until it finishes, whatever happens to it.
#
# The run is resumable by construction -- every answer is committed to judgement.sqlite as
# it arrives, and a restart judges only what is missing, which was verified by killing one
# with SIGKILL mid-phase and watching the next resume from exactly where it stopped. So the
# only thing standing between a 3am crash and a wasted night is something to start it
# again. This is that.
#
#   nohup tools/overnight-supervise.sh > /dev/null 2>&1 &
#
# Exits when the run exits 0. Gives up after MAX attempts so a run failing instantly does
# not spin until morning.

set -u
cd "$(dirname "$0")/.." || exit 1

AUDIT="${BIBLEREFERENCE_HOME:-$HOME/.local/share/biblereference}/audit"
LOG="$AUDIT/overnight.log"
MAX=40
mkdir -p "$AUDIT"

for attempt in $(seq 1 $MAX); do
    echo "[supervisor] attempt $attempt of $MAX at $(date '+%H:%M:%S')" | tee -a "$LOG"
    venv/bin/python tools/overnight.py "$@"
    status=$?
    if [ $status -eq 0 ]; then
        echo "[supervisor] finished cleanly after $attempt attempt(s)" | tee -a "$LOG"
        exit 0
    fi
    echo "[supervisor] exited $status; resuming in 30s" | tee -a "$LOG"
    sleep 30
done

echo "[supervisor] giving up after $MAX attempts" | tee -a "$LOG"
# Whatever was judged is still on disk; rebuild a readable report from it.
venv/bin/python tools/overnight.py --report-only
exit 1
