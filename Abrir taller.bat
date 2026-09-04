@echo off
chcp 65001 >nul
title Taller de Sanlo.raw
cd /d "%~dp0"

rem Doble clic en este archivo y ya. Levanta el taller y abre el navegador
rem solo. Mientras esta ventana siga abierta, el taller funciona; al
rem cerrarla se para. Es normal que no se vea nada mas que este texto.

echo.
echo   Arrancando el taller de Sanlo.raw...
echo.

where python >nul 2>&1
if %errorlevel%==0 (
    python "taller\taller.py" 8123 --abrir
    goto fin
)

rem Algunas instalaciones de Python solo dejan el lanzador "py"
where py >nul 2>&1
if %errorlevel%==0 (
    py "taller\taller.py" 8123 --abrir
    goto fin
)

echo.
echo   No encuentro Python en este ordenador.
echo   Instalalo desde python.org, marcando "Add Python to PATH",
echo   y vuelve a hacer doble clic aqui.
echo.

:fin
echo.
echo   El taller se ha cerrado. Ya puedes cerrar esta ventana.
echo.
pause >nul
