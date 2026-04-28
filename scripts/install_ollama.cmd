@echo off
:: ============================================================================
:: install_ollama.cmd - Wrapper that runs install_ollama.ps1 with the right
:: PowerShell flags (NoProfile, ExecutionPolicy Bypass). Works from any shell
:: and from a double-click in Explorer; sidesteps the default Windows policy
:: that blocks unsigned .ps1 files.
::
:: Usage:
::   install_ollama.cmd               # default model: qwen3:4b
::   install_ollama.cmd qwen3:8b      # or pick a model
:: ============================================================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_ollama.ps1" %*
exit /b %ERRORLEVEL%
