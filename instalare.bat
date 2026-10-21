@echo off
rem ============================================================
rem  Mint Bar - instalare dintr-un singur dublu-click.
rem
rem  Scriptul adevarat e setup.ps1; asta doar il porneste cum trebuie, ca sa nu mai tii minte
rem  linia cu -ExecutionPolicy Bypass. Fereastra ramane deschisa la final, ca sa poti citi ce
rem  a iesit chiar daca ceva s-a oprit.
rem
rem  Se pot da aceleasi optiuni ca scriptului:
rem      instalare.bat -YasbRef main
rem      instalare.bat -NoHWiNFO
rem      instalare.bat -YasbPath "D:\dev\yasb"
rem ============================================================
setlocal

rem UTF-8, altfel cuvintele cu diacritice din setup.ps1 ies stricate in consola
chcp 65001 >nul 2>&1

pushd "%~dp0"

if not exist "setup.ps1" (
    echo.
    echo   Nu gasesc setup.ps1 langa fisierul asta.
    echo   Pune instalare.bat in acelasi folder cu setup.ps1 si incearca din nou.
    echo.
    popd
    pause
    exit /b 1
)

rem Instalarea nu are nevoie de Administrator. Daca o pornesti asa, tot ce scrie ea ajunge sa
rem apartina contului de administrator, iar bara pornita de utilizatorul tau nu mai poate scrie
rem in propriile fisiere. Singurul pas care chiar cere drepturi (HWiNFO) si le cere singur.
net session >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo.
    echo   Ai pornit instalarea ca Administrator. Nu e nevoie, si poate incurca:
    echo   fisierele ajung sa apartina altui cont decat cel care foloseste bara.
    echo.
    echo   Inchide fereastra si porneste instalare.bat cu dublu-click obisnuit.
    echo   Pasul cu HWiNFO isi cere singur drepturile, cand e nevoie.
    echo.
    popd
    pause
    exit /b 1
)

rem PowerShell 7 daca exista, altfel cel din Windows
set "PS=powershell"
where pwsh >nul 2>&1 && set "PS=pwsh"

echo.
echo   Instalez Mint Bar. Dureaza cateva minute.
echo.

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "CODE=%ERRORLEVEL%"

popd

echo.
if "%CODE%"=="0" (
    echo   Gata. Bara ar trebui sa fie pe ecran.
) else (
    echo   Instalarea s-a oprit ^(cod %CODE%^). Mesajul de mai sus spune de ce.
    echo   Daca a cazut la verificare, acolo scrie exact ce nu se potriveste.
)
echo.
pause
exit /b %CODE%
