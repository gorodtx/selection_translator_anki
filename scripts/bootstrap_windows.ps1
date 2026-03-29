[CmdletBinding()]
param(
    [string]$RepoRoot = (Join-Path $PSScriptRoot ".."),
    [string]$PythonVersion = "3.13",
    [switch]$SetupVenv,
    [switch]$VerifyOnly,
    [switch]$CreateSkillsJunction,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[windows-bootstrap] $Message"
}

function Require-WindowsHost {
    if ($env:OS -ne "Windows_NT") {
        throw "bootstrap_windows.ps1 supports Windows hosts only."
    }
}

function Get-CommandVersionText {
    param(
        [string]$CommandName,
        [string[]]$Arguments
    )

    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        return $null
    }

    try {
        $output = & $command.Source @Arguments 2>&1
    } catch {
        return "$CommandName is installed but version lookup failed: $($_.Exception.Message)"
    }

    if ($null -eq $output) {
        return "$CommandName is installed"
    }

    return (($output | ForEach-Object { "$_" }) -join " ").Trim()
}

function Get-JsonAssetMap {
    param($AssetsObject)

    $map = @{}
    foreach ($property in $AssetsObject.PSObject.Properties) {
        $map[$property.Name] = $property.Value
    }
    return $map
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Step ("run: " + ($FilePath + " " + ($Arguments -join " ")).Trim())
    if ($DryRun) {
        return
    }

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

Require-WindowsHost

$resolvedRepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$lockFile = Join-Path $resolvedRepoRoot "scripts\db-bundle.lock.json"
$dbDir = Join-Path $resolvedRepoRoot "offline_language_base"
$repoSkillsPath = Join-Path $resolvedRepoRoot ".skills"
$userSkillsPath = Join-Path $HOME ".codex\skills"

if (-not (Test-Path -LiteralPath $lockFile)) {
    throw "Missing lock file: $lockFile"
}

$lock = Get-Content -LiteralPath $lockFile -Raw | ConvertFrom-Json
$assets = Get-JsonAssetMap -AssetsObject $lock.assets
$assetNames = @("primary.sqlite3", "fallback.sqlite3", "definitions_pack.sqlite3")

Write-Step "Repo root: $resolvedRepoRoot"
Write-Step "DB bundle tag: $($lock.tag)"
Write-Step "DB target dir: $dbDir"

$toolMatrix = @(
    @{ Name = "python"; Args = @("--version") },
    @{ Name = "uv"; Args = @("--version") },
    @{ Name = "node"; Args = @("--version") },
    @{ Name = "npm"; Args = @("--version") },
    @{ Name = "rg"; Args = @("--version") }
)

foreach ($tool in $toolMatrix) {
    $versionText = Get-CommandVersionText -CommandName $tool.Name -Arguments $tool.Args
    if ($null -eq $versionText) {
        Write-Step "$($tool.Name): missing"
    } else {
        Write-Step "$($tool.Name): $versionText"
    }
}

if ($SetupVenv) {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $uvCommand) {
        throw "uv is required when -SetupVenv is used."
    }

    Push-Location $resolvedRepoRoot
    try {
        Invoke-Checked -FilePath $uvCommand.Source -Arguments @("venv", ".venv", "--python", $PythonVersion)
        Invoke-Checked -FilePath $uvCommand.Source -Arguments @("sync", "--group", "dev")
    } finally {
        Pop-Location
    }
}

if ($CreateSkillsJunction) {
    if (-not (Test-Path -LiteralPath $userSkillsPath)) {
        throw "Cannot create .skills junction because user skills directory is missing: $userSkillsPath"
    }

    if (Test-Path -LiteralPath $repoSkillsPath) {
        Write-Step ".skills already exists: $repoSkillsPath"
    } else {
        Write-Step "Create .skills junction: $repoSkillsPath -> $userSkillsPath"
        if (-not $DryRun) {
            New-Item -ItemType Junction -Path $repoSkillsPath -Target $userSkillsPath | Out-Null
        }
    }
}
