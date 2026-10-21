# YASB – tema mea (pentru feedback)

Bară de stare pentru Windows făcută cu [YASB](https://github.com/amnweb/yasb), în stil „Linux rice”:
o singură bară continuă sus, font JetBrainsMono Nerd Font, culori luate automat din wallpaper.

## Fișiere
- **config.yaml** – ce widget-uri sunt în bară și ce face fiecare la click / click dreapta.
- **styles.css** – tot aspectul (spațieri, mărimi, separatoare, popup-uri). Folosește doar variabile de culoare.
- **palette.css** – culorile. Se rescrie automat la fiecare schimbare de wallpaper (pywal + verificare de contrast),
  deci aici e doar un exemplu (paleta implicită „Fuji”: verde-mentă pe fundal închis).
- **preview/** – cum arată câteva popup-uri (randate cu stilurile de mai sus).

## Structura barei (34px, de la o margine la alta)
- **Stânga:** lansator · notificări · desktop-uri virtuale · media (control, copertă, vizualizator, volum) · branch git (în modul lucru) · titlul ferestrei active
- **Centru:** ora și data (mereu la mijloc), click = calendar; lângă ele, doar când e cazul: focus, apel în curs
- **Dreapta:** vremea · FPS (joc) · CPU + temperatură · GPU · RAM · VRAM · ping (joc) · trafic · systray · wallpaper · capsula de stări (limbă, microfon, rețea, Bluetooth, volum, baterie)
- **Invizibile:** moduri automate, praguri de culoare, linia de progres, accent din copertă, traduceri

## Reguli de design pe care le-am urmat
- Separatoare (`|`) doar între categorii, nu între date de același fel.
- Numerele au lățime fixă (font monospace + padding), ca să nu „sară” bara când se schimbă valorile.
- Contrast minim garantat pentru text oricare ar fi wallpaper-ul.
- Bara dispare în jocuri / fullscreen.
- Culoarea înseamnă stare: microfon mut, Bluetooth conectat, valori peste prag.
- Bara își schimbă conținutul după ce faci (lucru / joc / apel).

Notă: widget-urile `audio_orbit`, `audio_slider`, `hwinfo_sensor`, `net_status`, `active_title`,
`media_visualizer`, `window_fix` sunt scrise de mine, nu există în YASB-ul oficial.
