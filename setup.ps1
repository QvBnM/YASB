# ============================================================
#  YASB Mint Bar - instalare completa pe un Windows proaspat
#  Ruleaza din folderul yasb-setup:
#     powershell -ExecutionPolicy Bypass -File .\setup.ps1
#  Optional:  -YasbPath "D:\dev\yasb"   -NoAutostart   -NoHWiNFO   -ForceHWiNFO
#             -PythonVersion 3.13
# ============================================================

param(
    [string]$YasbPath = "$HOME\yasb",
    # Versiunea YASB de folosit. Implicit se ia cea fixata in tools\yasb-pin.txt, adica aceea
    # pe care bara a mers ultima data. Dai -YasbRef main (sau un commit) ca sa treci conștient
    # pe alta; daca verificarea trece, noua versiune devine cea fixata.
    [string]$YasbRef = "",
    [switch]$NoAutostart,
    [switch]$NoHWiNFO,
    [switch]$ForceHWiNFO,
    # Versiunea de Python pe care merge bara, scrisa intr-un singur loc: de aici se iau si
    # pachetul din winget, si lansatorul (py -3.14), si scurtaturile din Startup. Pana acum
    # era scrisa de 18 ori in script, deci o schimbare insemna 18 modificari.
    [string]$PythonVersion = "3.14"
)

# Steagul lansatorului: "py -3.14 fisier.py" alege anume versiunea asta, oricate ai instalate.
$pyFlag = "-$PythonVersion"

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

# ---------- 2. Python + Git ----------
Step "Instalez Python $PythonVersion si Git"
Winget-Install "Python.Python.$PythonVersion" "Python $PythonVersion"
Winget-Install "Git.Git" "Git"
Refresh-Path

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Lansatorul 'py' nu e in PATH. Inchide si redeschide PowerShell, apoi ruleaza din nou scriptul."
}
$pyBanner = & py $pyFlag --version
if ($LASTEXITCODE -ne 0) { throw "Python $PythonVersion nu raspunde (py $pyFlag). Redeschide PowerShell si ruleaza din nou." }
Ok $pyBanner

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

# ---------- 4. YASB din sursa, pe versiunea verificata ----------
# Widget-urile noastre se sprijina pe lucruri din interiorul YASB. Daca instalarea ar lua mereu
# ultima versiune de pe main, o schimbare la ei ar putea opri bara intr-o dimineata, fara ca tu
# sa fi atins nimic. De aceea ramanem pe commit-ul pe care bara chiar a mers.
$pinFile = Join-Path $here "tools\yasb-pin.txt"
$pin = ""
if (Test-Path $pinFile) {
    # un fisier care are doar comentarii lasa $pinLine gol: nu chemam .Trim() pe nimic
    $pinLine = Get-Content $pinFile | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") } | Select-Object -First 1
    if ($pinLine) { $pin = $pinLine.Trim() }
}
$wantRef = if ($YasbRef) { $YasbRef } elseif ($pin -and $pin -ne "unpinned") { $pin } else { "" }

Step "Descarc YASB"
if (Test-Path "$YasbPath\src\main.py") {
    Push-Location $YasbPath
    # peticele noastre (centrarea ceasului, comenzile din lansator) se pun din nou mai jos;
    # intai aducem fisierele la original, ca sa se poata schimba versiunea
    git checkout -- src/main.py src/core/bar.py src/core/widgets/services/quick_launch/providers/__init__.py src/core/widgets/services/quick_launch/service.py src/core/validation/widgets/yasb/quick_launch.py 2>$null
    git fetch --tags origin
    Pop-Location
} else {
    git clone https://github.com/amnweb/yasb.git $YasbPath
    if ($LASTEXITCODE -ne 0) { throw "git clone a esuat." }
    Ok "YASB descarcat in $YasbPath"
}

Push-Location $YasbPath
if ($wantRef) {
    git checkout --quiet $wantRef
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Nu pot trece YASB pe '$wantRef'. Verifica numele versiunii." }
    Ok "YASB pe versiunea verificata ($($wantRef.Substring(0, [Math]::Min(10, $wantRef.Length))))"
} else {
    # fara o versiune fixata luam ramura principala a lor, oricum s-ar numi
    $branch = (git symbolic-ref --quiet --short refs/remotes/origin/HEAD) -replace '^origin/', ''
    if (-not $branch) { $branch = "main" }
    git checkout --quiet $branch
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Nu pot trece YASB pe ramura '$branch'." }
    git pull --ff-only
    Warn "Nicio versiune fixata inca: iau ultima de pe $branch. Daca verificarea trece, ramane fixata pe ea."
}
$yasbCommit = (git rev-parse HEAD)
Pop-Location
if ($yasbCommit) {
    Ok "YASB: commit $($yasbCommit.Trim().Substring(0,10))"
} else {
    Warn "Nu pot citi versiunea YASB (copia nu pare un depozit git)."
}

# ---------- 5. Widget-urile noastre (tot ce e in src/ + comenzile barei in lansator) ----------
Step "Copiez widget-urile (sunet, retea, temperatura, moduri, notificari, lansator...)"
$mintOut = & py $pyFlag (Join-Path $here "tools\mint_install.py") --yasb $YasbPath --src-only 2>&1
if ($LASTEXITCODE -ne 0) { $mintOut | ForEach-Object { Warn $_ }; throw "Nu am putut copia widget-urile (vezi mesajul de mai sus)." }
$mintOut | Where-Object { $_ -match "fisiere copiate|Lansator" } | ForEach-Object { Ok $_ }
$patchOut = & py $pyFlag (Join-Path $here "tools\yasb_patch.py") $YasbPath
$patchExit = $LASTEXITCODE
foreach ($line in @($patchOut)) { if ($line -like "*patched*") { Ok $line } else { Warn $line } }
# Peticul din main.py nu e un moft: fara el qasync ia PyQt5 daca alt program l-a instalat, si
# bara nu mai porneste deloc. Pana acum un petic neaplicat era doar un rand galben, iar
# instalarea mergea inainte inca doua minute, ca sa porneasca la final o bara care nu apare.
if ($patchExit -ne 0) { throw "Peticul din main.py nu s-a aplicat (vezi rindul galben de mai sus). YASB s-a schimbat acolo unde ne sprijinim." }

# ---------- 6. Dependente ----------
Step "Instalez dependentele YASB (dureaza 1-2 minute)"
Push-Location $YasbPath
& py $pyFlag -m pip install --upgrade pip --quiet
& py $pyFlag -m pip install . --quiet
$pipExit = $LASTEXITCODE
Pop-Location
if ($pipExit -ne 0) { throw "pip install a esuat. Ruleaza manual: cd $YasbPath; py $pyFlag -m pip install ." }
Ok "Dependente instalate"

Step "Instalez pywal (culori din wallpaper)"
# psutil nu mai e nevoie: widget-urile citesc procesele direct din Windows (mint_common.py)
& py $pyFlag -m pip install pywal16 colorthief speedtest-cli --quiet
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
        # Pastram ultimele 5 copii. Pana acum se adunau cate doua la fiecare instalare si nu
        # pleca nimeni sa le stearga. Numele are data in fata (yyyyMMdd-HHmmss), deci ordonarea
        # alfabetica descrescatoare le pune pe cele noi primele.
        Get-ChildItem -Path $configDir -Filter "$f.backup-*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -Skip 5 |
            ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
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
& py $pyFlag $paletteScript --once
if ($LASTEXITCODE -eq 0) {
    Ok "Paleta generata (vezi $configDir\palette.log)"
} else {
    Warn "Nu am putut genera paleta acum; ramane cea implicita."
}

# ---------- 7d. Controlul de dinainte ----------
# Ultima oprire inainte ca bara sa porneasca: versiunea YASB, fiecare lucru din interiorul lor pe
# care ne sprijinim, fiecare widget numit intr-o regula, fiecare culoare folosita in stiluri.
# Daca ceva nu se potriveste, instalarea se opreste aici si scrie ce anume, in loc sa pornesti o
# bara care pica. Daca trece, versiunea YASB de acum devine cea fixata.
Step "Verific totul inainte de pornire"
& py $pyFlag (Join-Path $here "tools\mint_doctor.py") --yasb $YasbPath --config $configDir --record-pin
if ($LASTEXITCODE -ne 0) {
    throw "Verificarea a gasit probleme (vezi lista de mai sus). Bara nu a fost pornita."
}

# ---------- 7c. HWiNFO64: temperatura CPU pentru bara ----------
# Intai ne uitam, fara Administrator: daca HWiNFO e instalat, setat cum trebuie si pornit,
# nu avem ce face si nu cerem acordul degeaba. Pana acum il opream, ii rescriam setarile si
# il porneam din nou la fiecare instalare, chiar cand totul era deja bine.
if (-not $NoHWiNFO) {
    Step "Verific HWiNFO64 (temperatura CPU)"
    $hw = Join-Path $here "tools\hwinfo_setup.ps1"
    $me = "$env:USERDOMAIN\$env:USERNAME"
    $extra = if ($ForceHWiNFO) { @("-Force") } else { @() }
    & $hw -CheckOnly
    $hwNeedsWork = ($LASTEXITCODE -ne 0) -or $ForceHWiNFO
    if (-not $hwNeedsWork) {
        Ok "HWiNFO e deja configurat; nu-l ating si nu cer Administrator"
    } else {
        Step "Configurez HWiNFO64 (senzori, Shared Memory, pornire la logare)"
        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        if ($isAdmin) {
            try { & $hw -ForUser $me @extra } catch { Warn "HWiNFO: $($_.Exception.Message)" }
        } else {
            Warn "Windows iti cere acordul de Administrator (HWiNFO sta in Program Files)."
            try {
                $argList = "-NoProfile -ExecutionPolicy Bypass -File `"$hw`" -ForUser `"$me`" $($extra -join ' ')"
                $p = Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList $argList
                if ($p.ExitCode -eq 0) { Ok "HWiNFO configurat" } else { Warn "Configurarea HWiNFO a esuat (cod $($p.ExitCode))." }
            } catch {
                Warn "Ai refuzat acordul de Administrator: HWiNFO ramane cum era (temperatura CPU poate lipsi)."
            }
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
        $sc.Arguments = "$pyFlag `"$main`""
        $sc.WorkingDirectory = Join-Path $YasbPath "src"
        $sc.Description = "YASB status bar"
        $sc.Save()
        Ok "Scurtatura creata in Startup"

        $lnk2 = Join-Path ([Environment]::GetFolderPath("Startup")) "YASB Palette.lnk"
        $sc2 = $shell.CreateShortcut($lnk2)
        $sc2.TargetPath = $pyw
        $sc2.Arguments = "$pyFlag `"$paletteScript`""
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
    Start-Process $pyw -ArgumentList $pyFlag, "`"$paletteScript`"" -WorkingDirectory $toolsDir
    Start-Process $pyw -ArgumentList $pyFlag, "`"$main`"" -WorkingDirectory (Join-Path $YasbPath "src")
} else {
    Start-Process py -ArgumentList $pyFlag, "`"$main`"" -WorkingDirectory (Join-Path $YasbPath "src")
}

Write-Host @"

Gata!
  - Bara porneste acum (si automat la fiecare logare).
  - Culorile se iau din wallpaper: schimba-l din Windows si bara se recoloreaza in ~3 secunde.
  - Vremea: click pe ea prima data si alege orasul.
  - Bulinele: una pentru fiecare desktop virtual (Win + Ctrl + D adauga unul).
  - Log, daca ceva nu merge:  $configDir\yasb.log  si  $configDir\palette.log
"@ -ForegroundColor Green
