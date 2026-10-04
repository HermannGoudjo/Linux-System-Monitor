@echo off
REM Lance l'application depuis le dossier où se trouve ce fichier.
cd /d "%~dp0"
call "venv\Scripts\activate.bat"
waitress-serve --listen=127.0.0.1:8000 app:app
