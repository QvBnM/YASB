# Mint Bar v2

Tot ce era în revizie, făcut: reparațiile de CSS și config, plus cele șapte idei noi.
Merge peste YASB 2.0.8 rulat din sursă (acolo unde stau deja widget-urile tale).

## Instalare

```powershell
cd mint-bar
python tools\mint_install.py --yasb C:\cale\catre\yasb --dry-run   # vezi ce s-ar schimba
python tools\mint_install.py --yasb C:\cale\catre\yasb             # instalează
```

Scriptul:

1. copiază widget-urile noi în `src/core/widgets/yasb/` și schemele lor în `src/core/validation/widgets/yasb/`;
2. adaugă comenzile barei în lansatorul YASB (trei rânduri, în locurile descrise de YASB în `providers/example.py`; originalele rămân ca `.mint-bak`);
3. pune `config.yaml` și `styles.css` în `~/.config/yasb`, cu copie de rezervă. `palette.css` nu e atins.

Rulat de două ori nu dublează nimic.

## De completat în config.yaml

| Unde | Ce |
|---|---|
| `modes` → `game` → `processes` | exe-urile jocurilor tale (am pus exemple) |
| `git_branch` → `roots` | folderele în care ții proiectele |
| `wallpaper` → `image_path`, `run_after` | folderul cu imagini și calea reală spre `yasb_palette.py` |
| `launcher` → `keybindings` | `alt+space` se bate cap în cap cu PowerToys Run, dacă îl folosești |
| `progress` → `qbittorrent` | `enabled: true` dacă vrei download-urile pe linia de jos |

În `yasb_palette.py` adaugă `--warn` (galbenul pentru valori peste prag), cu aceeași verificare de contrast ca `--accent`.
Până atunci, `styles.css` are o valoare de rezervă.

## Înainte să pornească bara

Instalarea nu mai pleacă de pe ultima versiune YASB. Rămâne pe commit-ul pe care bara chiar a mers,
scris în `tools/yasb-pin.txt`. Widget-urile noastre se sprijină pe lucruri din interiorul YASB, iar
o schimbare la ei ar putea opri bara într-o dimineață, fără să fi atins tu nimic.

```powershell
.\setup.ps1                      # rămâne pe versiunea fixată
.\setup.ps1 -YasbRef main        # trece conștient pe alta; dacă verificarea trece, se fixează pe ea
```

La final, înainte de pornire, rulează controlul:

```powershell
py -3.14 tools\mint_doctor.py --yasb C:\cale\catre\yasb
```

Verifică versiunea YASB, fiecare lucru din interiorul lor pe care ne sprijinim (citind codul, fără
să-l pornească), fiecare widget numit într-o regulă din `config.yaml`, fiecare opțiune prin schema
ei, și fiecare culoare din `styles.css`. Iese cu 1 dacă ceva ar strica bara, iar `setup.ps1` se
oprește acolo și scrie ce anume.

## Teste

```powershell
py -3.14 tests\run.py            # toate
py -3.14 tests\run.py layout     # doar un fișier
```

112 verificări, fără Windows, fără PyQt6 și fără pytest: `tests/stubs.py` pune module înlocuitoare
pentru Qt și pentru modulele YASB, ca logica barei să ruleze neschimbată. Rulează singure la fiecare
modificare (`.github/workflows/tests.yml`). Ce NU acoperă: desenarea propriu-zisă și apelurile către
Windows și COM.

## Ce face fiecare piesă

**Reparații (styles.css, config.yaml)**
- Microfonul și volumul pe mut se văd (roșu), în loc de negru pe gri.
- Stările stau într-o singură capsulă neutră; culoarea apare doar pentru stare.
- Volumul apare o singură dată; testul de viteză a ieșit din bară (e în popup-ul de rețea).
- Unitățile (%, °C) sunt mici și gri, lângă cifră.
- Ora mentă, data gri, ca două widget-uri lipite (ceasul YASB nu formatează data în span-uri).

**Widget-uri noi**

| Widget | Fișier | Ce face |
|---|---|---|
| `modes` | `context_mode.py` | Moduri automate: lucru (VS Code), joc, apel. Ascunde/arată widget-uri și pune `mode-*` pe bară |
| `thresholds` | `mint_thresholds.py` | Cifrele trec în galben/roșu peste prag, fără să clipească |
| `fps` | `rtss_fps.py` | FPS din RivaTuner (memoria partajată, ca la HWiNFO) |
| `latency` | `latency.py` | Ping cu API-ul ICMP din Windows, pe fir separat |
| `git_branch` | `git_branch.py` | Branch, ↑↓ și fișiere modificate pentru proiectul din VS Code |
| `call_status` | `call_status.py` | „În apel 12:04” cât timp o aplicație folosește microfonul |
| `focus` | pomodoro din YASB | Sesiune de focus, stilizată ca restul barei |
| `progress` | `progress_line.py` | Linia de jos: melodie, focus, download-uri |
| `notif` | `bar_notifications.py` | Notificările apar în bară, în locul titlului ferestrei |
| `launcher` | quick_launch din YASB + `bar_commands.py` | Aplicații, calcule și comenzile barei din tastatură |
| `wallpaper` | `wallpaper_palette.py` | Galerie cu paleta estimată pentru fiecare imagine |
| `cover_accent` | `cover_accent.py` | Grupul media și desktop-urile iau culoarea copertei |
| `desktops` | `desktops_plus.py` | Desktop-uri goale = cercuri; hover = ce e pe fiecare |
| `ui_ro` | `ui_polish.py` | Popup-urile YASB în română; calendar cu weekend, zile stinse, sărbători întregi |

Prima dată când vine o notificare, Windows îți cere acordul pentru citirea lor.

## Ce am verificat și ce nu

Am rulat totul pe Python 3.14 cu codul YASB 2.0.8: toate opțiunile din `config.yaml` trec prin schemele YASB,
`styles.css` trece prin procesorul CSS al YASB fără variabile nerezolvate, iar 84 de verificări acoperă
modurile, pragurile, linia de progres, notificările, traducerile, comenzile din lansator și calculele de culoare.

Nu am putut rula pe Windows. Părțile care depind direct de Windows (RivaTuner, ping ICMP, registrul pentru
microfon, citirea notificărilor, desktop-urile virtuale) sunt scrise după API-urile documentate, dar le vezi
prima dată tu. Dacă ceva nu pornește, `yasb.log` spune ce widget și de ce.

## Ce cere codul tău

Astea țin de widget-urile scrise de tine și le fac când îmi trimiți fișierele:

- Bluetooth: „Asociază” pentru dispozitive noi, bateria căștilor, numele lung tăiat cu „…”.
- Testul de viteză: eroare explicată în română, ultimul rezultat bun păstrat.
- Popup-ul de rețea: Wi-Fi și Bluetooth lipsă strânse într-un rând.
- `hwinfo_sensor`: unitatea „°C” mică, ca la restul.

O corectură la revizie: mâna și „morișca” din capturile Wi-Fi/Bluetooth sunt aproape sigur de la programul care
a randat previzualizarea, nu de la Windows. Pe Windows 11, Segoe Fluent Icons are glifele corecte, așa că
n-am schimbat fontul iconițelor.
