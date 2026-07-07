#!/usr/bin/env bash
# env_check.sh — dbt environment pre-flight check (Linux / macOS)
# Output: two-column "command ran | output". Stops at first missing prereq.

set -uo pipefail

COL=40  # width of left column

pad() { printf "%-${COL}s" "$1"; }

run_row() {
    local label="$1"; shift
    local output
    output=$("$@" 2>&1) && true  # capture; ignore exit so we print it
    printf "%s | %s\n" "$(pad "$label")" "$(echo "$output" | head -1)"
}

echo "$(pad "command ran") | output"
echo "$(printf '%0.s-' {1..80})"

# --- prereqs (stop if missing) ---
if ! command -v dbt > /dev/null 2>&1; then
    printf "%s | MISSING — install dbt before continuing\n" "$(pad "which dbt")"
    exit 1
fi
printf "%s | %s\n" "$(pad "which dbt")" "$(command -v dbt)"

if ! command -v python3 > /dev/null 2>&1; then
    printf "%s | MISSING — install python3 before continuing\n" "$(pad "which python3")"
    exit 1
fi
printf "%s | %s\n" "$(pad "which python3")" "$(command -v python3)"

# --- version + debug ---
run_row "python3 --version"   python3 --version
run_row "dbt --version"       dbt --version
run_row "dbt debug"           dbt debug
