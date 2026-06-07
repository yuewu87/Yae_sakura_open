@echo off
chcp 65001 >nul
cd /d E:\Study_Projects\yuewu_bachong\TTS_GPT_SoVITS
echo Starting TTS services...
echo.
D:\Conda_base\envs\gpt_sovits\python.exe start_servers.py
pause
