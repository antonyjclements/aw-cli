#!/usr/bin/env bash
# Stop hook for augmented-workflow session logging.
# Installed by aw-init into .claude/hooks/log-session.sh.
# Fires when a Claude Code session ends and writes a session log via aw-capture session.
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
LOCK_FILE="$PROJECT_DIR/.claude/hooks/.aw-log-session-active"

# Break the recursion: when this hook spawns `claude --print` to write the log,
# that subprocess is itself a Claude Code session. When it ends its Stop hook fires
# too. The lock file causes that second invocation to exit immediately.
if [ -f "$LOCK_FILE" ]; then
  exit 0
fi

cd "$PROJECT_DIR"

# Only run when augmented-workflow is installed in this repo.
if [ ! -f ".augmented-workflow-version" ]; then
  exit 0
fi

# Parse the transcript path from the Stop hook's stdin payload.
input_file=$(mktemp)
trap 'rm -f "$input_file" "$LOCK_FILE"' EXIT
cat > "$input_file"
transcript_path=$(python3 -c "
import sys, json
try:
    d = json.load(open('$input_file'))
    print(d.get('transcript_path', ''))
except Exception:
    print('')
" 2>/dev/null || echo "")

# Acquire the lock before spawning the subprocess.
touch "$LOCK_FILE"

if [ -n "$transcript_path" ] && [ -f "$transcript_path" ]; then
  claude --print "A Claude Code session just ended in this repository. \
The session transcript is at: $transcript_path \
Read the transcript to understand what was worked on. \
Then use aw-capture session to write a brief structured session log: \
what was attempted, what worked, any corrections the user made, and dead ends hit. \
Write to docs/sessions/ with status: unprocessed in the frontmatter. \
Keep the log under 300 words."
else
  claude --print "A Claude Code session just ended in this repository. \
Use aw-capture session to write a brief session log based on recent git activity. \
Check: git log --oneline -5 and git diff --stat HEAD to understand what changed. \
Write to docs/sessions/ with status: unprocessed in the frontmatter. \
Keep the log under 300 words."
fi
