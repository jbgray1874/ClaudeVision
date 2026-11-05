@echo off
rem SDI SameDay watch - run every 15 minutes by the scheduled task "SDI SameDay Watch"
rem (deploy\Install-SameDay-Watch.ps1, from the laptop). Checks SameDay and emails SAMEDAY_ALERT_TO when something
rem is wrong. It reads only - nothing in SameDay is changed.
cd /d "%~dp0"
if not exist logs mkdir logs
".venv\Scripts\python.exe" sameday_watch.py --send >> logs\sameday_watch.log 2>&1
