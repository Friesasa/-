@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 请确认 input 文件夹里已经放入：
echo 1. 蒲公英导出的 Excel
echo 2. 旧刊例 Excel
echo.
py "%~dp0run_once.py"
echo.
echo 运行结束。按任意键关闭窗口。
pause >nul
