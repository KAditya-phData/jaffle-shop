# env_check.ps1 — dbt environment pre-flight check (Windows PowerShell)
# Output: two-column "command ran | output". Stops at first missing prereq.

$COL = 40

function Pad($s) { $s.PadRight($COL) }

function Write-Row($label, $output) {
    "{0} | {1}" -f (Pad $label), ($output -split "`n")[0]
}

Write-Host ("{0} | output" -f (Pad "command ran"))
Write-Host ("-" * 80)

# --- prereqs (stop if missing) ---
$dbtPath = (Get-Command dbt -ErrorAction SilentlyContinue)?.Source
if (-not $dbtPath) {
    Write-Host ("{0} | MISSING — install dbt before continuing" -f (Pad "Get-Command dbt"))
    exit 1
}
Write-Host ("{0} | {1}" -f (Pad "Get-Command dbt"), $dbtPath)

$pyPath = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $pyPath) {
    Write-Host ("{0} | MISSING — install Python before continuing" -f (Pad "Get-Command python"))
    exit 1
}
Write-Host ("{0} | {1}" -f (Pad "Get-Command python"), $pyPath)

# --- version + debug ---
$pyVer = (python --version 2>&1) | Select-Object -First 1
Write-Host (Write-Row "python --version" $pyVer)

$dbtVer = (dbt --version 2>&1) | Select-Object -First 1
Write-Host (Write-Row "dbt --version" $dbtVer)

$dbtDebug = (dbt debug 2>&1) | Select-Object -First 1
Write-Host (Write-Row "dbt debug" $dbtDebug)
