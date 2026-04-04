#!/usr/bin/env python3
"""
Stop hook: if any tracked Python/config files were modified this turn,
prepend a CHANGELOG.md entry under today's UTC date.
Reads the assistant_response from stdin to extract file paths mentioned.
"""
import sys, json, datetime, subprocess, os, re

event = json.load(sys.stdin)
response = event.get("assistant_response", "")
cwd = event.get("cwd", os.getcwd())

# Find files modified since last commit (staged or unstaged)
result = subprocess.run(
    ["git", "diff", "--name-only", "HEAD"],
    capture_output=True, text=True, cwd=cwd
)
changed = [f for f in result.stdout.strip().splitlines()
           if f and "CHANGELOG" not in f and not f.startswith(".kiro")]

# Also check untracked new files
result2 = subprocess.run(
    ["git", "ls-files", "--others", "--exclude-standard"],
    capture_output=True, text=True, cwd=cwd
)
new_files = [f for f in result2.stdout.strip().splitlines()
             if f and "CHANGELOG" not in f and not f.startswith(".kiro")]

all_changed = changed + new_files
if not all_changed:
    sys.exit(0)

today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
changelog_path = os.path.join(cwd, "CHANGELOG.md")

# Build bullet points
bullets = "\n".join(f"- [chore] Modified `{f}`" for f in all_changed[:10])
entry = f"\n## [{today}]\n{bullets}\n"

# Read existing changelog
try:
    with open(changelog_path, "r") as fh:
        existing = fh.read()
except FileNotFoundError:
    existing = "# Changelog\n"

# Don't duplicate today's auto-entry
if f"## [{today}]" in existing:
    sys.exit(0)

# Prepend after first line (title)
lines = existing.split("\n", 1)
new_content = lines[0] + "\n" + entry + (lines[1] if len(lines) > 1 else "")

with open(changelog_path, "w") as fh:
    fh.write(new_content)

print(f"CHANGELOG updated: {len(all_changed)} file(s) on {today}")
