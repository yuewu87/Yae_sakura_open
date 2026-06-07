"""
八重樱记忆管理器 — 三层记忆架构
  工作记忆：最近 N 轮完整对话
  摘要记忆：每 M 轮由 LLM 压缩为一条摘要
  用户画像：从对话中提取的持久事实
"""
import os
import json
import time
import re
import logging
from datetime import datetime

logger = logging.getLogger("Sakura-Memory")

WORKING_ROUNDS = 5       # 工作记忆保留轮数
COMPRESS_EVERY = 10      # 每 N 轮触发一次摘要压缩
MAX_SUMMARIES = 3         # 最多保留几条摘要
MAX_SUMMARY_CHARS = 200   # 每条摘要上限（中文字符）


class SimpleSakuraMemoryManager:

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key
        self.model = model

        # 角色设定
        self.character_context = self._load_character_context()

        # 三层记忆
        self.working_memory = []    # [{role, content, time}, ...]
        self.summaries = []         # [{id, rounds, summary, time}, ...]

        # 计数
        self.conversation_count = 0  # 待压缩轮数
        self.total_rounds = 0

        # 持久化文件
        self.memory_file = os.path.join(
            os.path.dirname(__file__), "..", "assets", "sakura_memory.json"
        )

        self._load()

    # ==================== 文件加载 ====================

    def _load_character_context(self):
        path = os.path.join(os.path.dirname(__file__), "..", "assets", "sakura_prompt.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return "你是八重樱，500年前八重村的巫女。"

    def _load(self):
        try:
            if os.path.exists(self.memory_file):
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.summaries = data.get("summaries", [])
                self.working_memory = data.get("working_memory", [])
                self.conversation_count = data.get("conversation_count", 0)
                self.total_rounds = data.get("total_rounds", 0)
                logger.info(f"记忆已加载：{self.total_rounds} 轮，{len(self.summaries)} 条摘要")
        except Exception as e:
            logger.warning(f"加载记忆失败: {e}")

    def _save(self):
        try:
            data = {
                "summaries": self.summaries,
                "working_memory": self.working_memory[-WORKING_ROUNDS * 2:],
                "conversation_count": self.conversation_count,
                "total_rounds": self.total_rounds,
                "save_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存记忆失败: {e}")

    # ==================== 公开接口 ====================

    def add_conversation(self, user_input, ai_response, reasoning_content=""):
        # 剥掉系统提示，不存入记忆
        import re
        clean_user = re.sub(r'[（(]当前时间[：:][^）)]*[）)]\s*', '', user_input)
        clean_user = re.sub(r'[（(]旅人[^）)]*[）)]\s*', '', clean_user)
        now = time.time()
        self.working_memory.append({"role": "user", "content": clean_user, "time": now})
        msg = {"role": "assistant", "content": ai_response, "time": now}
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        self.working_memory.append(msg)

        self.conversation_count += 1
        self.total_rounds += 1

        if self.conversation_count >= COMPRESS_EVERY:
            self._compress()
            # 每10轮触发一次自动降级
            try:
                from need.memory.vault import degrade_stale
                n = degrade_stale()
                if n:
                    logger.info(f"自动降级: {n} 条记忆 → archive")
            except ImportError:
                pass

        self._save()

    def get_message_history(self, for_api=False, include_memory=True):
        if not for_api:
            return self.working_memory

        # ---- 构建 system prompt ----
        parts = [self.character_context]

        # 历史摘要
        if include_memory and self.summaries:
            summary_text = self._format_summaries()
            if summary_text:
                parts.append(summary_text)

        system = "\n\n".join(parts)
        messages = [{"role": "system", "content": system}]

        # 最近 5 轮原文
        recent = self.working_memory[-WORKING_ROUNDS * 2:]
        for msg in recent:
            entry = {"role": msg["role"], "content": msg["content"]}
            if msg.get("reasoning_content"):
                entry["reasoning_content"] = msg["reasoning_content"]
            messages.append(entry)

        # 用户画像：从 vault 缓存提取（每轮必注入，缓存自动刷新）
        try:
            from need.memory.vault import get_user_profile
            profile = get_user_profile()
            if profile:
                lines = ["## 关于旅人（你记得的）"]
                for m in profile:
                    lines.append(f"- {m.get('content', '')}")
                messages.append({"role": "system", "content": "\n".join(lines)})
        except ImportError:
            pass

        # 从 vault 检索相关长期记忆
        try:
            from need.memory.vault import search_memories
            last_user = ""
            for m in reversed(recent):
                if m.get("role") == "user":
                    last_user = m.get("content", "")
                    break
            vault_mems = search_memories(last_user, top_k=5)
            if vault_mems:
                mem_lines = ["## 你之前记得的事情"]
                for m in vault_mems:
                    mem_lines.append(f"- [{m.get('type', '')}] {m.get('content', '')}")
                messages.append({"role": "system", "content": "\n".join(mem_lines)})
        except ImportError:
            pass

        return messages

    def get_formatted_entities(self):
        lines = ["🌸 **八重樱_记忆** 🌸\n"]
        try:
            from need.memory.vault import get_all_memories
            mems = get_all_memories()
            if mems:
                lines.append("## Vault 长期记忆")
                for m in mems:
                    lines.append(f"- [{m.get('type','')}] {m.get('content','')}")
        except ImportError:
            pass

        lines.append(f"\n---\n 共 {self.total_rounds} 轮对话")
        return "\n".join(lines)

    def clear_memory(self):
        self.working_memory = []
        self.summaries = []
        self.conversation_count = 0
        self.total_rounds = 0
        try:
            if os.path.exists(self.memory_file):
                os.remove(self.memory_file)
        except Exception:
            pass
        try:
            leave_file = os.path.join(os.path.dirname(__file__), "..", "..", "data", "last_leave.txt")
            if os.path.exists(leave_file):
                os.remove(leave_file)
        except Exception:
            pass
        logger.info("记忆已清空")
        self._save()

    def _format_summaries(self):
        if not self.summaries:
            return ""
        lines = ["## 过去的对话摘要\n"]
        for s in self.summaries[-MAX_SUMMARIES:]:
            lines.append(f"- {s['summary']}")
        return "\n".join(lines) + "\n"

    # ==================== LLM 压缩 ====================

    def _compress(self):
        """将最近 10 轮对话压缩为一条摘要"""
        rounds_start = self.total_rounds - self.conversation_count + 1
        rounds_end = self.total_rounds
        buffer = self.working_memory[-(COMPRESS_EVERY * 2):]  # 10 轮 = 20 条

        summary = self._generate_summary(buffer, rounds_start, rounds_end)
        if summary:
            self.summaries.append({
                "id": len(self.summaries) + 1,
                "rounds": f"{rounds_start}-{rounds_end}",
                "summary": summary,
                "time": time.time(),
            })
            self.summaries = self.summaries[-MAX_SUMMARIES:]
            self.conversation_count = 0
            logger.debug(f"压缩完成：{len(summary)} 字摘要")

    def _generate_summary(self, messages, start, end):
        if not self.api_key:
            return f"第{start}-{end}轮对话"

        try:
            from openai import OpenAI
            from need.api_config import load_config
            cfg = load_config()
            client = OpenAI(api_key=self.api_key, base_url=cfg.get("base_url", "https://api.deepseek.com"))

            dialog = "\n".join(
                f"{'旅人' if m['role'] == 'user' else '八重樱'}: {str(m['content'])[:200]}"
                for m in messages
            )

            prompt = (
                f"请用 60 字以内中文概括以下对话中关于【旅人】的关键信息"
                f"（ta说了什么、情绪如何、聊了什么话题），"
                f"不要包含八重樱说的话：\n\n{dialog}"
            )

            resp = client.chat.completions.create(
                model=self.model or "deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
                temperature=0.3,
            )
            summary = resp.choices[0].message.content.strip()
            return summary[:MAX_SUMMARY_CHARS]
        except Exception as e:
            logger.warning(f"摘要生成失败: {e}")
            return f"第{start}-{end}轮对话"


# ---- 单例 ----

_instance = None

def get_memory_manager(api_key=None, model=None):
    global _instance
    if _instance is None:
        _instance = SimpleSakuraMemoryManager(api_key=api_key, model=model)
    elif api_key and not _instance.api_key:
        _instance.api_key = api_key
        _instance.model = model or _instance.model
    return _instance
