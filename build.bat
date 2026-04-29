@echo off
REM DataInsight 构建脚本
REM 用于打包 Windows 可执行文件

echo ========================================
echo DataInsight Build Script
echo ========================================

echo.
echo [1/3] Checking dependencies...
pip install -r requirements.txt

echo.
echo [2/3] Running code checks...
python -m flake8 --exclude=build,dist,venv .

echo.
echo [3/3] Building executable...
pyinstaller build.spec --clean

echo.
echo ========================================
echo Build completed!
echo Output: dist\DataInsight.exe
echo ========================================
pause
