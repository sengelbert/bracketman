@echo off
setlocal enabledelayedexpansion

:: Force UTF-8 encoding in Windows console
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

title Bracketman - Wrestling Tournament Manager

cd /d "%~dp0"

echo ========================================================
echo   Bracketman - Wrestling Tournament Manager (Localhost)
echo ========================================================
echo.

:: Check if virtual environment exists
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Virtual environment not found. Setting up first-time installation...
    echo.
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        where py >nul 2>nul
        if %errorlevel% neq 0 (
            echo [ERROR] Python 3 was not found on your system!
            echo Please install Python 3.10 or higher from https://www.python.org/
            echo Make sure to check "Add Python to PATH" during installation.
            echo.
            pause
            exit /b 1
        ) else (
            set "PY_CMD=py -3"
        )
    ) else (
        set "PY_CMD=python"
    )

    echo [1/3] Creating virtual environment...
    !PY_CMD! -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )

    echo [2/3] Installing dependencies...
    .venv\Scripts\python.exe -m pip install --upgrade pip setuptools
    .venv\Scripts\pip.exe install -e ".[dev]"
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )

    echo [3/3] Preparing example tournament...
    if not exist "data\example_tournament.xlsx" (
        .venv\Scripts\python.exe scripts\generate_example_tournament.py
    )
    echo.
    echo [SUCCESS] First-time setup complete!
    echo.
)

echo Starting Bracketman on http://localhost:8503 ...
echo (Keep this terminal window open while using Bracketman)
echo.

:: Launch Bracketman UI
.venv\Scripts\python.exe -m bracketman ui

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Bracketman exited with an error code: %errorlevel%
    pause
)
