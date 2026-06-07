"""
LLM 记忆提取器 — 从对话中提取重要信息，支持自动遗忘过时记忆
"""
import json
import logging
from openai import OpenAI

logger = logging.getLogger("Sakura-Extractor")

EXTRACT_PROMPT = """从对话中提取需要长期记住的新信息（最多3条），并判断以下已有记忆是否已过时。

已有记忆（仅参考，你需要判断其中哪些已不再有效）：
{existing}

新记忆格式: {{"type":"类型","importance":1-10,"content":"一句话","entities":["人物"]}}
类型: promise/preference/event/fact/insight

如果已有记忆中的约定已完成、事实已改变，在remove中列出要删除的关键词。

对话:
{conversation}

只输出JSON: {{"add":[...新记忆...],"remove":["旧记忆关键词"]}}"""


def extract_memories(api_key, base_url, model, user_msg, ai_response):
    conversation = f"旅人：{user_msg}\n八重樱：{ai_response}"

    # 语义检索相关活跃记忆，让 LLM 判断哪些已过时
    existing_text = ""
    try:
        from need.memory.vault import search_memories, get_all_memories
        # 只看活跃层（所有类型都可能过时，不只 promise/event）
        active = [m for m in get_all_memories()
                  if m.get("layer") != "archive"]
        if active:
            existing_text = "\n".join(f"- [{m.get('type','')}] {m.get('content','')}"
                                      for m in active[-20:])
    except ImportError:
        pass

    prompt = EXTRACT_PROMPT.format(existing=existing_text or "(无)", conversation=conversation)

    extract_model = model.replace("v4-pro", "v4-flash").replace("v2-pro", "v2-flash").replace("v2.5-pro", "v2-flash")
    extract_extra = {}
    if "mimo" in base_url:
        extract_extra = {"thinking": {"type": "disabled"}}

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        resp = client.chat.completions.create(
            model=extract_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.3,
            stream=False,
            extra_body=extract_extra if extract_extra else None,
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]

        result = json.loads(text)

        if isinstance(result, list):
            # 兼容旧格式: 直接是数组
            return [i for i in result if isinstance(i, dict) and i.get("content")], []
        if isinstance(result, dict):
            adds = result.get("add", [])
            removes = result.get("remove", [])
            if isinstance(adds, list):
                adds = [i for i in adds if isinstance(i, dict) and i.get("content")]
            if isinstance(removes, list):
                removes = [r for r in removes if isinstance(r, str)]
            return adds, removes

    except json.JSONDecodeError:
        try:
            text = text.strip()
            if text.endswith(","):
                text = text[:-1]
            if not text.endswith("]") and not text.endswith("}"):
                text += '"}]}' if '"add"' in text else '"}]'
            result = json.loads(text)
            if isinstance(result, dict):
                adds = result.get("add", [])
                removes = result.get("remove", [])
                return ([i for i in adds if isinstance(i, dict) and i.get("content")] if isinstance(adds, list) else [],
                        [r for r in removes if isinstance(r, str)] if isinstance(removes, list) else [])
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"记忆提取失败: {e}")

    return [], []
