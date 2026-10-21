# ============================================================
#  YASB Mint Bar - instalare completa pe un Windows proaspat
#  Ruleaza din folderul yasb-setup:
#     powershell -ExecutionPolicy Bypass -File .\setup.ps1
#  Optional:  -YasbPath "D:\dev\yasb"   -NoAutostart   -NoHWiNFO
# ============================================================

param(
    [string]$YasbPath = "$HOME\yasb",
    [switch]$NoAutostart,
    [switch]$NoHWiNFO
)

# Continue: git/winget write progress to stderr, which would abort PowerShell 5 on "Stop".
# Every step that matters checks its own result and throws.
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$configDir = "$HOME\.config\yasb"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "    $text" -ForegroundColor Green }
function Warn($text) { Write-Host "    $text" -ForegroundColor Yellow }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

function Winget-Install($id, $name) {
    $installed = winget list --id $id --exact --accept-source-agreements | Select-String $id
    if ($installed) { Ok "$name e deja instalat"; return }
    Write-Host "    Instalez $name..."
    winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Instalarea $name a esuat (winget cod $LASTEXITCODE)." }
    Ok "$name instalat"
}

# ---------- 1. winget ----------
Step "Verific winget"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget lipseste. Instaleaza 'App Installer' din Microsoft Store, apoi ruleaza din nou scriptul."
}
Ok "winget gasit"

# ---------- 2. Python 3.14 + Git ----------
Step "Instalez Python 3.14 si Git"
Winget-Install "Python.Python.3.14" "Python 3.14"
Winget-Install "Git.Git" "Git"
Refresh-Path

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Lansatorul 'py' nu e in PATH. Inchide si redeschide PowerShell, apoi ruleaza din nou scriptul."
}
$pyVersion = & py -3.14 --version
if ($LASTEXITCODE -ne 0) { throw "Python 3.14 nu raspunde (py -3.14). Redeschide PowerShell si ruleaza din nou." }
Ok $pyVersion

# ---------- 3. Font JetBrainsMono Nerd Font ----------
Step "Instalez fontul JetBrainsMono Nerd Font"
$fontDir = "$env:LOCALAPPDATA\Microsoft\Windows\Fonts"
$fontReg = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"
if (Test-Path "$fontDir\JetBrainsMonoNerdFont-Regular.ttf") {
    Ok "Fontul e deja instalat"
} else {
    $tmp = Join-Path $env:TEMP "jbmono-nf"
    New-Item -ItemType Directory -Force -Path $tmp, $fontDir | Out-Null
    $zip = Join-Path $tmp "JetBrainsMono.zip"
    Invoke-WebRequest "https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip" -OutFile $zip -UseBasicParsing -ErrorAction Stop
    Expand-Archive $zip -DestinationPath $tmp -Force -ErrorAction Stop
    foreach ($style in "Regular", "Medium", "SemiBold", "Bold", "Italic") {
        $file = "JetBrainsMonoNerdFont-$style.ttf"
        $src = Join-Path $tmp $file
        if (Test-Path $src) {
            Copy-Item $src "$fontDir\$file" -Force
            New-ItemProperty -Path $fontReg -Name "JetBrainsMono Nerd Font $style (TrueType)" -Value "$fontDir\$file" -PropertyType String -Force | Out-Null
        }
    }
    Remove-Item $tmp -Recurse -Force
    Ok "Font instalat (pentru utilizatorul curent)"
}

# ---------- 3b. Opresc YASB-ul care ruleaza ----------
# Altfel cel nou se inchide singur ("Another instance of the YASB is already running") si
# ramane pornit codul vechi: config-ul se reincarca, dar widget-urile nu.
Step "Opresc YASB daca ruleaza"
$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe' OR Name='yasb.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq "yasb.exe" -or $_.CommandLine -like "*src\main.py*" }
if ($running) {
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Ok "YASB oprit (il pornesc din nou la final, cu codul nou)"
} else {
    Ok "YASB nu rula"
}

# ---------- 4. YASB din sursa ----------
Step "Descarc YASB"
if (Test-Path "$YasbPath\src\main.py") {
    Push-Location $YasbPath
    # our patches (clock centering, launcher commands) are re-applied below; restore the originals so the pull can run
    git checkout -- src/main.py src/core/bar.py src/core/widgets/services/quick_launch/providers/__init__.py src/core/widgets/services/quick_launch/service.py src/core/validation/widgets/yasb/quick_launch.py 2>$null
    git pull --ff-only
    Pop-Location
    Ok "YASB actualizat in $YasbPath"
} else {
    git clone https://github.com/amnweb/yasb.git $YasbPath
    if ($LASTEXITCODE -ne 0) { throw "git clone a esuat." }
    Ok "YASB descarcat in $YasbPath"
}

# ---------- 5. Widget-urile noastre (tot ce e in src/ + comenzile barei in lansator) ----------
Step "Copiez widget-urile (sunet, retea, temperatura, moduri, notificari, lansator...)"
$mintOut = & py -3.14 (Join-Path $here "tools\mint_install.py") --yasb $YasbPath --src-only 2>&1
if ($LASTEXITCODE -ne 0) { $mintOut | ForEach-Object { Warn $_ }; throw "Nu am putut copia widget-urile (vezi mesajul de mai sus)." }
$mintOut | Where-Object { $_ -match "fisiere copiate|Lansator" } | ForEach-Object { Ok $_ }
$patchOut = & py -3.14 (Join-Path $here "tools\yasb_patch.py") $YasbPath
foreach ($line in @($patchOut)) { if ($line -like "*patched*") { Ok $line } else { Warn $line } }

# ---------- 6. Dependente ----------
Step "Instalez dependentele YASB (dureaza 1-2 minute)"
Push-Location $YasbPath
& py -3.14 -m pip install --upgrade pip --quiet
& py -3.14 -m pip install . --quiet
$pipExit = $LASTEXITCODE
Pop-Location
if ($pipExit -ne 0) { throw "pip install a esuat. Ruleaza manual: cd $YasbPath; py -3.14 -m pip install ." }
Ok "Dependente instalate"

Step "Instalez pywal (culori din wallpaper)"
# psutil: YASB 2.0.8+ no longer installs it, but our widgets (modes, window_fix, git, desktops) use it
& py -3.14 -m pip install psutil --quiet
if ($LASTEXITCODE -ne 0) { Warn "psutil nu s-a instalat: modurile automate si detectarea jocurilor merg mai slab." } else { Ok "psutil instalat" }
& py -3.14 -m pip install pywal16 colorthief speedtest-cli --quiet
if ($LASTEXITCODE -ne 0) {
    Warn "pywal nu s-a instalat; recolorarea merge oricum, cu extractorul inclus (Pillow)."
} else {
    Ok "pywal16 + colorthief + speedtest-cli instalate"
}

# ---------- 7. Config + stiluri ----------
Step "Pun config-ul si stilurile"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
foreach ($f in "config.yaml", "styles.css") {
    $dest = Join-Path $configDir $f
    if (Test-Path $dest) {
        $backup = "$dest.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        Copy-Item $dest $backup
        Warn "Am salvat vechiul $f ca $(Split-Path $backup -Leaf)"
    }
    Copy-Item (Join-Path $here "config\$f") $dest -Force -ErrorAction Stop
    Ok $f
}
# paleta implicita doar daca nu exista deja una generata din wallpaper
foreach ($f in "palette.css", "palette.json") {
    $dest = Join-Path $configDir $f
    if (-not (Test-Path $dest)) {
        Copy-Item (Join-Path $here "config\$f") $dest -Force -ErrorAction Stop
        Ok "$f (implicit)"
    }
}

# ---------- 7b. Recolorare automata din wallpaper ----------
Step "Pun scriptul de recolorare si generez paleta din wallpaper-ul actual"
# opresc watcher-ul vechi (altfel il tine ocupat pe cel nou)
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*yasb_palette.py*" } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
$toolsDir = Join-Path $configDir "tools"
New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
$paletteScript = Join-Path $toolsDir "yasb_palette.py"
Copy-Item (Join-Path $here "tools\yasb_palette.py") $paletteScript -Force -ErrorAction Stop
Copy-Item (Join-Path $here "tools\yasb_speedtest.py") (Join-Path $toolsDir "yasb_speedtest.py") -Force -ErrorAction Stop

# calea reala a scripturilor in config (cu "/" ca sa nu fie interpretata de YAML)
$cfgFile = Join-Path $configDir "config.yaml"
$toolsFwd = $toolsDir -replace "\\", "/"
$cfgText = [IO.File]::ReadAllText($cfgFile).Replace("__YASB_TOOLS__", $toolsFwd)
[IO.File]::WriteAllText($cfgFile, $cfgText, (New-Object System.Text.UTF8Encoding($false)))
Ok "Speed test: click pe el in bara (langa viteza retelei)"
& py -3.14 $paletteScript --once
if ($LASTEXITCODE -eq 0) {
    Ok "Paleta generata (vezi $configDir\palette.log)"
} else {
    Warn "Nu am putut genera paleta acum; ramane cea implicita."
}

# ---------- 7c. HWiNFO64: temperatura CPU pentru bara ----------
if (-not $NoHWiNFO) {
    Step "Configurez HWiNFO64 (senzori, Shared Memory, pornire la logare)"
    $hw = Join-Path $here "tools\hwinfo_setup.ps1"
    $me = "$env:USERDOMAIN\$env:USERNAME"
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        try { & $hw -ForUser $me } catch { Warn "HWiNFO: $($_.Exception.Message)" }
    } else {
        Warn "Windows iti cere acordul de Administrator (HWiNFO sta in Program Files)."
        try {
            $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$hw`" -ForUser `"$me`""
            if ($p.ExitCode -eq 0) { Ok "HWiNFO configurat" } else { Warn "Configurarea HWiNFO a esuat (cod $($p.ExitCode))." }
        } catch {
            Warn "Ai refuzat acordul de Administrator: HWiNFO ramane cum era (temperatura CPU poate lipsi)."
        }
    }
}

# ---------- 8. Pornire automata ----------
$main = Join-Path $YasbPath "src\main.py"
$pyw = (Get-Command pyw -ErrorAction SilentlyContinue).Source
if (-not $NoAutostart) {
    Step "Setez pornirea automata la logare"
    if ($pyw) {
        $lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "YASB.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($lnk)
        $sc.TargetPath = $pyw
        $sc.Arguments = "-3.14 `"$main`""
        $sc.WorkingDirectory = Join-Path $YasbPath "src"
        $sc.Description = "YASB status bar"
        $sc.Save()
        Ok "Scurtatura creata in Startup"

        $lnk2 = Join-Path ([Environment]::GetFolderPath("Startup")) "YASB Palette.lnk"
        $sc2 = $shell.CreateShortcut($lnk2)
        $sc2.TargetPath = $pyw
        $sc2.Arguments = "-3.14 `"$paletteScript`""
        $sc2.WorkingDirectory = $toolsDir
        $sc2.Description = "YASB: recolorare automata din wallpaper"
        $sc2.Save()
        Ok "Recolorarea automata porneste si ea la logare"
    } else {
        Warn "Nu am gasit 'pyw'; sar peste pornirea automata."
    }
}

# ---------- 9. Pornesc YASB + recolorarea ----------
Step "Pornesc YASB si urmarirea wallpaper-ului"
if ($pyw) {
    Start-Process $pyw -ArgumentList "-3.14", "`"$paletteScript`"" -WorkingDirectory $toolsDir
    Start-Process $pyw -ArgumentList "-3.14", "`"$main`"" -WorkingDirectory (Join-Path $YasbPath "src")
} else {
    Start-Process py -ArgumentList "-3.14", "`"$main`"" -WorkingDirectory (Join-Path $YasbPath "src")
}

Write-Host @"

Gata!
  - Bara porneste acum (si automat la fiecare logare).
  - Culorile se iau din wallpaper: schimba-l din Windows si bara se recoloreaza in ~3 secunde.
  - Vremea: click pe ea prima data si alege orasul.
  - Bulinele: una pentru fiecare desktop virtual (Win + Ctrl + D adauga unul).
  - Log, daca ceva nu merge:  $configDir\yasb.log  si  $configDir\palette.log
"@ -ForegroundColor Green
