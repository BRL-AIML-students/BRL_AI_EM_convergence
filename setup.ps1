param(
    [switch]$Dev,
    [switch]$UpdateLock
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '02_BRL_mesh_generator\setup.ps1') -Dev:$Dev -UpdateLock:$UpdateLock
