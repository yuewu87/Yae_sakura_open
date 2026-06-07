@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ================================================
echo   八重樱桌面助手 — 一键安装
echo ================================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)
echo Python 已就绪:
python --version
echo.

:: 安装 pip 依赖
echo [1/3] 安装 pip 依赖...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [警告] 依赖安装出错，请检查网络或手动执行 pip install -r requirements.txt
)
echo.

:: 下载模型和引擎
echo [2/3] 下载模型和引擎...
python download_models.py
if %errorlevel% neq 0 (
    echo [警告] 下载出错，请检查网络或手动执行 python download_models.py
)
echo.

:: 初始化 .env
echo [3/3] 初始化 .env...
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo 已创建 .env (从 .env.example 复制)
    ) else (
        echo [警告] 未找到 .env.example
    )
) else (
    echo [跳过] .env 已存在
)
echo.

echo ================================================
echo   安装完成
echo.
echo   下一步:
echo   1. 编辑 .env 填入 API Key
echo   2. pip install -r TTS_GPT_SoVITS\GPT_SoVITS\requirements.txt
echo   3. python 20_ui_第十七版_八重樱_沉浸界面.py
echo ================================================

pause
