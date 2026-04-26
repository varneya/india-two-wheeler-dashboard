@echo off
:: ============================================================================
:: install_backend.cmd - Wrapper that runs install_backend.ps1 with the right
:: PowerShell flags (NoProfile, ExecutionPolicy Bypass). Works from any shell
:: and from a double-click in Explorer; sidesteps the default Windows policy
:: that blocks unsigned .ps1 files.
::
:: Usage:
::   install_backend.cmd
:: ============================================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_backend.ps1" %*
exit /b %ERRORLEVEL%
