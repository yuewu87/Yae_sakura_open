import os
import json

PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": [
            {"id": "deepseek-v4-flash", "name": "V4 Flash"},
            {"id": "deepseek-v4-flash", "name": "V4 Flash (思考)",
             "extra_body": {"reasoning_effort": "high"}},
            {"id": "deepseek-v4-pro", "name": "V4 Pro"},
            {"id": "deepseek-v4-pro", "name": "V4 Pro (思考)",
             "extra_body": {"reasoning_effort": "high"}},
        ],
    },
    "qwen": {
        "name": "阿里千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": [
            {"id": "qwen3.6-flash", "name": "Qwen3.6 Flash"},
            {"id": "qwen3.6-flash", "name": "Qwen3.6 Flash (思考)",
             "extra_body": {"enable_thinking": True}},
            {"id": "qwen3.6-plus", "name": "Qwen3.6 Plus"},
            {"id": "qwen3.6-plus", "name": "Qwen3.6 Plus (思考)",
             "extra_body": {"enable_thinking": True}},
            {"id": "qwen3.6-max-preview", "name": "Qwen3.6 Max"},
        ],
    },
    "mimo": {
        "name": "小米MiMo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": [
            {"id": "mimo-v2-flash", "name": "MiMo V2 Flash",
             "extra_body": {"thinking": {"type": "disabled"}}},
            {"id": "mimo-v2-flash", "name": "MiMo V2 Flash (思考)",
             "extra_body": {"thinking": {"type": "enabled"}}},
            {"id": "mimo-v2-pro", "name": "MiMo V2 Pro",
             "extra_body": {"thinking": {"type": "disabled"}}},
            {"id": "mimo-v2-pro", "name": "MiMo V2 Pro (思考)",
             "extra_body": {"thinking": {"type": "enabled"}}},
            {"id": "mimo-v2.5-pro", "name": "MiMo V2.5 Pro",
             "extra_body": {"thinking": {"type": "disabled"}}},
        ],
    },
}

VISION_MODELS = {
    "qwen3-vl-flash": {"name": "Qwen3 VL Flash", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    "qwen-vl-plus":   {"name": "Qwen VL Plus",   "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    "qwen-vl-max":    {"name": "Qwen VL Max",    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
}

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "assets", "api_config.json")
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")

# .env 变量名映射
ENV_KEY_NAMES = {
    "deepseek": "API_KEY_DEEPSEEK",
    "qwen": "API_KEY_QWEN",
    "mimo": "API_KEY_MIMO",
}


def load_env():
    """读取 .env 文件，返回 {provider_id: api_key}"""
    keys = {pid: "" for pid in PROVIDERS}
    if not os.path.exists(ENV_PATH):
        return keys
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                for pid, env_name in ENV_KEY_NAMES.items():
                    if k == env_name:
                        keys[pid] = v
    except Exception:
        pass
    return keys


def save_env_key(provider_id, api_key):
    """保存单个运营商的 API Key 到 .env 文件"""
    lines = []
    if os.path.exists(ENV_PATH):
        try:
            with open(ENV_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []
    else:
        lines = ["# API密钥 — 不要提交到git\n"]

    env_name = ENV_KEY_NAMES.get(provider_id)
    if not env_name:
        return

    # 更新或追加
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(env_name + "=") or stripped.startswith(env_name + " ="):
            lines[i] = f"{env_name}={api_key}\n"
            found = True
            break

    if not found:
        lines.append(f"{env_name}={api_key}\n")

    os.makedirs(os.path.dirname(ENV_PATH), exist_ok=True)
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def load_config():
    cfg = {
        "provider": "deepseek",
        "base_url": PROVIDERS["deepseek"]["base_url"],
        "model": PROVIDERS["deepseek"]["models"][0]["id"],
        "extra_body": {},
        "idle_timeout_minutes": 5,
        "vision_model": "qwen3-vl-flash",
        "vision_base_url": VISION_MODELS["qwen3-vl-flash"]["base_url"],
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg["provider"] = saved.get("provider", cfg["provider"])
            cfg["base_url"] = saved.get("base_url", cfg["base_url"])
            cfg["model"] = saved.get("model", cfg["model"])
            cfg["extra_body"] = saved.get("extra_body", cfg["extra_body"])
            cfg["idle_timeout_minutes"] = saved.get("idle_timeout_minutes", cfg["idle_timeout_minutes"])
            cfg["vision_model"] = saved.get("vision_model", cfg["vision_model"])
            cfg["vision_base_url"] = saved.get("vision_base_url", cfg["vision_base_url"])
            # 自动修复：MiMo 默认开启思考，非思考模式必须显式关闭
            if cfg.get("provider") == "mimo" and not cfg["extra_body"]:
                cfg["extra_body"] = {"thinking": {"type": "disabled"}}
        except Exception:
            pass
    return cfg


def save_config(config):
    """保存非敏感配置到 JSON（不含 api_keys）"""
    data = {
        "provider": config.get("provider", "deepseek"),
        "base_url": config.get("base_url", ""),
        "model": config.get("model", ""),
        "extra_body": config.get("extra_body", {}),
        "idle_timeout_minutes": config.get("idle_timeout_minutes", 5),
        "vision_model": config.get("vision_model", "qwen3-vl-flash"),
        "vision_base_url": config.get("vision_base_url", VISION_MODELS["qwen3-vl-flash"]["base_url"]),
    }
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
