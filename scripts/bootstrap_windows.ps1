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
