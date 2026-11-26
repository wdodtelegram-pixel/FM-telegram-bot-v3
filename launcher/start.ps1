# FM Control launcher for Windows. Double-click Start-Windows.bat (it calls this).
#
# First run: checks Docker, asks for your Telegram bot token, generates the secrets,
# starts everything, creates the first admin login, and opens the website.
# Every later run: starts (and updates) everything and opens the website.
# Safe to run again at any time. Works in Windows PowerShell 5.1 and PowerShell 7.

$ErrorActionPreference = 'Continue'
Set-Location (Split-Path -Parent $PSScriptRoot)
$Root = (Get-Location).Path
$EnvFile = Join-Path $Root '.env'

function Say($m)  { Write-Host $m }
function Step($m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }

function PauseExit($code) {
    if (-not $env:FM_NO_PAUSE) { Write-Host ""; [void](Read-Host "Press Enter to close this window") }
    exit $code
}
function Fail($m) { Write-Host ""; Write-Host "X $m" -ForegroundColor Red; PauseExit 1 }

function RandomHex($bytes) {
    $b = New-Object byte[] $bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($b)
    $rng.Dispose()
    return (($b | ForEach-Object { $_.ToString('x2') }) -join '')
}

function EnvGet($name) {
    if (-not (Test-Path $EnvFile)) { return $null }
    $line = Get-Content $EnvFile | Where-Object { $_ -like "$name=*" } | Select-Object -First 1
    if ($line) { return $line.Substring($name.Length + 1) }
    return $null
}

function PortInUse($port) {
    $c = New-Object System.Net.Sockets.TcpClient
    try { $c.Connect('127.0.0.1', [int]$port); return $true } catch { return $false } finally { $c.Close() }
}

function Quiet { param([scriptblock]$Block) & $Block *> $null; return ($LASTEXITCODE -eq 0) }

# Windows time zone name -> the IANA name the application uses. Anything not listed falls back to UTC
# (the person can type theirs).
$TzMap = @{
    'Singapore Standard Time' = 'Asia/Singapore'; 'China Standard Time' = 'Asia/Shanghai'
    'Tokyo Standard Time' = 'Asia/Tokyo'; 'India Standard Time' = 'Asia/Kolkata'
    'W. Australia Standard Time' = 'Australia/Perth'; 'AUS Eastern Standard Time' = 'Australia/Sydney'
    'GMT Standard Time' = 'Europe/London'; 'W. Europe Standard Time' = 'Europe/Berlin'
    'Romance Standard Time' = 'Europe/Paris'; 'Eastern Standard Time' = 'America/New_York'
    'Central Standard Time' = 'America/Chicago'; 'Mountain Standard Time' = 'America/Denver'
    'Pacific Standard Time' = 'America/Los_Angeles'; 'Arab Standard Time' = 'Asia/Riyadh'
    'Malay Peninsula Standard Time' = 'Asia/Kuala_Lumpur'; 'SE Asia Standard Time' = 'Asia/Bangkok'
    'Taipei Standard Time' = 'Asia/Taipei'; 'Korea Standard Time' = 'Asia/Seoul'
    'UTC' = 'UTC'
}

Say "FM Control"
Say "Telegram bot + master-control website"

# 1. Docker -------------------------------------------------------------------
Step "Checking Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $bin = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin'
    if (Test-Path (Join-Path $bin 'docker.exe')) { $env:Path = "$bin;$env:Path" }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Warn "Docker is not installed."
    Say  "  FM Control runs inside Docker Desktop, which is free for personal and small-business use."
    Say  "  1. Install it from:  https://www.docker.com/products/docker-desktop/"
    Say  "  2. Open Docker Desktop once and accept its terms (restart Windows if it asks)."
    Say  "  3. Double-click Start-Windows.bat again."
    Start-Process 'https://www.docker.com/products/docker-desktop/'
    PauseExit 1
}
if (-not (Quiet { docker compose version })) { Fail "Your Docker is too old (no 'docker compose'). Please update Docker Desktop." }

if (-not (Quiet { docker info })) {
    Warn "Docker is installed but not running. Starting it..."
    $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $exe) { Start-Process $exe }
    $limit = 240; if ($env:FM_DOCKER_WAIT) { $limit = [int]$env:FM_DOCKER_WAIT }
    $waited = 0
    while (-not (Quiet { docker info })) {
        if ($waited -ge $limit) { Fail "Docker did not start. Open Docker Desktop yourself, wait until it says it is running, then try again." }
        Write-Host -NoNewline "."; Start-Sleep -Seconds 3; $waited += 3
    }
    Write-Host ""
}
Ok "Docker is running"

# 2. Configuration --------------------------------------------------------------
if (-not (Test-Path $EnvFile)) {
    Step "First-time setup"
    Say "You need a Telegram bot. It takes one minute:"
    Say "  1. In Telegram, open  @BotFather  and send  /newbot"
    Say "  2. Pick a name and a username ending in 'bot'"
    Say "  3. Copy the token it gives you (it looks like 123456789:AAH...)"
    Say ""
    $Token = ''
    while ($true) {
        $secure = Read-Host "Paste your bot token (typing is hidden), or press Enter to quit" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
        $Token = ($Token -replace '\s', '')
        if (-not $Token) { Say "No problem. Run this again when you have a token."; PauseExit 0 }
        if ($Token -notmatch '^[0-9]{6,16}:[A-Za-z0-9_-]{30,}$') {
            Warn "That does not look like a bot token (expected digits, a colon, then letters and digits). Copy the whole line from @BotFather."
            continue
        }
        # Ask Telegram if it knows this token (skipped quietly when offline).
        $reached = $true
        try {
            $reply = Invoke-RestMethod -Uri "https://api.telegram.org/bot$Token/getMe" -TimeoutSec 10 -ErrorAction Stop
            if ($reply.ok) { Ok "Telegram accepted it: @$($reply.result.username)"; break }
        } catch {
            if ($_.Exception.Response) { $reached = $true; Warn "Telegram rejected that token. Check it, or send /token to @BotFather for a fresh one."; continue }
            $reached = $false
        }
        if (-not $reached) { Warn "Could not reach Telegram to check it (no internet?). Continuing anyway."; break }
    }

    $defaultTz = 'UTC'
    try {
        $win = [System.TimeZoneInfo]::Local.Id
        if ($TzMap.ContainsKey($win)) { $defaultTz = $TzMap[$win] }
    } catch { }
    $tzIn = Read-Host "Timezone for 'today' in the bot and website, e.g. Asia/Singapore [$defaultTz]"
    $tz = if ($tzIn) { $tzIn.Trim() } else { $defaultTz }

    $webPort = 3000
    while ((PortInUse $webPort) -and $webPort -lt 3020) { $webPort++ }
    if ($webPort -ne 3000) { Warn "Port 3000 is busy, so the website will use port $webPort." }

    $content = @(
        "# Written by the FM Control launcher. Keep this file private: it holds your bot token.",
        "TELEGRAM_BOT_TOKEN=$Token",
        "SECRET_KEY=$(RandomHex 32)",
        "POSTGRES_PASSWORD=$(RandomHex 16)",
        "TZ=$tz",
        "WEB_PORT=$webPort"
    ) -join "`n"
    # UTF-8 *without* a byte-order mark: a BOM would corrupt the first variable name for docker compose.
    [System.IO.File]::WriteAllText($EnvFile, $content + "`n", (New-Object System.Text.UTF8Encoding($false)))
    Ok "Saved your settings to .env"
}
$WebPort = EnvGet 'WEB_PORT'; if (-not $WebPort) { $WebPort = '3000' }
$Site = "http://localhost:$WebPort"

# 3. Images ----------------------------------------------------------------------
Step "Getting the application (the first time takes a few minutes)"
if (Quiet { docker compose pull --quiet }) {
    Ok "Downloaded the latest version"
} else {
    Warn "Prebuilt images are not available, so building from the included source."
    docker compose build
    if ($LASTEXITCODE -ne 0) { Fail "The build failed. Scroll up for the reason, or send it to whoever set this up." }
    Ok "Built from source"
}

# 4. Start ----------------------------------------------------------------------------
Step "Starting"
docker compose up -d
if ($LASTEXITCODE -ne 0) { Fail "Could not start. Scroll up for the reason (a busy port is the usual cause: edit WEB_PORT in .env)." }

$limit = 180; if ($env:FM_START_WAIT) { $limit = [int]$env:FM_START_WAIT }
$waited = 0
Write-Host -NoNewline "  Waiting for the website"
while ($true) {
    $up = $false
    try { $r = Invoke-WebRequest -Uri "$Site/api/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop; $up = ($r.StatusCode -eq 200) } catch { }
    if ($up) { break }
    if ($waited -ge $limit) { Write-Host ""; docker compose ps; Fail "It did not become ready. Run 'docker compose logs' in this folder to see why." }
    Write-Host -NoNewline "."; Start-Sleep -Seconds 3; $waited += 3
}
Write-Host ""
Ok "Website is up at $Site"
$running = (docker compose ps --status running --services 2>$null) -split "`n" | ForEach-Object { $_.Trim() }
if ($running -contains 'bot') { Ok "Bot is running" } else { Warn "The bot is not running. Run 'docker compose logs bot' to see why." }

# 5. First admin -------------------------------------------------------------------------
function SetupDone { return (Quiet { docker compose run --rm -T migrate python -m botapp.admin setup-status }) }
if (-not (SetupDone)) {
    Step "Create your admin login"
    Say "This is the login you will use on the website. The first person to claim it in Telegram becomes master control."
    Say ""
    docker compose run --rm migrate python -m botapp.admin first-run
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the setup code." }
    Say ""
    Say "Waiting for you to send the code to your bot (Ctrl+C to skip; run this launcher again later)..."
    $waited = 0
    while (-not (SetupDone)) {
        if ($waited -ge 900) { Warn "Still waiting. Run this launcher again when you have sent the code."; break }
        Start-Sleep -Seconds 5; $waited += 5
    }
    if (SetupDone) { Ok "You are master control." }
}

# 6. Done ------------------------------------------------------------------------------------
Step "Ready"
Say "  Website:  $Site"
Say "  Bot:      open your bot in Telegram and send /start"
Say ""
Say "  Stop it:        double-click Stop-Windows.bat"
Say "  Start it again: double-click Start-Windows.bat (it also installs updates)"
Say "  Keep it running: it works while this computer is on and Docker Desktop is running."
Say "                   In Docker Desktop > Settings, tick 'Start Docker Desktop when you sign in'."
Start-Process $Site
PauseExit 0
