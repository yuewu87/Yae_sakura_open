"""
八重樱角色扮演程序 - 沉浸式界面
第十七版：统一 HTML 页面 + Flexbox 布局，解决 Windows QWebEngineView 透明问题
"""
import sys, io, os, warnings, logging, re, random, subprocess, socket, threading, numpy as np
import time
from datetime import datetime

if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="jieba")

from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout,
                             QLabel, QPushButton, QWidget, QDialog,
                             QTextEdit, QFrame, QHBoxLayout, QLineEdit,
                             QComboBox, QSpinBox, QFileDialog, QTabWidget)
from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings
from PyQt5.QtMultimedia import QMediaPlayer


from need.api_config import load_config, save_config, load_env, save_env_key, PROVIDERS

LIVE2D_AVAILABLE = False
try:
    from need.live2d.manager import Live2DWidget
    LIVE2D_AVAILABLE = True
except ImportError: pass

LANGCHAIN_AVAILABLE = False
try:
    from need.memory.manager import get_memory_manager
    LANGCHAIN_AVAILABLE = True
except ImportError: pass

TTS_AVAILABLE = False
try:
    from need.tts.manager import TTSManager
    TTS_AVAILABLE = True
except ImportError: pass

VISION_AVAILABLE = False
try:
    from need.vision.manager import VisionManager
    VISION_AVAILABLE = True
except ImportError: pass

from need.chat.thread import ChatThread
from need.chat.display import ChatDisplayHelper
from need.memory.dialog import MemoryDialog

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Sakura-UI")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("TTS-WebSocket-Server").setLevel(logging.WARNING)
logging.getLogger("TTS-Client").setLevel(logging.WARNING)
logging.getLogger("TTS-Inferencer").setLevel(logging.WARNING)
logging.getLogger("Sakura-TTS").setLevel(logging.WARNING)

IDLE_TIMEOUT_MS = 5 * 60 * 1000  # 默认值，被 api_config.json 覆盖
AUTO_MSGS = [
    "（你许久未开口了。向旅人说些什么吧。）",
    "（已是沉默良久……你轻轻开口。）",
]
RETURN_MSGS = [
    "（旅人回来了。你抬起头，微笑着迎接ta。）",
    "（旅人回到了圣痕空间。你问候ta。）",
]

BG_COLOR = "#181b3a"
BG_IMG = "E:/Study_Projects/yuewu_bachong/data/img/img_02.png".replace("\\", "/")


class CameraWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("摄像头预览"); self.setMinimumSize(340, 280)
        self.setStyleSheet("background:#1a1a2e;")
        l = QVBoxLayout(self); l.setContentsMargins(0, 0, 0, 0)
        self.lb = QLabel(); self.lb.setAlignment(Qt.AlignCenter)
        self.lb.setStyleSheet("border:none;background:#1a1a2e;"); l.addWidget(self.lb)

    def set_frame(self, frame):
        # 与 v15 完全一致的实现
        try:
            rgb = np.ascontiguousarray(frame[..., ::-1])
            h, w = rgb.shape[:2]
            qimg = QImage(rgb.tobytes(), w, h, QImage.Format_RGB888)
            scaled = qimg.scaled(
                self.lb.width(), self.lb.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.lb.setPixmap(QPixmap.fromImage(scaled))
        except Exception:
            pass

    def closeEvent(self, e): self.hide(); e.ignore()


def scan_live2d_model(model_dir):
    prefer = "八重樱"
    found = []
    try:
        for item in os.listdir(model_dir):
            item_path = os.path.join(model_dir, item)
            if os.path.isdir(item_path):
                for f in os.listdir(item_path):
                    if f.endswith('.model3.json'):
                        found.append((item, os.path.join(item_path, f)))
                        break
    except Exception as e:
        logger.warning(f"Live2D模型扫描失败: {e}")
        return ""
    if not found:
        return ""
    for name, path in found:
        if name == prefer:
            return "file:///" + path.replace("\\", "/")
    name, path = found[0]
    return "file:///" + path.replace("\\", "/")


class _StatusProxy:
    """让 TTSManager 的 setText 自动注入 JS 到 HTML 状态栏"""
    def __init__(self, view):
        self._view = view

    def setText(self, text):
        try:
            esc = text.replace("\\", "\\\\").replace("'", "\\'")
            self._view.page().runJavaScript(
                f"(function(){{var e=document.getElementById('status-text');if(e)e.textContent='{esc}';}})();")
        except: pass


class SakuraWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        api_cfg = load_config()
        api_keys = load_env()
        self.api_key = api_keys.get(api_cfg.get("provider", "deepseek"), "")
        self.url = api_cfg.get("base_url", "")
        self.model = api_cfg.get("model", "")
        self.api_extra_body = api_cfg.get("extra_body", {})
        self.l2d_dir = "E:/Study_Projects/yuewu_bachong/data/live2d_models"
        self.libs_dir = "E:/Study_Projects/yuewu_bachong/need/assets/libs".replace("\\", "/")

        self.memory_manager = None
        if LANGCHAIN_AVAILABLE:
            try:
                self.memory_manager = get_memory_manager(self.api_key, self.model)
            except: pass

        self.chat_thread = None; self.is_waiting_response = False
        self._user_expression = "平静"
        self._buf = ""
        self._actions_displayed = 0
        self._has_chatted = False
        self._bg_show = True  # 默认显示图片背景
        self._memory_paused = False
        self._maximized = False
        self._normal_geo = None
        self._idle_timeout_ms = api_cfg.get("idle_timeout_minutes", 5) * 60 * 1000

        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._on_idle_timeout); self._idle_timer.setSingleShot(True)

        self.setWindowTitle("八重樱·圣痕之庭")
        self.setGeometry(100, 50, 1500, 840)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self._init_ui()

        # 轮询 JS 变量（替代 QWebChannel）
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_action)
        self._poll_timer.start(60)

        self.display = ChatDisplayHelper(self.view)
        self.memory_dialog = MemoryDialog(self, self.memory_manager)

        # 状态代理 — 让 TTSManager 更新 HTML #status-text
        status_proxy = _StatusProxy(self.view)

        self._llm_logs = []  # [{user, raw_response}]
        self._current_raw_response = ""
        self._tts_server_logs = []  # 服务端日志
        self._tts_log_window = None  # 日志窗口引用(非模态)
        self._tts_running = False
        self._tts_server_process = None
        self.tts_manager = None
        self._status_proxy = status_proxy

        self._vision_running = False
        if VISION_AVAILABLE:
            self.vision_manager = VisionManager(check_interval=10.0, debounce_frames=30, preview_fps=10)
            self.vision_manager.user_arrived.connect(self._on_user_arrived)
            self.vision_manager.user_left.connect(self._on_user_left)
            self.vision_manager.frame_captured.connect(self._on_frame_captured)
            self.vision_manager.expression_changed.connect(self._on_expression_changed)
        else:
            self.vision_manager = None
        self.camera_window = CameraWindow() if VISION_AVAILABLE else None

        # 预加载知识库
        try:
            from need.knowledge.retriever import retrieve
            retrieve("")
        except Exception:
            pass

        self._start_idle_timer()

        # 首次使用引导：无 API Key 时自动弹出配置窗口
        api_keys = load_env()
        if not any(api_keys.values()):
            QTimer.singleShot(800, self._show_api_config)

    # ======================= 轮询（JS → Python）=======================

    def _poll_action(self):
        self.view.page().runJavaScript(
            "var v=window._sakura_action||'';window._sakura_action='';v",
            self._on_poll_result
        )

    def _on_poll_result(self, value):
        if not value:
            return
        if ":" in value:
            action, param = value.split(":", 1)
        else:
            action, param = value, ""
        if action == "send":
            self._user_input_from_html(param)
        elif action == "tts_svr_toggle":
            self._tts_svr_toggle()
        elif action == "tts_log_win":
            self._show_tts_log_window()
        elif action == "llm_log":
            self._show_llm_log()
        elif action == "mem_pause":
            self._toggle_memory_pause()
        elif action == "settings":
            self._show_settings()
        elif action == "img":
            self._select_image()
        elif action == "tts_cli_toggle":
            self._tts_cli_toggle()
        elif action == "vision":
            self._toggle_vision()
        elif action == "camera":
            self._toggle_camera_window()
        elif action == "memory":
            self.memory_dialog.show()
        elif action == "close":
            self.close()
        elif action == "live2d":
            self._show_live2d_window()
        elif action == "bg":
            self._toggle_bg()
        elif action == "api_config":
            self._show_api_config()
        elif action == "drag":
            if self.windowHandle():
                self.windowHandle().startSystemMove()
        elif action == "min":
            self.showMinimized()
        elif action == "max":
            from PyQt5.QtWidgets import QApplication
            screen = self.screen() or QApplication.primaryScreen()
            if screen:
                if self._maximized:
                    self._maximized = False
                    self.setGeometry(self._normal_geo)
                else:
                    self._normal_geo = self.geometry()
                    self._maximized = True
                    self.setGeometry(screen.geometry())

    # ======================= UI =======================

    def _init_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        cw.setStyleSheet(f"background:{BG_COLOR};")

        self.view = QWebEngineView(cw)
        self.view.setGeometry(0, 0, self.width(), self.height())
        self.view.setStyleSheet("background:transparent;")
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.page().settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessFileUrls, True)

        model_url = scan_live2d_model(self.l2d_dir) if LIVE2D_AVAILABLE else ""
        if model_url:
            logger.info("Live2D模型已就绪")
        else:
            logger.warning("Live2D模型未找到")
        html = self._build_html(model_url)
        self.view.setHtml(html, QUrl("file:///"))

    def _build_html(self, model_url):
        libs = self.libs_dir
        v_tts = """<button class="side-btn" onclick="showTtsPanel()">语音系统</button>"""
        v_vision = """<button class="side-btn" onclick="showVisPanel()">视觉系统</button>"""
        v_mem = """<button class="side-btn" onclick="doAction('memory')">记忆系统</button>"""
        tts_btn = v_tts if TTS_AVAILABLE else ""
        vis_btn = v_vision if VISION_AVAILABLE else ""
        mem_btn = v_mem if LANGCHAIN_AVAILABLE else ""
        vis_txt = ""
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><style>
            *{{margin:0;padding:0;box-sizing:border-box;user-select:none;-webkit-user-select:none;}}
            html,body{{width:100%;height:100%;overflow:hidden;
                font-family:'Microsoft YaHei',sans-serif;
                background:transparent;color:#ddd;
                padding-top:20px;}}
            input,textarea{{user-select:text;-webkit-user-select:text;}}
            button:focus,button:focus-visible{{outline:none;}}

            body.gradient-bg{{background:linear-gradient(135deg,#0d1b2a 0%,#1b0a2e 50%,#162040 100%);}}
            body.gradient-bg #bg-img,body.gradient-bg #bg-overlay{{display:none;}}

            #bg-img{{position:fixed;top:0;left:0;width:100%;height:100%;
                object-fit:cover;z-index:-2;opacity:0.9;}}

            #bg-overlay{{position:fixed;top:0;left:0;width:100%;height:100%;
                z-index:-1;pointer-events:none;
                background:linear-gradient(135deg,rgba(13,27,42,0.55) 0%,rgba(27,10,46,0.55) 50%,rgba(22,32,64,0.55) 100%);}}

            /* 欢迎覆盖层 */
            #welcome-overlay{{position:fixed;top:0;left:0;width:100%;height:100%;
                display:flex;align-items:center;justify-content:center;
                z-index:100;pointer-events:none;
                animation:welcomeFade 2.8s ease-in-out forwards;}}
            #welcome-overlay>div{{
                color:rgba(255,255,255,.85);background:rgba(0,0,0,.4);
                border-radius:16px;padding:18px 36px;font-size:24px;font-weight:bold;}}
            @keyframes welcomeFade{{
                0%{{opacity:0;}} 12%{{opacity:1;}} 70%{{opacity:1;}} 100%{{opacity:0;}}}}

            #main{{display:flex;width:100%;height:100%;}}
            #l2d{{flex:1;display:flex;align-items:center;justify-content:center;
                position:relative;min-width:400px;}}
            #l2d canvas{{position:absolute;left:0;top:0;}}

            #right{{width:540px;display:flex;flex-direction:column;padding:20px 20px 20px 0;}}
            .card{{flex:1;display:flex;flex-direction:column;
                background:rgba(13,26,38,0.5);
                border-radius:16px;border:1px solid rgba(255,255,255,0.08);
                transform:perspective(1000px) rotateY(-8deg);
                box-shadow:0 4px 30px rgba(0,0,0,0.4);overflow:hidden;}}

            #msgs{{flex:1;overflow-y:auto;padding:14px 12px;
                scrollbar-width:none;-ms-overflow-style:none;}}
            #msgs::-webkit-scrollbar{{display:none;}}

            /* 动作描写行 */
            .action-line{{display:flex;align-items:center;gap:12px;margin:10px 20px;}}
            .action-line::before,.action-line::after{{
                content:'';flex:1;height:1px;
                background:linear-gradient(to right,transparent,rgba(255,180,200,.25),transparent);}}
            .action-line span{{font-size:15px;color:rgba(255,200,210,.55);
                font-style:italic;white-space:pre-wrap;}}

            /* 时间分隔条 */
            .time-divider{{text-align:center;margin:16px 0 12px;}}
            .time-divider span{{font-size:12px;color:rgba(255,255,255,.25);
                padding:4px 14px;border-radius:10px;
                background:rgba(255,255,255,.04);}}

            /* 消息气泡 — 匹配 ChatDisplayHelper */
            .message-container{{margin:6px 0;animation:msgIn .35s;}}
            @keyframes msgIn{{from{{opacity:0;transform:translateY(10px);}}to{{opacity:1;transform:translateY(0);}}}}
            .assistant-message{{text-align:left;}}.user-message{{text-align:right;}}
            .message-bubble{{display:inline-block;max-width:82%;padding:10px 14px;
                border-radius:14px;font-size:16px;line-height:1.55;word-wrap:break-word;}}
            .assistant-bubble{{background:rgba(255,200,215,0.30);color:#ffe8ee;border-bottom-left-radius:4px;}}
            .user-bubble{{background:rgba(255,255,255,0.12);color:#ddd;border-bottom-right-radius:4px;}}
            .assistant-name{{font-size:12px;margin-bottom:2px;opacity:.5;color:#ffb7c5;}}
            .user-name{{font-size:12px;margin-bottom:2px;opacity:.5;color:#999;}}
            .timestamp{{font-size:11px;opacity:.3;margin-top:3px;text-align:right;}}
            .message-content{{word-wrap:break-word;white-space:pre-wrap;}}
            .cursor{{display:inline-block;width:6px;height:13px;background:#ffb7c5;
                margin-left:2px;vertical-align:middle;animation:blink 1s infinite;}}
            @keyframes blink{{0%,100%{{opacity:1;}}50%{{opacity:0;}}}}

            #typing-indicator{{display:none;padding:4px 16px;}}
            .dots{{display:flex;gap:3px;}}
            .dot{{width:6px;height:6px;background:#ffb7c5;border-radius:50%;animation:ty 1.4s infinite;}}
            .dot:nth-child(2){{animation-delay:.2s;}}.dot:nth-child(3){{animation-delay:.4s;}}
            @keyframes ty{{0%,80%,100%{{opacity:.3;transform:scale(.8);}}40%{{opacity:1;transform:scale(1);}}}}

            /* TTS 状态指示器 */
            .tts-status-container{{margin-top:8px;}}
            .tts-status{{font-size:12px;padding:2px 8px;border-radius:8px;display:inline-block;}}
            .tts-pending{{background:rgba(255,200,100,.18);color:#ffc850;}}
            .tts-completed{{background:rgba(100,200,100,.18);color:#80d080;}}
            .tts-failed{{background:rgba(200,100,100,.18);color:#d08080;}}

            #input-row{{display:flex;gap:8px;padding:10px 14px 14px;}}
            #msg-input{{flex:1;background:rgba(255,255,255,0.06);
                border:1px solid rgba(255,255,255,0.1);border-radius:20px;
                padding:10px 18px;color:#ddd;font-size:16px;outline:none;
                font-family:'Microsoft YaHei',sans-serif;}}
            #msg-input:focus{{border-color:rgba(255,150,170,.35);}}
            #msg-input:disabled{{opacity:.4;}}
            #send-btn{{background:rgba(255,150,170,.25);color:rgba(255,255,255,.8);
                border:none;border-radius:18px;padding:8px 18px;cursor:pointer;
                font-size:18px;font-family:'Microsoft YaHei',sans-serif;outline:none;}}
            #send-btn:focus,#send-btn:focus-visible{{outline:none;}}
            #send-btn:hover{{background:rgba(255,150,170,.45);}}
            #send-btn:disabled{{opacity:.4;cursor:default;}}
            #img-btn{{background:rgba(255,255,255,.06);color:rgba(255,255,255,.4);
                border:none;border-radius:18px;padding:8px 14px;cursor:pointer;
                font-size:18px;font-family:'Microsoft YaHei',sans-serif;outline:none;}}
            #img-btn:hover{{background:rgba(255,255,255,.12);color:#fff;}}
            #img-btn.active{{background:rgba(80,160,80,.15);color:#60d060;}}

            /* 状态栏（替代 Qt QLabel） */
            #status-bar{{position:fixed;bottom:6px;left:16px;z-index:50;
                display:flex;flex-direction:column;gap:2px;
                color:rgba(255,255,255,.3);font-size:14px;pointer-events:none;}}

            #particles{{position:fixed;top:0;left:0;width:100%;height:100%;
                pointer-events:none;z-index:0;}}

            /* 侧边栏 */

            #sidebar{{position:fixed;top:38px;left:0;width:300px;height:calc(100% - 38px);
                z-index:310;display:flex;flex-direction:column;
                background:rgba(12,10,22,0.45);border-right:1px solid rgba(255,255,255,0.06);
                backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
                transform:translateX(-100%);transition:transform .3s cubic-bezier(.4,0,.2,1);}}
            #sidebar.open{{transform:translateX(0);}}

            #sidebar-header{{padding:16px 20px 12px;
                font-size:14px;font-weight:bold;color:rgba(255,255,255,.4);
                border-bottom:1px solid rgba(255,255,255,.06);}}

            #sidebar-btns{{flex:1;padding:18px;display:flex;flex-direction:column;}}
            .side-btn{{display:block;width:100%;padding:14px 20px;border-radius:10px;
                border:none;outline:none;background:rgba(255,255,255,.04);color:rgba(255,255,255,.55);
                font-size:16px;font-family:'Microsoft YaHei',sans-serif;margin-bottom:16px;
                cursor:pointer;text-align:left;transition:all .2s;}}
            .side-btn:hover{{background:rgba(255,255,255,.12)!important;color:#fff!important;}}
            .side-btn.danger{{background:rgba(200,70,70,.1);color:rgba(255,150,150,.55);}}
            .side-btn.danger:hover{{background:rgba(200,70,70,.3)!important;color:#faa!important;}}

            #sidebar-footer{{padding:14px;border-top:1px solid rgba(255,255,255,.06);}}

            /* 侧边栏遮罩 */
            #sidebar-overlay{{position:fixed;top:38px;left:0;width:100%;height:calc(100% - 38px);
                z-index:309;background:rgba(0,0,0,.3);display:none;}}
            #sidebar-overlay.show{{display:block;}}

            /* HTML 标题栏 */
            #title-bar{{position:fixed;top:0;left:0;width:100%;height:38px;
                z-index:300;display:flex;align-items:center;padding:0 8px;
                background:rgba(12,10,22,0.60);backdrop-filter:blur(8px);
                -webkit-backdrop-filter:blur(8px);}}
            #title-bar .ttl{{flex:1;font-size:14px;color:rgba(255,255,255,.5);
                font-family:'Microsoft YaHei',sans-serif;padding-left:6px;
                pointer-events:none;}}
            .tbtn{{width:32px;height:28px;border-radius:6px;border:none;
                background:transparent;color:rgba(255,255,255,.45);font-size:16px;
                cursor:pointer;display:flex;align-items:center;justify-content:center;
                font-family:'Microsoft YaHei',sans-serif;outline:none;}}
            .tbtn:hover{{background:rgba(255,255,255,.08);color:#fff;}}
            .tbtn.cls:hover{{background:rgba(200,60,60,.5);color:#fff;}}
        </style></head><body>
        <div id="title-bar">
            <button class="tbtn" onclick="toggleSidebar()" style="font-size:18px;font-weight:bold;">=</button>
            <span class="ttl">八重樱 · 圣痕之庭</span>
            <button class="tbtn" onclick="doAction('min')">-</button>
            <button class="tbtn" onclick="doAction('max')">+</button>
            <button class="tbtn cls" onclick="doAction('close')">x</button>
        </div>
        <div id="sidebar-overlay" onclick="toggleSidebar()"></div>
        <div id="sidebar">
            <div id="sidebar-header"><span id="panel-title">控制面板</span></div>
            <div id="sidebar-btns">
                {tts_btn}
                {vis_btn}
                {mem_btn}
                <button class="side-btn" onclick="doAction('api_config')">API运营商</button>
                <button class="side-btn" onclick="doAction('bg')">切换背景</button>
                <button class="side-btn" onclick="doAction('live2d')">Live2D模型</button>
                <button class="side-btn" onclick="showDebugPanel()">调试系统</button>
                <button class="side-btn" onclick="doAction('settings')">设置</button>
            </div>
            <!-- TTS 二级面板 -->
            <div id="tts-panel" class="sub-panel" style="flex:1;padding:16px;display:none;flex-direction:column;gap:10px;">
                <button class="side-btn" id="btn-server" onclick="doAction('tts_svr_toggle')"
                    style="background:rgba(255,255,255,.04);color:rgba(255,255,255,.4);">启动服务器</button>
                <button class="side-btn" id="btn-client" onclick="doAction('tts_cli_toggle')"
                    disabled style="background:rgba(255,255,255,.02);color:rgba(255,255,255,.15);cursor:not-allowed;">服务器未启动</button>
                <button class="side-btn" onclick="doAction('tts_log_win')">查看日志</button>
                <div id="svr-log" style="font-size:11px;color:rgba(255,255,255,.35);
                    background:rgba(0,0,0,.2);border-radius:8px;padding:8px 10px;margin-top:4px;
                    overflow-y:auto;line-height:1.55;min-height:50px;max-height:180px;
                    font-family:'Consolas','Microsoft YaHei',sans-serif;"></div>
                <div style="flex:1;"></div>
                <button class="side-btn" onclick="showMainPanel()">返回</button>
            </div>
            <!-- 视觉二级面板 -->
            <div id="vis-panel" class="sub-panel" style="flex:1;padding:16px;display:none;flex-direction:column;gap:10px;">
                <button class="side-btn" id="btn-vision" onclick="doAction('vision')"
                    style="background:rgba(255,255,255,.04);color:rgba(255,255,255,.5);">启动视觉</button>
                <button class="side-btn" id="btn-camera" onclick="doAction('camera')"
                    disabled style="background:rgba(255,255,255,.02);color:rgba(255,255,255,.15);cursor:not-allowed;">摄像头预览(未启动)</button>
                <div style="flex:1;"></div>
                <button class="side-btn" onclick="showMainPanel()" style="margin-top:auto;">返回</button>
            </div>
            <!-- 调试二级面板 -->
            <div id="debug-panel" class="sub-panel" style="flex:1;padding:16px;display:none;flex-direction:column;gap:10px;">
                <button class="side-btn" onclick="doAction('llm_log')">LLM对话日志</button>
                <button class="side-btn" id="btn-memory-pause" onclick="doAction('mem_pause')"
                    style="background:rgba(80,180,80,.12);color:#60d060;">记忆录制中</button>
                <div style="flex:1;"></div>
                <button class="side-btn" onclick="showMainPanel()" style="margin-top:auto;">返回</button>
            </div>
            <div id="sidebar-footer">
                <button class="side-btn danger" onclick="doAction('close')">退出</button>
            </div>
        </div>
        <script>
        function toggleSidebar(){{
            var s=document.getElementById('sidebar');
            var o=document.getElementById('sidebar-overlay');
            s.classList.toggle('open');o.classList.toggle('show');
        }}
        function doAction(a){{window._sakura_action=a;}}
        function hideAllPanels(){{
            var ps=document.querySelectorAll('.sub-panel');
            for(var i=0;i<ps.length;i++)ps[i].style.display='none';
            document.getElementById('sidebar-btns').style.display='';
            document.getElementById('sidebar-footer').style.display='';
            document.getElementById('panel-title').textContent='控制面板';
        }}
        function showTtsPanel(){{
            document.getElementById('sidebar-btns').style.display='none';
            document.getElementById('sidebar-footer').style.display='none';
            document.getElementById('tts-panel').style.display='flex';
            document.getElementById('panel-title').textContent='语音系统';
        }}
        function showVisPanel(){{
            document.getElementById('sidebar-btns').style.display='none';
            document.getElementById('sidebar-footer').style.display='none';
            document.getElementById('vis-panel').style.display='flex';
            document.getElementById('panel-title').textContent='视觉系统';
        }}
        function showDebugPanel(){{
            document.getElementById('sidebar-btns').style.display='none';
            document.getElementById('sidebar-footer').style.display='none';
            document.getElementById('debug-panel').style.display='flex';
            document.getElementById('panel-title').textContent='调试系统';
        }}
        function showMainPanel(){{hideAllPanels();}}
        document.getElementById('title-bar').addEventListener('mousedown',function(e){{
            if(e.target.tagName==='BUTTON')return;
            window._sakura_action='drag';
        }});
        </script>
        <img id="bg-img" src="file:///{BG_IMG}">
        <div id="bg-overlay"></div>
        <canvas id="particles"></canvas>

        <div id="welcome-overlay"><div>八重樱 · 圣痕之庭</div></div>

        <div id="status-bar">
            <span id="vision-text">{vis_txt}</span>
            <span id="status-text">圣痕空间·待机中</span>
        </div>

        <div id="main">
            <div id="l2d"><canvas id="l2d-canvas"></canvas></div>
            <div id="right">
                <div class="card">
                    <div id="msgs"></div>
                    <div id="typing-indicator">
                        <div class="assistant-message">
                            <span class="assistant-name">八重樱</span>
                            <div class="dots">
                                <div class="dot"></div><div class="dot"></div><div class="dot"></div>
                            </div>
                        </div>
                    </div>
                    <div id="input-row">
                        <input id="msg-input" type="text" placeholder="与八重樱对话..." autofocus>
                        <button id="img-btn" onclick="doAction('img')" title="发送图片">□</button>
                        <button id="send-btn" onclick="submitMsg()">→</button>
                    </div>
                </div>
            </div>
        </div>

        <script src="file:///{libs}/live2dcubismcore.min.js"></script>
        <script src="file:///{libs}/live2d.min.js"></script>
        <script src="file:///{libs}/pixi.min.js"></script>
        <script src="file:///{libs}/index.min.js"></script>

        <script>
        // ==== 轮询通信：设 window._sakura_action ====
        function submitMsg(){{
            var inp = document.getElementById('msg-input');
            var text = inp.value.trim();
            if(!text) return;
            window._sakura_action = 'send:' + text;
            inp.value = '';
        }}
        document.getElementById('msg-input').addEventListener('keydown',function(e){{
            if(e.key==='Enter') submitMsg();
        }});

        // ==== Live2D ====
        var g_model = null;
        var g_app = null;
        var g_modelW = 0, g_modelH = 0;  // 原始尺寸，不随缩放改变
        var g_animFrame = null;
        var _mt=0,_mc=0,_ms=0.35;
        function setMouthOpen(v){{
            _mt=Math.max(0,Math.min(1,Number(v)||0));
            if(g_animFrame===null) _tickMouth();
        }}
        function _tickMouth(){{
            _mc+=(_mt-_mc)*_ms;
            if(_mc<0.005) _mc=0;
            if(g_model&&g_model.internalModel){{
                try{{g_model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY',_mc);}}catch(e){{}}
            }}
            if(_mt===0&&_mc<0.001){{g_animFrame=null;return;}}
            g_animFrame=requestAnimationFrame(_tickMouth);
        }}
        function _resizeLive2D() {{
            if (!g_app || !g_model || !g_modelW) return;
            g_app.resize();
            g_model.x = g_app.screen.width / 2;
            g_model.y = g_app.screen.height * 0.55;
            g_model.scale.set(Math.min(g_app.screen.width / g_modelW * 1.1, g_app.screen.height / g_modelH * 1.1));
        }}
        (async function(){{
            try{{
                if(typeof PIXI==='undefined'||!PIXI.live2d){{console.error('PIXI/Live2D not loaded');return;}}
                var app = new PIXI.Application({{
                    view:document.getElementById('l2d-canvas'),
                    resizeTo:document.getElementById('l2d'),
                    transparent:true,autoStart:true,backgroundAlpha:0
                }});
                g_app = app;
                var model = await PIXI.live2d.Live2DModel.from('{model_url}');
                g_modelW = model.width; g_modelH = model.height;
                model.anchor.set(0.5,0.35);
                model.x=app.screen.width/2; model.y=app.screen.height*0.55;
                var s=Math.min(app.screen.width/g_modelW*1.1, app.screen.height/g_modelH*1.1);
                model.scale.set(s);
                app.stage.addChild(model);
                g_model=model;
                console.log('Live2D loaded');
                window._l2d_app = app;
                // 切换模型函数
                window.switchModel = async function(url){{
                    if(!g_app||!g_model)return;
                    g_app.stage.removeChild(g_model);
                    try{{g_model.destroy();}}catch(e){{}}
                    var m=await PIXI.live2d.Live2DModel.from(url);
                    g_modelW=m.width;g_modelH=m.height;
                    m.anchor.set(0.5,0.35);m.x=g_app.screen.width/2;m.y=g_app.screen.height*0.55;
                    var s=Math.min(g_app.screen.width/g_modelW*1.1,g_app.screen.height/g_modelH*1.1);
                    m.scale.set(s);g_app.stage.addChild(m);g_model=m;
                    if(m.internalModel&&m.internalModel.motionManager){{
                        try{{var mg=m.internalModel.motionManager.motionGroups;
                        if(mg&&mg.idle&&mg.idle.length>0)m.motion('idle',0);}}catch(e){{}}
                    }}
                }};
                console.log('Live2D loaded');
                if(model.internalModel&&model.internalModel.motionManager){{
                    try{{
                        var mg=model.internalModel.motionManager.motionGroups;
                        if(mg&&mg.idle&&mg.idle.length>0) model.motion('idle',0);
                    }}catch(e){{}}
                }}
                window.addEventListener('resize', _resizeLive2D);
            }}catch(e){{console.error('Live2D error:',e);}}
        }})();

        // ==== 花瓣粒子 ====
        (function(){{
            var cv=document.getElementById('particles');
            cv.width=window.innerWidth; cv.height=window.innerHeight;
            var ctx=cv.getContext('2d');
            var petals=[];
            for(var i=0;i<35;i++) petals.push({{
                x:Math.random()*cv.width,y:Math.random()*cv.height,
                sp:0.3+Math.random()*0.6,sw:0.2+Math.random()*0.3,
                sz:4+Math.random()*6,op:0.15+Math.random()*0.35,
                rot:Math.random()*360,ph:Math.random()*Math.PI*2
            }});
            function tick(){{
                ctx.clearRect(0,0,cv.width,cv.height);
                for(var i=0;i<petals.length;i++){{
                    var p=petals[i];
                    p.y+=p.sp; p.x+=Math.sin(p.ph)*p.sw;
                    p.rot+=0.5; p.ph+=0.02;
                    if(p.y>cv.height+10){{p.y=-10;p.x=Math.random()*cv.width;}}
                    ctx.save(); ctx.translate(p.x,p.y); ctx.rotate(p.rot*Math.PI/180);
                    ctx.fillStyle='rgba(255,182,193,'+p.op+')';
                    ctx.beginPath(); ctx.ellipse(0,0,p.sz,p.sz*0.4,0,0,Math.PI*2);
                    ctx.fill(); ctx.restore();
                }}
                requestAnimationFrame(tick);
            }}
            tick();
            window.addEventListener('resize',function(){{
                cv.width=window.innerWidth; cv.height=window.innerHeight;
            }});
        }})();
        </script>
        </body></html>"""

    # ======================= 消息处理 =======================

    def _user_input_from_html(self, inp):
        if self.is_waiting_response: return
        if not inp: return
        if inp.lower() in ['退出', 'exit', 'quit', 'q']:
            self._stop_idle_timer()
            self.display.add_message("旅人", inp, is_user=True)
            self.display.add_message("八重樱", "……要离开了吗？愿下次樱花盛开时，我们还能再见。", is_user=False)
            QTimer.singleShot(1000, self.close); return

        self._stop_idle_timer()
        self._set_input(False)
        self._bracket_depth = 0  # 安全重置括号深度
        self._buf = ""
        self._actions_displayed = 0
        if self.tts_manager:
            self.tts_manager.stop_playback()
        self.display.add_message("旅人", inp, is_user=True)
        hint = {"微笑": "（旅人面带微笑地说：）", "大笑": "（旅人开怀大笑地说：）", "悲伤": "（旅人的神色有些低落地说：）"}.get(self._user_expression, "")
        time_hint = f"（当前时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}）\n"
        # 读取离开时长，告知 LLM
        try:
            with open("data/last_leave.txt", "r") as f:
                leave_ts = float(f.read().strip())
            gap_min = int((time.time() - leave_ts) / 60)
            if gap_min >= 1:
                if gap_min < 2:
                    dur = "一小会儿"
                elif gap_min < 5:
                    dur = "几分钟"
                elif gap_min < 15:
                    dur = "十来分钟"
                elif gap_min < 40:
                    dur = "半个多小时"
                elif gap_min < 90:
                    dur = "一个多小时"
                elif gap_min < 180:
                    dur = "两三个小时"
                elif gap_min < 360:
                    dur = "小半天"
                elif gap_min < 1440:
                    dur = "大半天"
                elif gap_min < 2880:
                    dur = "一天多"
                else:
                    d = gap_min // 1440
                    dur = f"大概{d}天"
                time_hint += f"（旅人离开了{dur}，刚才回到了圣痕空间）\n"
            os.remove("data/last_leave.txt")
        except Exception:
            pass
        self._last_activity = time.time()
        api_inp = f"{time_hint}{hint}{inp}" if hint else f"{time_hint}{inp}"
        # 处理待发送的图片
        img_desc = ""
        if getattr(self, '_pending_image', None):
            img_path = self._pending_image
            self._pending_image = None
            self._run_js("document.getElementById('img-btn').classList.remove('active')")
            self.display.add_message("系统", "识别图片中...", is_user=False)
            img_desc = self._describe_pending_image(img_path)

        if img_desc:
            api_inp = f"（旅人发来一张图片，内容是：{img_desc}）\n{api_inp}"

        self._has_chatted = True
        self.is_waiting_response = True; self.display.show_typing_indicator()
        self._current_raw_response = ""
        self._current_user_msg = api_inp
        um = LANGCHAIN_AVAILABLE and self.memory_manager
        self.chat_thread = ChatThread(self.api_key, self.url, self.model, api_inp, use_memory=um, extra_body=self.api_extra_body, memory_paused=self._memory_paused)
        self.chat_thread.chunk_received.connect(self._on_chunk)
        self.chat_thread.response_complete.connect(self._on_complete)
        self.chat_thread.error_occurred.connect(self._on_error); self.chat_thread.start()

    def _on_chunk(self, chunk):
        try:
            self._on_chunk_impl(chunk)
        except Exception:
            import traceback
            traceback.print_exc()

    def _on_chunk_impl(self, chunk):
        self.display.hide_typing_indicator()
        self._current_raw_response += chunk

        # 换行符直接丢弃，不参与任何断句和显示
        clean = chunk.replace('\n', '')
        buf = getattr(self, '_buf', '') + clean
        depth = getattr(self, '_bracket_depth', 0)
        sentences, remainder, depth = self._extract_sentences(buf, depth)
        self._bracket_depth = depth
        self._buf = remainder

        for s in sentences:
            if self.display.current_streaming_message_id:
                self.display.complete_message(
                    self.display.current_streaming_message_id, s)
                if self.tts_manager:
                    self.tts_manager.synthesize(s,
                        self.display.current_streaming_message_id)

        if remainder.strip():
            if self.display.current_streaming_message_id:
                self.display.current_message_content = remainder.strip()
                self.display.update_message(
                    self.display.current_streaming_message_id, remainder.strip())
            else:
                self.display.add_message("八重樱", remainder.strip(),
                    is_user=False, is_streaming=True)
        else:
            self.display.current_streaming_message_id = None
            self.display.current_message_content = ""

        # 从原始响应中提取完整括号内容作为动作行
        self._extract_actions_from_raw()

    def _on_complete(self, full_response):
        self.display.hide_typing_indicator()
        # 存储 LLM 日志
        raw = self._current_raw_response.strip()
        if raw:
            self._llm_logs.append({
                "user": self._current_user_msg,
                "response": raw
            })
            if len(self._llm_logs) > 50:
                self._llm_logs = self._llm_logs[-50:]
        if self.display.current_streaming_message_id:
            self.display.complete_message(
                self.display.current_streaming_message_id,
                self.display.current_message_content)
            self._bracket_depth = 0
            self._buf = ""
            self._actions_displayed = 0
            self.display.current_streaming_message_id = None
            self.display.current_message_content = ""
        else:
            self.display.current_streaming_message_id = None
            self.display.current_message_content = ""

        self.is_waiting_response = False
        self._set_input(True)

        self._start_idle_timer()

    def _on_error(self, msg):
        self.display.hide_typing_indicator()
        s = "API错误"
        if "key" in msg.lower(): s = "API密钥无效"
        elif "network" in msg.lower(): s = "网络失败"
        self.display.add_message("系统", f"圣痕空间异常: {s}", is_user=False)
        self.is_waiting_response = False
        self._set_input(True)
        self._start_idle_timer()

    def _send_auto(self, prompt):
        self.is_waiting_response = True
        self._set_input(False)
        self._bracket_depth = 0  # 安全重置括号深度
        self._buf = ""
        self._actions_displayed = 0
        self._current_raw_response = ""
        self.display.show_typing_indicator()
        self._has_chatted = True
        time_hint = f"（当前时间：{datetime.now().strftime('%Y年%m月%d日 %H:%M')}）\n"
        prompt = f"{time_hint}{prompt}"
        um = LANGCHAIN_AVAILABLE and self.memory_manager
        self.chat_thread = ChatThread(self.api_key, self.url, self.model, prompt, use_memory=um, extra_body=self.api_extra_body, memory_paused=self._memory_paused)
        self.chat_thread.chunk_received.connect(self._on_chunk)
        self.chat_thread.response_complete.connect(self._on_complete)
        self.chat_thread.error_occurred.connect(self._on_error); self.chat_thread.start()

    # ======================= 辅助 =======================

    def _extract_actions_from_raw(self):
        """从完整原始响应中扫描所有闭合括号内容，新建的出现即插入为动作行"""
        raw = getattr(self, '_current_raw_response', '')
        displayed = getattr(self, '_actions_displayed', 0)
        actions = []
        depth = 0
        start = -1
        for i, ch in enumerate(raw):
            if ch in '（(【':
                if depth == 0:
                    start = i
                depth += 1
            elif ch in '）)】':
                if depth > 0:
                    depth -= 1
                if depth == 0 and start >= 0:
                    actions.append(raw[start:i+1])
                    start = -1
        # 只插入新出现的动作行
        for a in actions[displayed:]:
            self.display._insert_action_line(a)
        self._actions_displayed = len(actions)

    @staticmethod
    def _extract_sentences(buffer, depth=0):
        """
        括号深度感知的句子提取。
        括号内字符全部丢弃，括号外按句号切句。
        返回 (sentences, remainder, new_depth)
        """
        sentences = []
        current = []
        for ch in buffer:
            if ch in '（(【':
                depth += 1
                continue
            if ch in '）)】':
                if depth > 0:
                    depth -= 1
                continue
            if depth == 0:
                current.append(ch)
                if ch in '。！？':
                    s = ''.join(current).strip()
                    if s:
                        sentences.append(s)
                    current = []
        return sentences, ''.join(current), depth

    def _toggle_bg(self):
        self._bg_show = not self._bg_show
        if self._bg_show:
            self.view.page().runJavaScript("document.body.classList.remove('gradient-bg')")
        else:
            self.view.page().runJavaScript("document.body.classList.add('gradient-bg')")

    def _show_api_config(self):
        if hasattr(self, '_api_cfg_dlg') and self._api_cfg_dlg and self._api_cfg_dlg.isVisible():
            self._api_cfg_dlg.raise_()
            return

        cfg = load_config()
        dlg = QDialog(self)
        dlg.setWindowTitle("API运营商配置")
        dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        dlg.setAttribute(Qt.WA_TranslucentBackground)
        dlg.setGeometry(300, 200, 500, 600)
        dlg.setStyleSheet("""
            QDialog { background: transparent; }
            #container {
                background: rgba(20, 15, 30, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
            QLabel { color: rgba(255,255,255,.5); font-family: 'Microsoft YaHei'; font-size: 13px; }
            QComboBox {
                padding: 8px 12px; background: rgba(0,0,0,.25); color: #ccc;
                border: 1px solid rgba(255,255,255,.1); border-radius: 8px;
                font-family: 'Microsoft YaHei'; font-size: 13px;
            }
            QComboBox:hover { border-color: rgba(255,150,170,.35); }
            QComboBox QAbstractItemView {
                background: rgba(20,15,30,.95); color: #ccc;
                border: 1px solid rgba(255,255,255,.1);
                selection-background-color: rgba(255,150,170,.25);
            }
            QLineEdit {
                padding: 8px 12px; background: rgba(0,0,0,.25); color: #ccc;
                border: 1px solid rgba(255,255,255,.1); border-radius: 8px;
                font-family: 'Microsoft YaHei'; font-size: 13px;
            }
            QLineEdit:focus { border-color: rgba(255,150,170,.35); }
        """)

        outer = QVBoxLayout(dlg); outer.setContentsMargins(0,0,0,0)
        container = QFrame(); container.setObjectName("container")
        inner = QVBoxLayout(container); inner.setContentsMargins(24, 0, 24, 20); inner.setSpacing(12)

        # 标题栏
        tb_layout = QHBoxLayout(); tb_layout.setContentsMargins(0, 10, 4, 10)
        tl = QLabel("  API运营商配置")
        tl.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        tl.setStyleSheet("color: #ffb7c5;")
        tb_layout.addWidget(tl); tb_layout.addStretch()
        cb = QPushButton("x"); cb.setFixedSize(32,32)
        cb.setStyleSheet("QPushButton{background:rgba(255,255,255,.05);color:rgba(255,255,255,.4);"
            "border-radius:16px;font-size:18px;}QPushButton:hover{background:rgba(200,60,60,.4);color:#fff;}")
        cb.clicked.connect(dlg.close); tb_layout.addWidget(cb)
        inner.addLayout(tb_layout)

        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255, 255, 255, .08);")
        inner.addWidget(line)

        # 选项卡
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane{border:1px solid rgba(255,255,255,.06);border-radius:8px;}"
            "QTabBar::tab{background:rgba(0,0,0,.2);color:rgba(255,255,255,.4);padding:8px 20px;font-family:'Microsoft YaHei';}"
            "QTabBar::tab:selected{background:rgba(255,150,170,.15);color:#ffb7c5;}")

        # ---- 选项卡1: 聊天模型 ----
        chat_tab = QWidget()
        chat_layout = QVBoxLayout(chat_tab)
        chat_layout.setContentsMargins(0, 12, 0, 0)
        chat_layout.setSpacing(10)

        chat_layout.addWidget(QLabel("运营商"))
        provider_combo = QComboBox()
        for pid in PROVIDERS:
            provider_combo.addItem(PROVIDERS[pid]["name"], pid)
        cur_provider = cfg.get("provider", "deepseek")
        if cur_provider in PROVIDERS:
            provider_combo.setCurrentText(PROVIDERS[cur_provider]["name"])
        chat_layout.addWidget(provider_combo)

        # API Key（含明文切换）
        api_keys = load_env()
        chat_layout.addWidget(QLabel("API Key"))
        key_row = QHBoxLayout(); key_row.setSpacing(8)
        key_input = QLineEdit()
        key_input.setEchoMode(QLineEdit.Password)
        key_input.setText(api_keys.get(cur_provider, ""))
        key_input.setPlaceholderText("输入API密钥...")
        key_row.addWidget(key_input, 1)
        eye_btn = QPushButton("显")
        eye_btn.setFixedSize(36, 36)
        eye_btn.setStyleSheet("QPushButton{background:rgba(255,255,255,.06);color:rgba(255,255,255,.5);"
            "border-radius:8px;font-size:12px;border:none;}"
            "QPushButton:hover{background:rgba(255,255,255,.15);color:#fff;}")
        def toggle_eye():
            if key_input.echoMode() == QLineEdit.Password:
                key_input.setEchoMode(QLineEdit.Normal)
                eye_btn.setText("隐")
            else:
                key_input.setEchoMode(QLineEdit.Password)
                eye_btn.setText("显")
        eye_btn.clicked.connect(toggle_eye)
        key_row.addWidget(eye_btn)
        chat_layout.addLayout(key_row)

        # Base URL
        chat_layout.addWidget(QLabel("Base URL"))
        url_input = QLineEdit()
        url_input.setText(cfg.get("base_url", ""))
        chat_layout.addWidget(url_input)

        # Model（下拉选择，含思考模式）
        def _populate_models(pid):
            model_combo.blockSignals(True)
            model_combo.clear()
            models = PROVIDERS.get(pid, {}).get("models", [])
            cur_model = cfg.get("model", "")
            cur_extra = cfg.get("extra_body", {})
            sel_idx = 0
            for i, m in enumerate(models):
                model_combo.addItem(m["name"], m)
                if m["id"] == cur_model:
                    # 匹配额外参数判断是否为思考模式
                    m_extra = m.get("extra_body", {})
                    if m_extra == cur_extra:
                        sel_idx = i
                    elif not m_extra and not cur_extra:
                        sel_idx = i
            model_combo.setCurrentIndex(sel_idx)
            model_combo.blockSignals(False)

        chat_layout.addWidget(QLabel("模型"))
        model_combo = QComboBox()
        _populate_models(cur_provider)
        chat_layout.addWidget(model_combo)

        # 运营商切换联动：更新 key / base_url / model
        def on_provider_changed(idx):
            pid = provider_combo.itemData(idx)
            if pid and pid in PROVIDERS:
                key_input.setText(api_keys.get(pid, ""))
                url_input.setText(PROVIDERS[pid]["base_url"])
                _populate_models(pid)
        provider_combo.currentIndexChanged.connect(on_provider_changed)

        tabs.addTab(chat_tab, "聊天模型")

        # ---- 选项卡2: 视觉模型 ----
        vis_tab = QWidget()
        vis_layout = QVBoxLayout(vis_tab)
        vis_layout.setContentsMargins(0, 12, 0, 0)
        vis_layout.setSpacing(10)

        vis_layout.addWidget(QLabel("视觉模型（识图用）"))
        vis_combo = QComboBox()
        from need.api_config import VISION_MODELS
        for vid, vinfo in VISION_MODELS.items():
            vis_combo.addItem(vinfo["name"], vid)
        cur_vis = cfg.get("vision_model", "qwen3-vl-flash")
        if cur_vis in VISION_MODELS:
            vis_combo.setCurrentText(VISION_MODELS[cur_vis]["name"])
        vis_layout.addWidget(vis_combo)

        vis_layout.addWidget(QLabel("视觉 API Key（用千问的Key）"))
        vis_key_input = QLineEdit()
        vis_key_input.setEchoMode(QLineEdit.Password)
        vis_key_input.setText(load_env().get("qwen", ""))
        vis_layout.addWidget(vis_key_input)

        vis_layout.addStretch()
        tabs.addTab(vis_tab, "视觉模型")

        inner.addWidget(tabs)

        # 保存
        def on_save():
            pid = provider_combo.currentData()
            m = model_combo.currentData() or {}
            new_key = key_input.text().strip()
            new_cfg = {
                "provider": pid,
                "base_url": url_input.text().strip(),
                "model": m.get("id", ""),
                "extra_body": m.get("extra_body", {}),
                "vision_model": vis_combo.currentData(),
                "vision_base_url": VISION_MODELS.get(vis_combo.currentData(), {}).get("base_url", ""),
            }
            save_env_key(pid, new_key)
            # 视觉 Key 写回
            vis_new_key = vis_key_input.text().strip()
            if vis_new_key:
                save_env_key("qwen", vis_new_key)
            save_config(new_cfg)
            self.api_key = new_key
            self.url = new_cfg["base_url"]
            self.model = new_cfg["model"]
            self.api_extra_body = new_cfg["extra_body"]
            dlg.close()

        # 测试联通 + 状态
        test_row = QHBoxLayout(); test_row.setSpacing(10)
        test_status = QLabel("")
        test_status.setStyleSheet("color:rgba(255,255,255,.35);font-size:12px;")

        def on_test():
            pid = provider_combo.currentData()
            m = model_combo.currentData() or {}
            test_key = key_input.text().strip()
            test_url = url_input.text().strip()
            test_model = m.get("id", "")
            test_extra = m.get("extra_body", {})
            if not test_key:
                test_status.setText("请先填入 API Key")
                test_status.setStyleSheet("color:#d08080;font-size:12px;")
                return
            test_btn.setEnabled(False)
            test_btn.setText("测试中...")
            test_status.setText("")
            result = {}

            def _do_test():
                try:
                    from openai import OpenAI
                    client = OpenAI(api_key=test_key, base_url=test_url)
                    kwargs = {"model": test_model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 10, "stream": False}
                    if test_extra:
                        kwargs["extra_body"] = test_extra
                    client.chat.completions.create(**kwargs)
                    result["ok"] = True
                except Exception as e:
                    result["ok"] = False
                    result["msg"] = str(e)[:80]

            threading.Thread(target=_do_test, daemon=True).start()

            def _check_result():
                if "ok" not in result:
                    QTimer.singleShot(200, _check_result)
                    return
                if result["ok"]:
                    test_status.setText("联通成功")
                    test_status.setStyleSheet("color:#60d060;font-size:12px;")
                else:
                    test_status.setText(f"失败: {result['msg']}")
                    test_status.setStyleSheet("color:#d08080;font-size:12px;")
                test_btn.setEnabled(True)
                test_btn.setText("测试联通")

            QTimer.singleShot(200, _check_result)

        test_btn = QPushButton("测试联通")
        test_btn.setStyleSheet("QPushButton{font-family:'Microsoft YaHei';font-size:13px;"
            "padding:10px 22px;border-radius:14px;border:none;"
            "background:rgba(255,255,255,.08);color:rgba(255,255,255,.55);}"
            "QPushButton:hover{background:rgba(255,255,255,.18);color:#fff;}")
        test_btn.clicked.connect(on_test)
        test_row.addWidget(test_btn)
        test_row.addWidget(test_status, 1)
        inner.addLayout(test_row)

        save_btn = QPushButton("保存")
        save_btn.setStyleSheet("QPushButton{font-family:'Microsoft YaHei';font-size:13px;"
            "padding:10px 28px;border-radius:14px;border:none;"
            "background:rgba(255,150,170,.22);color:#ffb7c5;}"
            "QPushButton:hover{background:rgba(255,150,170,.4);}")
        save_btn.clicked.connect(on_save)
        inner.addWidget(save_btn)

        outer.addWidget(container)

        def _press(e):
            if e.button() == Qt.LeftButton:
                dlg._dp = e.globalPos() - dlg.frameGeometry().topLeft()
        def _move(e):
            if e.buttons() == Qt.LeftButton and hasattr(dlg, '_dp'):
                dlg.move(e.globalPos() - dlg._dp)
        container.mousePressEvent = _press; container.mouseMoveEvent = _move

        dlg.destroyed.connect(lambda: setattr(self, '_api_cfg_dlg', None))
        self._api_cfg_dlg = dlg
        dlg.show()

    def _tts_svr_toggle(self):
        if self._tts_server_process is not None:
            # 关闭服务器 → 先断开客户端，再杀进程树
            self._tts_cli_toggle(force=True)
            pid = self._tts_server_process.pid
            try:
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                               capture_output=True, timeout=5)
            except Exception:
                self._tts_server_process.terminate()
            self._tts_server_process = None
            self._set_btn("btn-server", "启动服务器", "rgba(255,255,255,.04)", "rgba(255,255,255,.4)")
            self._set_btn("btn-client", "服务器未启动", "rgba(255,255,255,.02)", "rgba(255,255,255,.15)", True)
            self._tts_log("服务器已关闭")
            return
        # 检查端口是否已被占用
        try:
            s = socket.create_connection(("localhost", 8770), timeout=0.5)
            s.close()
            self._tts_log("端口 8770 已被占用，服务器可能已在运行")
            return
        except (ConnectionRefusedError, OSError, socket.timeout):
            pass
        # 启动服务器
        try:
            server_dir = os.path.join(os.path.dirname(__file__), "TTS_GPT_SoVITS")
            py = r"D:\Conda_base\envs\gpt_sovits\python.exe"
            self._tts_server_process = subprocess.Popen(
                [py, "start_servers.py"], cwd=server_dir,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            self._set_btn("btn-server", "启动中...", "rgba(255,200,80,.12)", "#ffc850")
            self._tts_log("正在启动服务器...")
            threading.Thread(target=self._read_server_output, daemon=True).start()
            QTimer.singleShot(3000, self._check_server_ready)
        except Exception as e:
            self._tts_log(f"启动失败: {e}")
            self._set_btn("btn-server", "启动服务器", "rgba(255,255,255,.04)", "rgba(255,255,255,.4)")

    def _read_server_output(self):
        """读取服务端 stdout，写入日志"""
        if not self._tts_server_process:
            return
        for line in self._tts_server_process.stdout:
            line = line.strip()
            if line:
                self._tts_log(line)

    def _check_server_ready(self):
        try:
            s = socket.create_connection(("localhost", 8770), timeout=1)
            s.close()
            self._set_btn("btn-server", "关闭服务器", "rgba(80,180,80,.15)", "#60d060")
            self._set_btn("btn-client", "连接", "rgba(255,255,255,.04)", "rgba(255,255,255,.5)", False)
            self._tts_log("服务器就绪，可以连接")
        except Exception:
            if self._tts_server_process and self._tts_server_process.poll() is None:
                QTimer.singleShot(2000, self._check_server_ready)
            else:
                self._tts_server_process = None
                self._set_btn("btn-server", "启动服务器", "rgba(255,255,255,.04)", "rgba(255,255,255,.4)")
                self._tts_log("服务器启动失败")

    def _tts_cli_toggle(self, force=False):
        if force:
            # 强制断开，不连接
            if self._tts_running:
                if self.tts_manager:
                    self.tts_manager.cleanup()
                self.tts_manager = None
                self._tts_running = False
            return
        if self._tts_running:
            # 断开
            if self.tts_manager:
                self.tts_manager.cleanup()
            self.tts_manager = None
            self._tts_running = False
            self._set_btn("btn-client", "连接", "rgba(255,255,255,.04)", "rgba(255,255,255,.5)")
            self._tts_log("已断开连接")
        else:
            # 连接
            if not TTS_AVAILABLE:
                return
            self.tts_manager = TTSManager(self.view, self._status_proxy, None, QMediaPlayer())
            if LIVE2D_AVAILABLE:
                self.tts_manager.mouth_open.connect(self._set_mouth_open)
            self._tts_running = True
            self._set_btn("btn-client", "已连接", "rgba(80,180,80,.15)", "#60d060")
            self._tts_log("已连接到服务器")

    def _set_btn(self, btn_id, text, bg, color, disabled=False):
        d = "true" if disabled else "false"
        esc = text.replace("\\", "\\\\").replace("'", "\\'")
        self.view.page().runJavaScript(
            f"var b=document.getElementById('{btn_id}');if(b){{"
            f"b.textContent='{esc}';b.style.background='{bg}';"
            f"b.style.color='{color}';b.disabled={d};"
            f"b.style.cursor={d}?'not-allowed':'pointer';}}")

    def _tts_log(self, msg):
        self._tts_server_logs.append(msg)
        if len(self._tts_server_logs) > 200:
            self._tts_server_logs = self._tts_server_logs[-150:]
        esc = msg.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")
        self.view.page().runJavaScript(
            f"var e=document.getElementById('svr-log');if(e){{"
            f"e.textContent+='{esc}\\n';"
            f"var lines=e.textContent.split('\\n');"
            f"if(lines.length>20)e.textContent=lines.slice(-15).join('\\n');"
            f"e.scrollTop=e.scrollHeight;}}")
        # 日志窗口在打开时一次性加载全部内容（避免跨线程操作 QTextEdit）

    def _toggle_vision(self):
        if not self.vision_manager:
            return
        if self._vision_running:
            # 先关闭预览窗口，再停止视觉
            if self.camera_window and self.camera_window.isVisible():
                self.camera_window.hide()
            self.vision_manager.stop()
            self._vision_running = False
            self._set_btn("btn-vision", "启动视觉", "rgba(255,255,255,.04)", "rgba(255,255,255,.5)")
            self._set_btn("btn-camera", "摄像头预览(未启动)", "rgba(255,255,255,.02)", "rgba(255,255,255,.15)", True)
            self.view.page().runJavaScript(
                "var e=document.getElementById('vision-text');if(e)e.textContent='';")
        else:
            self.vision_manager.start()
            self._vision_running = True
            self._set_btn("btn-vision", "关闭视觉", "rgba(80,180,80,.15)", "#60d060")
            self._set_btn("btn-camera", "打开摄像头预览", "rgba(255,255,255,.04)", "rgba(255,255,255,.5)", False)
            self.view.page().runJavaScript(
                "var e=document.getElementById('vision-text');if(e)e.textContent='视觉已连接';")

    def _apply_live2d_model(self, l2d_widget):
        model_name = l2d_widget.model_combo.currentText()
        if not model_name or model_name not in l2d_widget.model_options:
            return
        model_dir = l2d_widget.model_options[model_name]
        for f in os.listdir(model_dir):
            if f.endswith('.model3.json'):
                url = "file:///" + os.path.join(model_dir, f).replace("\\", "/")
                esc = url.replace("\\", "\\\\").replace("'", "\\'")
                self.view.page().runJavaScript(
                    f"if(window.switchModel)switchModel('{esc}');")
                logger.info(f"已更换Live2D模型: {model_name}")
                return

    def _show_live2d_window(self):
        if hasattr(self, '_l2d_dlg') and self._l2d_dlg and self._l2d_dlg.isVisible():
            self._l2d_dlg.raise_()
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Live2D模型")
        dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        dlg.setAttribute(Qt.WA_TranslucentBackground)
        dlg.setGeometry(200, 80, 580, 700)
        dlg.setStyleSheet("""
            QDialog { background: transparent; }
            #container {
                background: rgba(20, 15, 30, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
        """)
        outer = QVBoxLayout(dlg); outer.setContentsMargins(0,0,0,0)
        container = QFrame(); container.setObjectName("container")
        inner = QVBoxLayout(container); inner.setContentsMargins(24, 0, 24, 20); inner.setSpacing(10)

        # 标题栏
        tb_layout = QHBoxLayout(); tb_layout.setContentsMargins(0, 10, 4, 10)
        tl = QLabel("  Live2D模型"); tl.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        tl.setStyleSheet("color: #ffb7c5;")
        tb_layout.addWidget(tl); tb_layout.addStretch()
        cb = QPushButton("x"); cb.setFixedSize(32,32)
        cb.setStyleSheet("QPushButton{background:rgba(255,255,255,.05);color:rgba(255,255,255,.4);"
            "border-radius:16px;font-size:18px;}QPushButton:hover{background:rgba(200,60,60,.4);color:#fff;}")
        cb.clicked.connect(dlg.hide); tb_layout.addWidget(cb)
        inner.addLayout(tb_layout)

        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255, 255, 255, .08);")
        inner.addWidget(line)

        # Live2D 组件（内置模型选择下拉 + 预览区）
        l2d_widget = Live2DWidget(default_size=(520, 480))
        l2d_widget.model_combo.setStyleSheet("QComboBox{padding:6px 12px;background:rgba(0,0,0,.25);color:#ccc;"
            "border:1px solid rgba(255,255,255,.1);border-radius:8px;font-size:12px;}"
            "QComboBox:hover{border-color:rgba(255,150,170,.35);}"
            "QComboBox QAbstractItemView{background:rgba(20,15,30,.95);color:#ccc;"
            "border:1px solid rgba(255,255,255,.1);selection-background-color:rgba(255,150,170,.25);}")
        inner.addWidget(l2d_widget, 1)

        # "应用到主界面" 按钮
        apply_btn = QPushButton("应用到主界面")
        apply_btn.setStyleSheet("QPushButton{font-family:'Microsoft YaHei';font-size:13px;"
            "padding:8px 20px;border-radius:14px;border:none;"
            "background:rgba(255,150,170,.18);color:#ffb7c5;}"
            "QPushButton:hover{background:rgba(255,150,170,.35);}")
        apply_btn.clicked.connect(lambda: self._apply_live2d_model(l2d_widget))
        inner.addWidget(apply_btn)

        outer.addWidget(container)

        def _press(e):
            if e.button() == Qt.LeftButton:
                dlg._dp = e.globalPos() - dlg.frameGeometry().topLeft()
        def _move(e):
            if e.buttons() == Qt.LeftButton and hasattr(dlg, '_dp'):
                dlg.move(e.globalPos() - dlg._dp)
        container.mousePressEvent = _press; container.mouseMoveEvent = _move

        self._l2d_dlg = dlg
        dlg.show()

    def _show_tts_log_window(self):
        if self._tts_log_window and self._tts_log_window.isVisible():
            self._tts_log_window.raise_()
            return
        text = "\n".join(self._tts_server_logs) if self._tts_server_logs else "暂无日志"
        dlg = QDialog(self)
        dlg.setWindowTitle("TTS服务器日志")
        dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        dlg.setAttribute(Qt.WA_TranslucentBackground)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.setGeometry(150, 80, 900, 700)
        dlg.setStyleSheet("""
            QDialog { background: transparent; }
            #container {
                background: rgba(20, 15, 30, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
            QTextEdit {
                font-family: 'Consolas', 'Microsoft YaHei'; font-size: 13px; color: #c8c0d0;
                background: rgba(0,0,0,.25); border: 1px solid rgba(255,255,255,.06);
                border-radius: 10px; padding: 14px;
            }
        """)
        outer = QVBoxLayout(dlg); outer.setContentsMargins(0,0,0,0)
        container = QFrame(); container.setObjectName("container")
        inner = QVBoxLayout(container); inner.setContentsMargins(24, 0, 24, 20); inner.setSpacing(12)

        tb_layout = QHBoxLayout(); tb_layout.setContentsMargins(0, 10, 4, 10)
        tl = QLabel("  TTS服务器日志")
        tl.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        tl.setStyleSheet("color: #ffb7c5;")
        tb_layout.addWidget(tl); tb_layout.addStretch()
        cb = QPushButton("x"); cb.setFixedSize(32,32)
        cb.setStyleSheet("QPushButton{background:rgba(255,255,255,.05);color:rgba(255,255,255,.4);"
            "border-radius:16px;font-size:18px;}QPushButton:hover{background:rgba(200,60,60,.4);color:#fff;}")
        cb.clicked.connect(dlg.close); tb_layout.addWidget(cb)
        inner.addLayout(tb_layout)

        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255, 255, 255, .08);")
        inner.addWidget(line)

        te = QTextEdit(); te.setReadOnly(True); te.setPlainText(text)
        te.setMinimumHeight(520); inner.addWidget(te)
        outer.addWidget(container)

        # 非模态：用 show() 不阻塞主窗口
        self._tts_log_window = dlg
        dlg.destroyed.connect(lambda: setattr(self, '_tts_log_window', None))
        dlg.show()

        def _press(e):
            if e.button() == Qt.LeftButton:
                dlg._dp = e.globalPos() - dlg.frameGeometry().topLeft()
        def _move(e):
            if e.buttons() == Qt.LeftButton and hasattr(dlg, '_dp'):
                dlg.move(e.globalPos() - dlg._dp)
        container.mousePressEvent = _press; container.mouseMoveEvent = _move

    def _show_llm_log(self):
        if hasattr(self, '_llm_log_dlg') and self._llm_log_dlg and self._llm_log_dlg.isVisible():
            self._llm_log_dlg.raise_()
            return
        lines = []
        if not self._llm_logs:
            lines = ["暂无对话记录"]
        for i, log in enumerate(self._llm_logs):
            user = log["user"]
            resp = log["response"]
            lines.append(f"--- [{i+1}] 用户 ---\n{user}")
            lines.append(f"--- [{i+1}] 八重樱 ---\n{resp}\n")
        text = "\n".join(lines)

        dlg = QDialog(self)
        dlg.setWindowTitle("LLM对话日志")
        dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        dlg.setAttribute(Qt.WA_TranslucentBackground)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.setGeometry(150, 80, 900, 700)
        dlg.setStyleSheet("""
            QDialog { background: transparent; }
            #container {
                background: rgba(20, 15, 30, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
            QTextEdit {
                font-family: 'Microsoft YaHei'; font-size: 13px; color: #d0c8d8;
                background: rgba(0,0,0,.25); border: 1px solid rgba(255,255,255,.06);
                border-radius: 10px; padding: 14px;
                selection-background-color: rgba(255,150,170,.25);
            }
        """)

        outer = QVBoxLayout(dlg); outer.setContentsMargins(0,0,0,0)
        container = QFrame(); container.setObjectName("container")
        inner = QVBoxLayout(container); inner.setContentsMargins(24, 0, 24, 20); inner.setSpacing(12)

        # 标题栏
        tb_layout = QHBoxLayout(); tb_layout.setContentsMargins(0, 10, 4, 10)
        tl = QLabel("  LLM对话日志")
        tl.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        tl.setStyleSheet("color: #ffb7c5;")
        tb_layout.addWidget(tl); tb_layout.addStretch()
        cb = QPushButton("x"); cb.setFixedSize(32,32)
        cb.setStyleSheet("QPushButton{background:rgba(255,255,255,.05);color:rgba(255,255,255,.4);"
            "border-radius:16px;font-size:18px;}QPushButton:hover{background:rgba(200,60,60,.4);color:#fff;}")
        cb.clicked.connect(dlg.close); tb_layout.addWidget(cb)
        inner.addLayout(tb_layout)

        # 分隔线
        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255, 255, 255, .08);")
        inner.addWidget(line)

        te = QTextEdit(); te.setReadOnly(True); te.setPlainText(text)
        te.setMinimumHeight(520)
        inner.addWidget(te)
        outer.addWidget(container)

        # 拖拽
        def _press(e):
            if e.button() == Qt.LeftButton:
                dlg._dp = e.globalPos() - dlg.frameGeometry().topLeft()
        def _move(e):
            if e.buttons() == Qt.LeftButton and hasattr(dlg, '_dp'):
                dlg.move(e.globalPos() - dlg._dp)
        container.mousePressEvent = _press; container.mouseMoveEvent = _move
        dlg.destroyed.connect(lambda: setattr(self, '_llm_log_dlg', None))
        self._llm_log_dlg = dlg
        dlg.show()

    def _toggle_memory_pause(self):
        self._memory_paused = not self._memory_paused
        if self._memory_paused:
            self._set_btn("btn-memory-pause", "记忆暂停中", "rgba(200,80,80,.12)", "#d08080")
        else:
            self._set_btn("btn-memory-pause", "记忆录制中", "rgba(80,180,80,.12)", "#60d060")

    def _show_settings(self):
        if hasattr(self, '_settings_dlg') and self._settings_dlg and self._settings_dlg.isVisible():
            self._settings_dlg.raise_()
            return

        cfg = load_config()
        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        dlg.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        dlg.setAttribute(Qt.WA_TranslucentBackground)
        dlg.setGeometry(350, 250, 400, 280)
        dlg.setStyleSheet("""
            QDialog { background: transparent; }
            #container {
                background: rgba(20, 15, 30, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
            QLabel { color: rgba(255,255,255,.5); font-family: 'Microsoft YaHei'; font-size: 13px; }
            QSpinBox {
                padding: 8px 12px; background: rgba(0,0,0,.25); color: #ccc;
                border: 1px solid rgba(255,255,255,.1); border-radius: 8px;
                font-family: 'Microsoft YaHei'; font-size: 13px;
            }
            QSpinBox:focus { border-color: rgba(255,150,170,.35); }
        """)

        outer = QVBoxLayout(dlg); outer.setContentsMargins(0,0,0,0)
        container = QFrame(); container.setObjectName("container")
        inner = QVBoxLayout(container); inner.setContentsMargins(24, 0, 24, 20); inner.setSpacing(14)

        # 标题栏
        tb_layout = QHBoxLayout(); tb_layout.setContentsMargins(0, 10, 4, 10)
        tl = QLabel("  设置")
        tl.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        tl.setStyleSheet("color: #ffb7c5;")
        tb_layout.addWidget(tl); tb_layout.addStretch()
        cb = QPushButton("x"); cb.setFixedSize(32,32)
        cb.setStyleSheet("QPushButton{background:rgba(255,255,255,.05);color:rgba(255,255,255,.4);"
            "border-radius:16px;font-size:18px;}QPushButton:hover{background:rgba(200,60,60,.4);color:#fff;}")
        cb.clicked.connect(dlg.close); tb_layout.addWidget(cb)
        inner.addLayout(tb_layout)

        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255, 255, 255, .08);")
        inner.addWidget(line)

        # 自动回复间隔
        row = QHBoxLayout(); row.setSpacing(12)
        row.addWidget(QLabel("自动回复触发时间"))
        spin = QSpinBox()
        spin.setRange(1, 60)
        spin.setSuffix(" 分钟")
        cur_minutes = cfg.get("idle_timeout_minutes", 5)
        spin.setValue(cur_minutes)
        row.addWidget(spin)
        inner.addLayout(row)

        inner.addWidget(QLabel("长时间无交互后八重樱会自动发起对话"))
        inner.addStretch()

        # 保存
        def on_save():
            new_cfg = load_config()
            new_cfg["idle_timeout_minutes"] = spin.value()
            save_config(new_cfg)
            self._idle_timeout_ms = spin.value() * 60 * 1000
            self._start_idle_timer()
            dlg.close()

        save_btn = QPushButton("保存")
        save_btn.setStyleSheet("QPushButton{font-family:'Microsoft YaHei';font-size:13px;"
            "padding:10px 28px;border-radius:14px;border:none;"
            "background:rgba(255,150,170,.22);color:#ffb7c5;}"
            "QPushButton:hover{background:rgba(255,150,170,.4);}")
        save_btn.clicked.connect(on_save)
        inner.addWidget(save_btn)

        outer.addWidget(container)

        def _press(e):
            if e.button() == Qt.LeftButton:
                dlg._dp = e.globalPos() - dlg.frameGeometry().topLeft()
        def _move(e):
            if e.buttons() == Qt.LeftButton and hasattr(dlg, '_dp'):
                dlg.move(e.globalPos() - dlg._dp)
        container.mousePressEvent = _press; container.mouseMoveEvent = _move

        dlg.destroyed.connect(lambda: setattr(self, '_settings_dlg', None))
        self._settings_dlg = dlg
        dlg.show()

    def _select_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if path:
            self._pending_image = path
            self._run_js("document.getElementById('img-btn').classList.add('active')")

    def _describe_pending_image(self, img_path):
        """调千问VL模型识别图片，返回文字描述"""
        try:
            from need.vision.image_understand import describe_image
            qwen_key = load_env().get("qwen", "")
            if not qwen_key:
                return "（千问API Key未配置，无法识别图片内容）"
            return describe_image(qwen_key, img_path) or "（图片无法识别）"
        except Exception:
            return "（识图失败）"

    def _toggle_camera_window(self):
        if self.camera_window:
            if self.camera_window.isVisible(): self.camera_window.hide()
            else: self.camera_window.show()

    def _on_user_arrived(self):
        self._start_idle_timer()
        if self.is_waiting_response: return
        self._send_auto(random.choice(RETURN_MSGS))

    def _on_user_left(self): self._stop_idle_timer()

    def _on_frame_captured(self, frame):
        if self.camera_window and self.camera_window.isVisible():
            self.camera_window.set_frame(frame)

    def _on_expression_changed(self, exp):
        self._user_expression = exp
        emoji_map = {"微笑": "😊", "大笑": "😄", "平静": "😐", "悲伤": "😢"}
        emoji = emoji_map.get(exp, "")
        esc = f"{emoji} {exp}".replace("\\", "\\\\").replace("'", "\\'")
        self._run_js(
            f"(function(){{var e=document.getElementById('vision-text');if(e)e.textContent='{esc}';}})();")

    def _start_idle_timer(self): self._idle_timer.start(self._idle_timeout_ms)
    def _stop_idle_timer(self): self._idle_timer.stop()

    def _on_idle_timeout(self):
        if self.is_waiting_response: self._start_idle_timer(); return
        self._send_auto(random.choice(AUTO_MSGS))

    def _set_input(self, enabled):
        v = "false" if enabled else "true"
        self._run_js(
            f"(function(){{var e=document.getElementById('msg-input');if(e)e.disabled={v};"
            f"e=document.getElementById('send-btn');if(e)e.disabled={v};}})();")

    def _set_mouth_open(self, value):
        self._run_js(f"setMouthOpen({value})")

    def _run_js(self, code):
        try:
            self.view.page().runJavaScript(code)
        except Exception as e:
            logger.error(f"JS错误: {e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'view'):
            self.view.setGeometry(0, 0, self.width(), self.height())

    def closeEvent(self, event):
        if self.is_waiting_response:
            self._do_close()
            event.accept()
        else:
            # 本轮有过对话才更新时间戳，否则保持上次的离开时间
            if getattr(self, '_has_chatted', False):
                try:
                    with open("data/last_leave.txt", "w") as f:
                        f.write(str(time.time()))
                except Exception:
                    pass
            self._do_close()
            event.accept()

    def _do_close(self):
        self._stop_idle_timer()
        self._poll_timer.stop()
        if self.camera_window:
            self.camera_window.hide()
        if self.vision_manager and self._vision_running: self.vision_manager.stop()
        if self._tts_server_process:
            try:
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self._tts_server_process.pid)],
                               capture_output=True, timeout=5)
            except Exception:
                pass
            self._tts_server_process = None
        if self.tts_manager: self.tts_manager.cleanup()
        QApplication.quit()


if __name__ == "__main__":
    print("=" * 50, flush=True)
    print(f"八重樱·圣痕之庭 v17 | TTS:{'✓' if TTS_AVAILABLE else '✗'} "
          f"Live2D:{'✓' if LIVE2D_AVAILABLE else '✗'} "
          f"视觉:{'✓' if VISION_AVAILABLE else '✗'}", flush=True)
    print("=" * 50, flush=True)
    app = QApplication(sys.argv)
    w = SakuraWindow()
    w.show()
    sys.exit(app.exec_())
