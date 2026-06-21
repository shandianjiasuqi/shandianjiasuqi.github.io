param(
  [int]$Limit = 1,
  [switch]$NoAi,
  [switch]$Push
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
& $python -m pip install -r requirements.txt

if ($NoAi) {
  & $python scripts\site.py batch --limit $Limit --no-ai
} else {
  & $python scripts\site.py batch --limit $Limit
}

if ($Push) {
  git add .
  git diff --cached --quiet
  if ($LASTEXITCODE -ne 0) {
    $date = Get-Date -Format "yyyy-MM-dd"
    git commit -m "batch articles $date"
    if (git remote) { git push } else { Write-Host "No git remote configured yet." }
  }
}
