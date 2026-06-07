"""
聊天显示辅助 — WebView 消息渲染、流式更新、打字指示器
"""
import html
import logging
from datetime import datetime

logger = logging.getLogger("Sakura-Display")

# 滚动容器的 ID
CONTAINER_ID = "msgs"


class ChatDisplayHelper:

    TIME_GAP_MINUTES = 3  # 超过此间隔插入时间分隔条

    def __init__(self, chat_display):
        self.chat_display = chat_display
        self.message_count = 0
        self.current_streaming_message_id = None
        self.current_message_content = ""
        self._last_time = None

    def add_message(self, sender, message, is_user=False, is_streaming=False):
        now = datetime.now()

        # 时间分组：距上一条消息超过阈值时插入时间分隔条
        if self._last_time is not None:
            gap = (now - self._last_time).total_seconds() / 60
            if gap >= self.TIME_GAP_MINUTES:
                self._insert_time_divider(now)

        self._last_time = now
        self.message_count += 1
        message_id = f"msg-{self.message_count}"

        msg_type = "user-message" if is_user else "assistant-message"
        bubble = "user-bubble" if is_user else "assistant-bubble"
        name = "user-name" if is_user else "assistant-name"
        cursor = '<span class="cursor"></span>' if is_streaming else ''

        try:
            esc = html.escape(message).replace('\n', '<br>')
        except Exception:
            esc = html.escape(message[:50]).replace('\n', '<br>')

        js = f"""
            var c=document.getElementById('{CONTAINER_ID}');
            var d=document.createElement('div');
            d.className='message-container';
            d.id='{message_id}';
            d.innerHTML=`
                <div class="{msg_type}">
                    <div class="{name}">{sender}</div>
                    <div class="message-bubble {bubble}">
                        <div class="message-content" id="content-{message_id}">{esc}{cursor}</div>
                    </div>
                </div>
            `;
            c.appendChild(d);
            if(c.scrollTop+c.clientHeight>=c.scrollHeight-80)c.scrollTop=c.scrollHeight;
        """
        self._run_js(js)

        if is_streaming:
            self.current_streaming_message_id = message_id
            self.current_message_content = message

        return message_id

    def update_message(self, message_id, new_content, is_complete=False):
        try:
            esc = html.escape(new_content).replace('\n', '<br>')
        except Exception:
            esc = html.escape(new_content[:30]).replace('\n', '<br>')

        cursor = "" if is_complete else '<span class="cursor"></span>'

        js = f"""
            var e=document.getElementById('content-{message_id}');
            if(e)e.innerHTML=`{esc}{cursor}`;
            var c=document.getElementById('{CONTAINER_ID}');
            if(c)if(c.scrollTop+c.clientHeight>=c.scrollHeight-80)c.scrollTop=c.scrollHeight;
        """
        self._run_js(js)

    def complete_message(self, message_id, final_content):
        try:
            esc = html.escape(final_content).replace('\n', '<br>')
        except Exception:
            esc = html.escape(final_content[:30]).replace('\n', '<br>')

        js = f"""
            var e=document.getElementById('content-{message_id}');
            if(e)e.innerHTML=`{esc}`;
            var c=document.getElementById('{CONTAINER_ID}');
            if(c)if(c.scrollTop+c.clientHeight>=c.scrollHeight-80)c.scrollTop=c.scrollHeight;
        """
        self._run_js(js)
        self.current_streaming_message_id = None
        self.current_message_content = ""

    def show_typing_indicator(self):
        js = f"""
            document.getElementById('typing-indicator').style.display='block';
            var c=document.getElementById('{CONTAINER_ID}');
            if(c)if(c.scrollTop+c.clientHeight>=c.scrollHeight-80)c.scrollTop=c.scrollHeight;
        """
        self._run_js(js)

    def hide_typing_indicator(self):
        self._run_js("document.getElementById('typing-indicator').style.display='none';")

    def _insert_action_line(self, text):
        """插入动作描写独立行"""
        now = datetime.now()
        if self._last_time is not None:
            gap = (now - self._last_time).total_seconds() / 60
            if gap >= self.TIME_GAP_MINUTES:
                self._insert_time_divider(now)
        self._last_time = now

        try:
            esc = html.escape(text)
        except Exception:
            esc = html.escape(text[:50])
        js = f"""
            var c=document.getElementById('{CONTAINER_ID}');
            var d=document.createElement('div');
            d.className='action-line';
            d.innerHTML='<span>{esc}</span>';
            c.appendChild(d);
            if(c.scrollTop+c.clientHeight>=c.scrollHeight-80)c.scrollTop=c.scrollHeight;
        """
        self._run_js(js)

    def _insert_time_divider(self, dt):
        """插入时间分隔条"""
        time_str = dt.strftime("%H:%M")
        js = f"""
            var c=document.getElementById('{CONTAINER_ID}');
            var d=document.createElement('div');
            d.className='time-divider';
            d.innerHTML='<span>{time_str}</span>';
            c.appendChild(d);
            if(c.scrollTop+c.clientHeight>=c.scrollHeight-80)c.scrollTop=c.scrollHeight;
        """
        self._run_js(js)

    def _now(self):
        return datetime.now().strftime("%H:%M")

    def _run_js(self, code):
        try:
            self.chat_display.page().runJavaScript(code)
        except Exception as e:
            logger.error(f"JS错误: {e}")
