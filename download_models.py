"""
模型下载脚本 — 从 HuggingFace 下载所需的模型文件
运行前请确保已安装 huggingface_hub: pip install huggingface_hub
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def download_text2vec():
    """下载 text2vec 嵌入模型（用于记忆语义检索）"""
    dst = DATA / "text_models" / "text2vec-base-chinese"
    if dst.exists():
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
    """下载八重樱模型（TTS 权重 + Live2D 模型）"""
    from huggingface_hub import snapshot_download

    repo = "yuewu871/yae-sakura-models"

    # TTS 权重
    dst_tts = DATA / "TTS_models"
    if not (dst_tts / "GPT_weights_v2").exists() or not (dst_tts / "SoVITS_weights_v2").exists():
        print("下载 TTS 权重 (240M)...")
        snapshot_download(
            repo,
            local_dir=str(DATA),
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
            repo,
            local_dir=str(DATA),
            local_dir_use_symlinks=False,
            allow_patterns=["live2d/**"],
        )
        print("Live2D 模型下载完成")
    else:
        print("[跳过] Live2D 模型已存在")

    # 参考音频（TTS 克隆音色必需）
    dst_ref = DATA / "reference"
    if not dst_ref.exists():
        print("下载参考音频...")
        snapshot_download(
            repo,
            local_dir=str(DATA),
            local_dir_use_symlinks=False,
            allow_patterns=["reference/**"],
        )
        print("参考音频下载完成")
    else:
        print("[跳过] 参考音频已存在")


def main():
    need_hf = False
    if not (DATA / "text_models" / "text2vec-base-chinese").exists():
        need_hf = True
    if not (DATA / "TTS_models" / "GPT_weights_v2").exists():
        need_hf = True

    if need_hf:
        try:
            import huggingface_hub  # noqa: F401
        except ImportError:
            print("请先安装 huggingface_hub: pip install huggingface_hub")
            sys.exit(1)

    os.makedirs(DATA, exist_ok=True)
    download_text2vec()
    download_yae_models()

    print("\n全部模型下载完成。")


if __name__ == "__main__":
    main()
