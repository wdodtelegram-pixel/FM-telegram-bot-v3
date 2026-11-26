# Stops FM Control. Your data is kept; start it again with Start-Windows.bat.
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $bin = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin'
    if (Test-Path (Join-Path $bin 'docker.exe')) { $env:Path = "$bin;$env:Path" }
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running, so FM Control is already stopped."
} else {
    docker compose stop
    if ($LASTEXITCODE -eq 0) { Write-Host "Stopped. Your data is kept. Double-click Start-Windows.bat to start again." }
}
if (-not $env:FM_NO_PAUSE) { Write-Host ""; [void](Read-Host "Press Enter to close this window") }
