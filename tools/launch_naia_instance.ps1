<#
.SYNOPSIS
  Launch an isolated NAIA instance so several can run side by side.

.DESCRIPTION
  Multiple NAIA instances (e.g. one bound to NAI, one to ComfyUI, or two
  different NAI accounts) normally collide on three shared resources:
    1. the Electron single-instance lock (keyed on the Electron userData dir),
    2. the backend user-data folder (config/save/output/wildcards/tokens),
    3. the Grok progrok proxy port.

  This launcher gives each named instance its own:
    * Electron userData      -> via the built-in --user-data-dir switch
                                (separate single-instance lock + session/cookies),
    * backend user-data       -> via the NAIA_USER_DATA_DIR env var
                                (separate config, save dir, secure_tokens.json),
    * Grok proxy port         -> via NAIA_GROK_PROXY_PORT (or shell auto-probe).

  The backend HTTP port needs no handling: NAIA already launches it with
  --auto-port and discovers the bound port from stdout.

  Works with both run modes:
    * Source / plan A (npm Electron):  app/electron/node_modules/.bin/electron.cmd .
    * Portable build:                  pass -Target <path-to-NAIA.exe>.

.PARAMETER Name
  Short instance label (e.g. "nai", "comfy"). Picks the default data folder
  %LOCALAPPDATA%\NAIA-instances\<Name> when -DataRoot is not given.

.PARAMETER Target
  Path to a portable NAIA.exe. Omit to run the source build via Electron
  (requires `npm install` under app/electron first).

.PARAMETER DataRoot
  Base directory that holds this instance's electron/ and user-data/ folders.
  Default: %LOCALAPPDATA%\NAIA-instances\<Name>.

.PARAMETER GrokPort
  Fixed Grok proxy port for this instance. 0 (default) lets the shell auto-pick
  a free port (only effective on builds that include the dynamic-port change;
  older portables ignore this and may lose Grok on the 2nd instance).

.PARAMETER DryRun
  Print the resolved configuration and the exact launch command, but do not start
  anything.

.EXAMPLE
  # Two source instances, one per backend:
  pwsh tools/launch_naia_instance.ps1 -Name nai
  pwsh tools/launch_naia_instance.ps1 -Name comfy

.EXAMPLE
  # Two copies of the installed portable:
  pwsh tools/launch_naia_instance.ps1 -Name acctA -Target "C:\NAIA\NAIA.exe"
  pwsh tools/launch_naia_instance.ps1 -Name acctB -Target "C:\NAIA\NAIA.exe"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Target = "",
    [string]$DataRoot = "",
    [int]$GrokPort = 0,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Sanitize the instance label for use in a path.
$safeName = ($Name -replace '[^A-Za-z0-9_.-]', '_').Trim('_')
if (-not $safeName) { throw "Instance -Name must contain at least one path-safe character." }

if ($GrokPort -lt 0 -or $GrokPort -gt 65535) {
    throw "-GrokPort must be between 1 and 65535 (or 0 for auto)."
}

if (-not $DataRoot) {
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $env:USERPROFILE "AppData\Local" }
    $DataRoot = Join-Path (Join-Path $base "NAIA-instances") $safeName
}
$electronUserData = Join-Path $DataRoot "electron"
$backendUserData  = Join-Path $DataRoot "user-data"

# Resolve the launch target.
$repoRoot   = Split-Path -Parent $PSScriptRoot          # tools/ -> repo root
$electronDir = Join-Path $repoRoot "app\electron"
if ($Target) {
    if (-not (Test-Path -LiteralPath $Target)) { throw "Portable target not found: $Target" }
    $exe     = (Resolve-Path -LiteralPath $Target).Path
    $exeArgs = @("--user-data-dir=$electronUserData")
    $workDir = Split-Path -Parent $exe
    $modeDesc = "portable: $exe"
} else {
    $electronBin = Join-Path $electronDir "node_modules\.bin\electron.cmd"
    if (-not (Test-Path -LiteralPath $electronBin)) {
        throw "Source Electron not installed. Run:  cd `"$electronDir`"; npm install`n(or pass -Target <NAIA.exe> to use a portable build)."
    }
    $exe     = $electronBin
    $exeArgs = @(".", "--user-data-dir=$electronUserData")
    $workDir = $electronDir
    $modeDesc = "source (electron .)"
}

Write-Host "NAIA instance '$safeName'"
Write-Host "  mode               : $modeDesc"
Write-Host "  electron user-data : $electronUserData"
Write-Host "  backend  user-data : $backendUserData"
Write-Host ("  grok proxy port    : " + ($(if ($GrokPort -gt 0) { "$GrokPort (fixed)" } else { "auto (free port)" })))
Write-Host "  launch             : `"$exe`" $($exeArgs -join ' ')   (cwd: $workDir)"

if ($DryRun) {
    Write-Host "DryRun: not launching."
    return
}

New-Item -ItemType Directory -Force -Path $electronUserData | Out-Null
New-Item -ItemType Directory -Force -Path $backendUserData  | Out-Null

# Per-instance environment (inherited by the child process).
$env:NAIA_USER_DATA_DIR = $backendUserData
if ($GrokPort -gt 0) {
    $env:NAIA_GROK_PROXY_PORT = "$GrokPort"
} else {
    # Auto mode: drop any inherited fixed port so it does not silently pin this
    # instance (the shell will then probe a free port itself).
    Remove-Item Env:NAIA_GROK_PROXY_PORT -ErrorAction SilentlyContinue
}

Start-Process -FilePath $exe -ArgumentList $exeArgs -WorkingDirectory $workDir
Write-Host "Launched. The backend will pick a free HTTP port automatically (see the shell log)."
