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

Require-WindowsHost
