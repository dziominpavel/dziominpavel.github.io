@echo off
rem ? release-? ? (? ? release.ps1).
rem ? ? ? dist\ ? GitHub Release: ? vX.Y.Z ? ? version.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release.ps1" %*
exit /b %ERRORLEVEL%
