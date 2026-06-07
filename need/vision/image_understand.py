"""
视觉识图 — 调千问VL模型将图片转为文字描述
"""
import base64
import logging
from openai import OpenAI

logger = logging.getLogger("Sakura-Vision")

PROMPT = "请用中文简要描述这张图片的内容。如果在聊天对话场景中发来这张图，图中有什么值得注意的细节？限80字以内。"


def describe_image(api_key, image_path):
    """将图片转文字描述，返回字符串或None"""
    try:
        from need.api_config import load_config
        cfg = load_config()
        vl_model = cfg.get("vision_model", "qwen3-vl-flash")
        vl_url = cfg.get("vision_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")

        with open(image_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        ext = image_path.rsplit(".", 1)[-1].lower()
        mime = f"image/{ext}" if ext in ("jpg","jpeg","png","gif","webp") else "image/png"
        data_uri = f"data:{mime};base64,{img_data}"

        client = OpenAI(api_key=api_key, base_url=vl_url)
        resp = client.chat.completions.create(
            model=vl_model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": PROMPT},
                ]
            }],
            max_tokens=150,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"识图失败: {e}")
        return None
