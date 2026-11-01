@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 轻提

where python >nul 2>nul
if %errorlevel%==0 (
    python app.py
    goto done
)

where py >nul 2>nul
if %errorlevel%==0 (
    py app.py
    goto done
)

echo.
echo 没有找到 Python。请先安装 Python 3.10 或更新版本：
echo https://www.python.org/downloads/
echo 安装时记得勾选 "Add Python to PATH"。
echo.
pause

:done
