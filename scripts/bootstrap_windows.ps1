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

Require-WindowsHost
