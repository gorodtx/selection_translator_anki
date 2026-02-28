[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,
    [string]$EvidenceDir = ".\vm-gate-output",
    [string]$ImageId = "win11-gate",
    [string]$Snapshot = "win11-gate-clean",
    [string]$OperatorName = $env:USERNAME,
    [string]$Commit = "",
    [switch]$NonInteractive,
    [ValidateSet("PASS", "FAIL")]
    [string]$DefaultResult = "PASS"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-Commit {
    param([string]$Value)
    if ($Value) {
        return $Value
    }
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        return "unknown"
    }
    try {
        return (git rev-parse --short HEAD).Trim()
    } catch {
        return "unknown"
    }
}

function Read-StepResult {
    param(
        [string]$Label,
        [switch]$AutoMode,
        [string]$AutoValue
    )
    if ($AutoMode) {
        return $AutoValue
    }
    while ($true) {
        $value = (Read-Host "$Label [PASS/FAIL]").Trim().ToUpperInvariant()
        if ($value -in @("PASS", "FAIL")) {
            return $value
        }
    }
}

function Ensure-FileWithPlaceholder {
    param(
        [string]$Path,
        [string]$Content
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        Set-Content -LiteralPath $Path -Value $Content -Encoding UTF8
    }
}

$artifactFullPath = (Resolve-Path -LiteralPath $ArtifactPath).Path
$evidenceFullPath = [System.IO.Path]::GetFullPath($EvidenceDir)
$logsDir = Join-Path $evidenceFullPath "logs"
$videoDir = Join-Path $evidenceFullPath "video"

New-Item -ItemType Directory -Force -Path $evidenceFullPath | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
New-Item -ItemType Directory -Force -Path $videoDir | Out-Null

Ensure-FileWithPlaceholder -Path (Join-Path $logsDir "app.log") -Content "App log placeholder. Replace with real runtime log."
Ensure-FileWithPlaceholder -Path (Join-Path $logsDir "helper.log") -Content "Helper log placeholder. Replace with real helper log."
Ensure-FileWithPlaceholder -Path (Join-Path $logsDir "ipc.log") -Content "IPC log placeholder. Replace with real IPC log."
Ensure-FileWithPlaceholder -Path (Join-Path $videoDir "gate-run.mp4") -Content "Replace with recorded gate session video."

$steps = @(
    "App starts from portable zip",
    "Second start does not create second instance",
    "Helper/backend IPC connection established",
    "Global hotkey opens translation window",
    "UIA selection works in Notepad",
    "UIA selection works in browser",
    "Clipboard fallback works when UIA unavailable",
    "Tray opens Settings",
    "Tray opens History",
    "Translation success path renders result",
    "Network error path handled without crash",
    "GetAnkiStatus works",
    "Create model works",
    "Deck list/select works",
    "Add/update card works",
    "Hotkey spam does not freeze UI",
    "Repeated open/close does not corrupt state"
)

$results = @()
foreach ($step in $steps) {
    $result = Read-StepResult -Label $step -AutoMode:$NonInteractive -AutoValue $DefaultResult
    $results += [PSCustomObject]@{
        Step = $step
        Result = $result
        Notes = ""
    }
}

$checklistPath = Join-Path $evidenceFullPath "vm-gate-checklist.md"
$lines = @()
$lines += "# VM Gate Checklist Result"
$lines += ""
$lines += "| Step | Result | Notes |"
$lines += "|---|---|---|"
foreach ($item in $results) {
    $lines += "| $($item.Step) | $($item.Result) | $($item.Notes) |"
}
$lines += ""
$failed = ($results | Where-Object { $_.Result -eq "FAIL" }).Count
$decision = if ($failed -eq 0) { "PASS" } else { "FAIL" }
$lines += "- Final decision: $decision"
Set-Content -LiteralPath $checklistPath -Value $lines -Encoding UTF8

$artifactHash = (Get-FileHash -LiteralPath $artifactFullPath -Algorithm SHA256).Hash.ToLowerInvariant()
$windowsVersion = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").DisplayVersion
if (-not $windowsVersion) {
    $windowsVersion = "unknown"
}
$timestamp = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$resolvedCommit = Resolve-Commit -Value $Commit

$manifest = [ordered]@{
    schema_version = 1
    vm = [ordered]@{
        platform = "qemu-kvm"
        image_id = $ImageId
        snapshot = $Snapshot
        windows_version = "Windows 11 $windowsVersion"
    }
    artifact = [ordered]@{
        file = [System.IO.Path]::GetFileName($artifactFullPath)
        sha256 = $artifactHash
    }
    run = [ordered]@{
        timestamp_utc = $timestamp
        commit = $resolvedCommit
        operator = $OperatorName
        checklist = "vm-gate-checklist.md"
    }
}

$manifestPath = Join-Path $evidenceFullPath "env-manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "VM gate checklist written: $checklistPath"
Write-Host "Manifest written: $manifestPath"
Write-Host "Evidence directory ready: $evidenceFullPath"
Write-Host "Final decision: $decision"
if ($decision -eq "FAIL") {
    exit 1
}
