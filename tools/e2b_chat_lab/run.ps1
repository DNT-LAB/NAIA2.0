param([int]$Port=7362, [string]$Ollama='http://127.0.0.1:11435')
$repoPath = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pythonPath = Join-Path $repoPath 'venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { $pythonPath = 'python' }
try { Invoke-RestMethod "$Ollama/api/version" -TimeoutSec 2 | Out-Null }
catch {
    $ollamaExe = (Get-Command ollama -ErrorAction Stop).Source
    $env:OLLAMA_HOST = ([uri]$Ollama).Authority
    $env:OLLAMA_CONTEXT_LENGTH = '8192'
    Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
}
Write-Host "E2B Chat Lab: http://127.0.0.1:$Port/"
& $pythonPath (Join-Path $PSScriptRoot 'server.py') --port $Port --ollama $Ollama
