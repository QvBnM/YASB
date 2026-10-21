# ============================================================
#  HWiNFO64 pentru bara YASB
#   - instaleaza HWiNFO daca lipseste (winget)
#   - il seteaza: doar senzori, pornit minimizat in tray, fara ecran de bun venit,
#     Shared Memory Support pornit (de acolo citeste YASB temperatura CPU)
#   - creeaza sarcina programata "YASB HWiNFO": porneste HWiNFO la logare, cu drepturi
#     de administrator, fara fereastra UAC. Aceeasi sarcina il reporneste cand YASB
#     nu mai primeste date (versiunea gratuita opreste Shared Memory dupa 12 ore).
#
#  Nu atinge nimic din ce e deja bine. Daca HWiNFO e instalat, setat si pornit, scriptul
#  spune asta si iese: nu mai opreste programul, nu rescrie fisierul de setari, nu cere
#  Administrator degeaba.
#
#      hwinfo_setup.ps1 -CheckOnly    # doar se uita; iese cu 0 = totul e bine, 2 = e de lucru
#                                     # (merge si fara Administrator, de asta il cheama setup.ps1 intai)
#      hwinfo_setup.ps1               # repara doar ce lipseste (cere Administrator)
#      hwinfo_setup.ps1 -Force        # reface tot, chiar daca pare in regula
# ============================================================
param([string]$ForUser = "", [switch]$CheckOnly, [switch]$Force)

$ErrorActionPreference = "Continue"
function Ok($t)   { Write-Host "    $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    $t" -ForegroundColor Yellow }
function Info($t) { Write-Host "    $t" }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $CheckOnly -and -not $admin) { throw "hwinfo_setup.ps1 trebuie rulat ca Administrator." }
if (-not $ForUser) { $ForUser = "$env:USERDOMAIN\$env:USERNAME" }

$TaskName = "YASB HWiNFO"

# Setarile de care are nevoie bara. Scrise o singura data, aici: si verificarea, si repararea
# se uita la aceeasi lista.
$Want = [ordered]@{
    "SensorsOnly"            = "1"   # doar fereastra de senzori
    "SensorsSM"              = "1"   # Shared Memory Support: de aici citeste YASB
    "MinimalizeSensors"      = "1"   # senzorii pornesc minimizati in tray
    "MinimalizeMainWnd"      = "1"
    "MinimalizeSensorsClose" = "1"   # X pe fereastra de senzori = in tray, nu inchis
    "ShowWelcomeAndProgress" = "0"   # fara ecran de bun venit
    "OpenSystemSummary"      = "0"
    "Autorun"                = "0"   # pornirea o face sarcina noastra (o singura data, nu de doua ori)
}

# ---------- unde e HWiNFO ----------
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

# ---------- ce lipseste ----------
function Get-IniSettings($ini) {
    # cheile din [Settings], asa cum sunt acum in fisier
    $have = @{}
    if (-not (Test-Path $ini)) { return $have }
    $inSettings = $false
    foreach ($line in (Get-Content $ini -Encoding Default -ErrorAction SilentlyContinue)) {
        if ($line -match '^\[(.+)\]') { $inSettings = ($Matches[1] -eq "Settings"); continue }
        if ($inSettings -and $line -match '^([^=]+)=(.*)$') { $have[$Matches[1].Trim()] = $Matches[2].Trim() }
    }
    return $have
}

function Test-TaskReady($exe) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { return $false }
    # sarcina trebuie sa porneasca exact programul gasit acum (altfel a fost mutat / reinstalat)
    $args = @($task.Actions | ForEach-Object { $_.Arguments }) -join " "
    return $args -like "*$exe*"
}

$exe = Find-HWiNFO
$missing = New-Object System.Collections.Generic.List[string]
if (-not $exe) {
    $missing.Add("HWiNFO nu e instalat")
} else {
    $have = Get-IniSettings (Join-Path (Split-Path $exe) "HWiNFO64.INI")
    $wrong = @($Want.Keys | Where-Object { $have[$_] -ne $Want[$_] })
    if ($wrong.Count -gt 0) { $missing.Add("setari de schimbat: $($wrong -join ', ')") }
    if (-not (Test-TaskReady $exe)) { $missing.Add("sarcina '$TaskName' lipseste") }
    if (-not (Get-Process HWiNFO64 -ErrorAction SilentlyContinue)) { $missing.Add("HWiNFO nu ruleaza") }
}

if ($CheckOnly) {
    if ($missing.Count -eq 0) { Ok "HWiNFO e deja configurat: $exe"; exit 0 }
    foreach ($m in $missing) { Info "de facut: $m" }
    exit 2
}

if ($missing.Count -eq 0 -and -not $Force) {
    Ok "HWiNFO e deja configurat ($exe); nu ating nimic"
    exit 0
}

# ---------- 1. instalez, daca lipseste ----------
if (-not $exe) {
    Write-Host "    Instalez HWiNFO64 (winget)..."
    winget install --id REALiX.HWiNFO --exact --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $exe = Find-HWiNFO
}
if (-not $exe) { throw "Nu gasesc HWiNFO64.EXE. Instaleaza-l de pe hwinfo.com si ruleaza din nou." }
Ok "HWiNFO: $exe"

# ---------- 2. setarile (HWiNFO le rescrie la iesire, deci il opresc intai) ----------
$ini = Join-Path (Split-Path $exe) "HWiNFO64.INI"
$have = Get-IniSettings $ini
$needIni = $Force -or (@($Want.Keys | Where-Object { $have[$_] -ne $Want[$_] }).Count -gt 0)
if ($needIni) {
    Get-Process HWiNFO64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    $lines = @()
    if (Test-Path $ini) { $lines = Get-Content $ini -Encoding Default }
    if (-not ($lines -match '^\[Settings\]')) { $lines = @("[Settings]") + $lines }
    $out = New-Object System.Collections.Generic.List[string]
    $inSettings = $false
    $done = @{}
    foreach ($line in $lines) {
        if ($line -match '^\[(.+)\]') {
            if ($inSettings) { foreach ($k in $Want.Keys) { if (-not $done[$k]) { $out.Add("$k=$($Want[$k])"); $done[$k] = $true } } }
            $inSettings = ($Matches[1] -eq "Settings")
            $out.Add($line); continue
        }
        if ($inSettings -and $line -match '^([^=]+)=') {
            $k = $Matches[1].Trim()
            if ($Want.Contains($k)) { $out.Add("$k=$($Want[$k])"); $done[$k] = $true; continue }
        }
        $out.Add($line)
    }
    if ($inSettings) { foreach ($k in $Want.Keys) { if (-not $done[$k]) { $out.Add("$k=$($Want[$k])") } } }
    if (Test-Path $ini) { Copy-Item $ini "$ini.bak" -Force }
    Set-Content -Path $ini -Value $out -Encoding Default
    Ok "Setari scrise in $ini (copie: HWiNFO64.INI.bak)"
} else {
    Ok "Setarile din HWiNFO64.INI erau deja bune; nu le-am atins"
}

# ---------- 3. sarcina programata: porneste / reporneste HWiNFO, ca admin, fara UAC ----------
if ($Force -or -not (Test-TaskReady $exe)) {
    $cmd = "Get-Process HWiNFO64 -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 2; Start-Process -FilePath '$exe'"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"$cmd`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $ForUser
    $trigger.Delay = "PT20S"   # dupa ce porneste desktop-ul
    $principal = New-ScheduledTaskPrincipal -UserId $ForUser -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Ok "Sarcina '$TaskName' creata: porneste HWiNFO la logare (si il reporneste YASB cand e nevoie)"
    } else {
        Warn "Nu am putut crea sarcina '$TaskName'."
    }
} else {
    Ok "Sarcina '$TaskName' exista deja"
}

# ---------- 4. pornesc HWiNFO, daca nu merge deja ----------
if ($needIni -or $Force -or -not (Get-Process HWiNFO64 -ErrorAction SilentlyContinue)) {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 6
}
if (Get-Process HWiNFO64 -ErrorAction SilentlyContinue) { Ok "HWiNFO ruleaza (minimizat in tray)" } else { Warn "HWiNFO nu a pornit; porneste-l o data manual." }
