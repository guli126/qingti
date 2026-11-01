@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo [1/3] 重新生成图标
if exist "tools\make_icon.py" (
  python tools\make_icon.py || goto :fail
)

echo [2/3] 清理旧产物
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 打包
set PYTHONUTF8=1
python -m PyInstaller --clean --noconfirm 轻提.spec || goto :fail

echo.
echo 完成：dist\轻提.exe
exit /b 0

:fail
echo.
echo 打包失败，看上面的报错。
exit /b 1
