"""
一键安装脚本 — 安装依赖 + 下载模型 + 初始化 .env
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent


def check_python():
    v = sys.version_info
    if v < (3, 10):
        print(f"需要 Python 3.10+，当前: {v.major}.{v.minor}")
        sys.exit(1)
    print(f"Python {v.major}.{v.minor}.{v.micro} — OK")


def install_requirements():
    req = ROOT / "requirements.txt"
    if not req.exists():
        print("未找到 requirements.txt，跳过")
        return
    print("安装 pip 依赖...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req)],
        check=True,
    )
    print("依赖安装完成")


def run_download():
    script = ROOT / "download_models.py"
    if not script.exists():
        print("未找到 download_models.py，跳过")
        return
    print("下载模型和引擎...")
    subprocess.run([sys.executable, str(script)], check=True)


def init_env():
    env_path = ROOT / ".env"
    example_path = ROOT / ".env.example"
    if env_path.exists():
        print(f"[跳过] .env 已存在")
        return
    if example_path.exists():
        shutil.copy(example_path, env_path)
        print(f"已创建 .env (从 .env.example 复制)")
        print("请编辑 .env 填入 API Key")
    else:
        print("未找到 .env.example，跳过")


def main():
    print("=" * 50)
    print("八重樱桌面助手 — 一键安装")
    print("=" * 50)

    os.chdir(ROOT)

    check_python()
    print()
    install_requirements()
    print()
    run_download()
    print()
    init_env()

    print()
    print("=" * 50)
    print("安装完成。")
    print()
    print("下一步:")
    print("  1. 编辑 .env 填入 API Key")
    print("  2. pip install -r TTS_GPT_SoVITS/GPT_SoVITS/requirements.txt")
    print("  3. python 20_ui_第十七版_八重樱_沉浸界面.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
