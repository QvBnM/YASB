# ============================================================
#  HWiNFO64 pentru bara YASB (ruleaza ca Administrator)
#   - instaleaza HWiNFO daca lipseste (winget)
#   - il seteaza: doar senzori, pornit minimizat in tray, fara ecran de bun venit,
#     Shared Memory Support pornit (de acolo citeste YASB temperatura CPU)
#   - creeaza sarcina programata "YASB HWiNFO": porneste HWiNFO la logare, cu drepturi
#     de administrator, fara fereastra UAC. Aceeasi sarcina il reporneste cand YASB
#     nu mai primeste date (versiunea gratuita opreste Shared Memory dupa 12 ore).
# ============================================================
param([string]$ForUser = "")

$ErrorActionPreference = "Continue"
function Ok($t)   { Write-Host "    $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    $t" -ForegroundColor Yellow }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "hwinfo_setup.ps1 trebuie rulat ca Administrator." }
if (-not $ForUser) { $ForUser = "$env:USERDOMAIN\$env:USERNAME" }

# ---------- 1. unde e HWiNFO (sau il instalez) ----------
function Find-HWiNFO {
    $running = Get-Process HWiNFO64 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($running -and $running.Path) { return $running.Path }
    foreach ($p in @("$env:ProgramFiles\HWiNFO64\HWiNFO64.EXE", "${env:ProgramFiles(x86)}\HWiNFO64\HWiNFO64.EXE")) {
        if (Test-Path $p) { return $p }
    }
    $key = Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" -ErrorAction SilentlyContinue |
        Get-ItemProperty -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like "HWiNFO*" } | Select-Object -First 1
    if ($key -and $key.InstallLocation) {
        $p = Join-Path $key.InstallLocation "HWiNFO64.EXE"
        if (Test-Path $p) { return $p }
    }
    return $null
}

$exe = Find-HWiNFO
if (-not $exe) {
    Write-Host "    Instalez HWiNFO64 (winget)..."
    winget install --id REALiX.HWiNFO --exact --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $exe = Find-HWiNFO
}
if (-not $exe) { throw "Nu gasesc HWiNFO64.EXE. Instaleaza-l de pe hwinfo.com si ruleaza din nou." }
Ok "HWiNFO: $exe"

# ---------- 2. setarile (HWiNFO le rescrie la iesire, deci il opresc intai) ----------
Get-Process HWiNFO64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$ini = Join-Path (Split-Path $exe) "HWiNFO64.INI"
$want = [ordered]@{
    "SensorsOnly"            = "1"   # doar fereastra de senzori
    "SensorsSM"              = "1"   # Shared Memory Support: de aici citeste YASB
    "MinimalizeSensors"      = "1"   # senzorii pornesc minimizati in tray
    "MinimalizeMainWnd"      = "1"
    "MinimalizeSensorsClose" = "1"   # X pe fereastra de senzori = in tray, nu inchis
    "ShowWelcomeAndProgress" = "0"   # fara ecran de bun venit
    "OpenSystemSummary"      = "0"
    "Autorun"                = "0"   # pornirea o face sarcina noastra (o singura data, nu de doua ori)
}
$lines = @()
if (Test-Path $ini) { $lines = Get-Content $ini -Encoding Default }
if (-not ($lines -match '^\[Settings\]')) { $lines = @("[Settings]") + $lines }
$out = New-Object System.Collections.Generic.List[string]
$inSettings = $false
$done = @{}
foreach ($line in $lines) {
    if ($line -match '^\[(.+)\]') {
        if ($inSettings) { foreach ($k in $want.Keys) { if (-not $done[$k]) { $out.Add("$k=$($want[$k])"); $done[$k] = $true } } }
        $inSettings = ($Matches[1] -eq "Settings")
        $out.Add($line); continue
    }
    if ($inSettings -and $line -match '^([^=]+)=') {
        $k = $Matches[1].Trim()
        if ($want.Contains($k)) { $out.Add("$k=$($want[$k])"); $done[$k] = $true; continue }
    }
    $out.Add($line)
}
if ($inSettings) { foreach ($k in $want.Keys) { if (-not $done[$k]) { $out.Add("$k=$($want[$k])") } } }
if (Test-Path $ini) { Copy-Item $ini "$ini.bak" -Force }
Set-Content -Path $ini -Value $out -Encoding Default
Ok "Setari scrise in $ini (copie: HWiNFO64.INI.bak)"

# ---------- 3. sarcina programata: porneste / reporneste HWiNFO, ca admin, fara UAC ----------
$taskName = "YASB HWiNFO"
$cmd = "Get-Process HWiNFO64 -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 2; Start-Process -FilePath '$exe'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"$cmd`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $ForUser
$trigger.Delay = "PT20S"   # dupa ce porneste desktop-ul
$principal = New-ScheduledTaskPrincipal -UserId $ForUser -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Ok "Sarcina '$taskName' creata: porneste HWiNFO la logare (si il reporneste YASB cand e nevoie)"
} else {
    Warn "Nu am putut crea sarcina '$taskName'."
}

# ---------- 4. pornesc HWiNFO acum ----------
Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 6
if (Get-Process HWiNFO64 -ErrorAction SilentlyContinue) { Ok "HWiNFO ruleaza (minimizat in tray)" } else { Warn "HWiNFO nu a pornit; porneste-l o data manual." }
