"""
LLM API 调用线程 — 支持流式输出和记忆系统
"""
from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI

# 延迟导入，避免循环依赖
LANGCHAIN_AVAILABLE = False
try:
    from need.memory.manager import get_memory_manager
    LANGCHAIN_AVAILABLE = True
except ImportError:
    pass


class ChatThread(QThread):
    chunk_received = pyqtSignal(str)
    response_complete = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, api_key, base_url, model, user_input, use_memory=False, extra_body=None, memory_paused=False):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.user_input = user_input
        self.use_memory = use_memory
        self.extra_body = extra_body or {}
        self.memory_paused = memory_paused

    def run(self):
        try:
            if self.use_memory and LANGCHAIN_AVAILABLE:
                self._run_with_memory()
            else:
                self._run_direct()
        except Exception as e:
            self.error_occurred.emit(f"对话错误: {str(e)[:200]}")

    def _run_direct(self):
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        messages = [{"role": "user", "content": self.user_input}]
        self._stream(client, messages)

    def _run_with_memory(self):
        memory_manager = get_memory_manager()
        if not memory_manager:
            self.error_occurred.emit("记忆管理器未初始化")
            return

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        messages = memory_manager.get_message_history(for_api=True, include_memory=True)

        # 知识库检索：将相关知识作为 system prompt 注入
        try:
            from need.knowledge.retriever import retrieve
            knowledge = retrieve(self.user_input)
            if knowledge:
                messages.append({"role": "system", "content": knowledge})
        except ImportError:
            pass

        messages.append({"role": "user", "content": self.user_input})

        self._stream(client, messages)

        # 将对话存入记忆（暂停时跳过）
        if hasattr(self, '_full_response') and not self.memory_paused:
            rc = getattr(self, '_reasoning_content', '')
            memory_manager.add_conversation(self.user_input, self._full_response, reasoning_content=rc)

            # LLM 提取长期记忆到 vault（失败不影响主流程）
            try:
                from need.memory.extractor import extract_memories
                from need.memory.vault import add_memory
                # 剥掉系统提示，但保留图片描述
                import re
                img_desc = ""
                m = re.search(r'[（(]旅人发来一张图片，内容是：[^）)]*[）)]', self.user_input)
                if m:
                    img_desc = m.group()
                clean_input = re.sub(r'[（(]当前时间[：:][^）)]*[）)]\s*', '', self.user_input)
                clean_input = re.sub(r'[（(]旅人[^）)]*[）)]\s*', '', clean_input)
                if img_desc:
                    clean_input = f"{img_desc}\n{clean_input}"
                items, removes = extract_memories(
                    self.api_key, self.base_url, self.model,
                    clean_input, self._full_response
                )
                count = 0
                for item in items:
                    mem_type = item.get("type", "fact")
                    imp = item.get("importance", 5)
                    content = item.get("content", "")
                    add_memory(mem_type=mem_type, content=content,
                               importance=imp, entities=item.get("entities", []))
                    # 高重要度事实/偏好 → 自动升 core
                    if imp >= 9 and mem_type in ("fact", "preference"):
                        from need.memory.vault import set_layer
                        set_layer(content[:20], "core")
                    count += 1
                if removes:
                    from need.memory.vault import archive_memories
                    del_count = archive_memories(removes)
                else:
                    del_count = 0
                import logging
                if count > 0 or del_count > 0:
                    logging.getLogger("Sakura-Thread").info(
                        f"Vault: +{count} -{del_count}条")
                else:
                    logging.getLogger("Sakura-Thread").info("Vault: 无新记忆")
            except Exception as e:
                import logging
                logging.getLogger("Sakura-Thread").warning(f"Vault提取失败: {e}")

    def _stream(self, client, messages):
        stream = client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            extra_body=self.extra_body if self.extra_body else None,
        )

        full_response = ""
        reasoning_content = ""
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content is not None:
                full_response += delta.content
                self.chunk_received.emit(delta.content)
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content is not None:
                reasoning_content += delta.reasoning_content

        # 思考模型偶尔只输出 reasoning 忘了 content，兜底用最后一段 reasoning
        if not full_response.strip() and reasoning_content.strip():
            full_response = "（思考了太久，忘了开口说话……）"
        self._full_response = full_response
        self._reasoning_content = reasoning_content
        self.response_complete.emit(full_response)
