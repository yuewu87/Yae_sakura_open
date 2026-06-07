"""
一键下载所有模型和依赖仓库
"""
import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def download_text2vec():
    """text2vec 嵌入模型 — 记忆语义检索"""
    dst = DATA / "text_models" / "text2vec-base-chinese"
    if (dst / "pytorch_model.bin").exists() or (dst / "model.safetensors").exists():
        print(f"[跳过] text2vec 已存在: {dst}")
        return

    print("下载 text2vec-base-chinese (422M)...")
    from huggingface_hub import snapshot_download
    snapshot_download(
        "shibing624/text2vec-base-chinese",
        local_dir=str(dst),
        local_dir_use_symlinks=False,
    )
    print("text2vec 下载完成")


def download_yae_models():
    """八重樱模型 — TTS 权重 + Live2D + 参考音频"""
    from huggingface_hub import snapshot_download
    repo = "yuewu871/yae-sakura-models"

    # TTS 权重
    dst_tts_gpt = DATA / "TTS_models" / "GPT_weights_v2"
    dst_tts_sovits = DATA / "TTS_models" / "SoVITS_weights_v2"
    if not dst_tts_gpt.exists() or not dst_tts_sovits.exists():
        print("下载 TTS 权重 (240M)...")
        snapshot_download(
            repo, local_dir=str(DATA),
            local_dir_use_symlinks=False,
            allow_patterns=["TTS/**"],
        )
        print("TTS 权重下载完成")
    else:
        print("[跳过] TTS 权重已存在")

    # Live2D 模型
    dst_l2d = DATA / "live2d_models" / "八重樱"
    if not dst_l2d.exists():
        print("下载 Live2D 八重樱模型 (8M)...")
        snapshot_download(
            repo, local_dir=str(DATA),
            local_dir_use_symlinks=False,
            allow_patterns=["live2d/**"],
        )
        print("Live2D 模型下载完成")
    else:
        print("[跳过] Live2D 模型已存在")

    # 参考音频
    dst_ref = DATA / "reference"
    if not dst_ref.exists():
        print("下载参考音频...")
        snapshot_download(
            repo, local_dir=str(DATA),
            local_dir_use_symlinks=False,
            allow_patterns=["reference/**"],
        )
        print("参考音频下载完成")
    else:
        print("[跳过] 参考音频已存在")


def download_gpt_sovits():
    """克隆 GPT-SoVITS 引擎"""
    dst = ROOT / "TTS_GPT_SoVITS" / "GPT_SoVITS"
    if dst.exists():
        print(f"[跳过] GPT-SoVITS 已存在: {dst}")
        return

    print("克隆 GPT-SoVITS (约 1GB, 请耐心等待)...")
    subprocess.run(
        ["git", "clone", "https://github.com/RVC-Boss/GPT-SoVITS.git", str(dst)],
        check=True,
    )
    print("GPT-SoVITS 克隆完成")
    print(f"请手动安装 GPT-SoVITS 依赖: pip install -r {dst / 'requirements.txt'}")


def check_huggingface_hub():
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        print("请先安装 huggingface_hub: pip install huggingface_hub")
        sys.exit(1)


def main():
    os.makedirs(DATA, exist_ok=True)

    need_hf = False
    if not (DATA / "text_models" / "text2vec-base-chinese").exists():
        need_hf = True
    if not (DATA / "TTS_models" / "GPT_weights_v2").exists():
        need_hf = True
    if need_hf:
        check_huggingface_hub()

    print("=" * 50)
    print("1/3 下载 text2vec 嵌入模型")
    print("=" * 50)
    download_text2vec()

    print("\n" + "=" * 50)
    print("2/3 下载八重樱模型 (TTS + Live2D + 参考音频)")
    print("=" * 50)
    download_yae_models()

    print("\n" + "=" * 50)
    print("3/3 克隆 GPT-SoVITS 引擎")
    print("=" * 50)
    download_gpt_sovits()

    print("\n全部下载完成。")


if __name__ == "__main__":
    main()
