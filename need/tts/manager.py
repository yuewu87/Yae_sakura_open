"""
TTS 管理器 — WebSocket 客户端管理 + 语音合成请求 + 音频播放 + 口型同步 + UI 状态更新
"""
import os
import threading
import time
import logging
import numpy as np
import soundfile as sf
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from TTS_GPT_SoVITS.tts_config import TTS_CONFIG

logger = logging.getLogger("Sakura-TTS")

TTS_AVAILABLE = False
try:
    from TTS_GPT_SoVITS.tts_websocket_client import TTSWebSocketClient, TTSClientStatus
    TTS_AVAILABLE = True
except ImportError:
    pass


class TTSManager(QObject):

    # 对外信号
    connection_changed = pyqtSignal(bool)
    mouth_open = pyqtSignal(float)  # 0.0~1.0，驱动 Live2D 口型

    # 内部信号（跨线程 → 主线程 UI 更新）
    _status_update = pyqtSignal(str)
    _show_pending = pyqtSignal(str)
    _show_ready = pyqtSignal(str, str, float)
    _show_error = pyqtSignal(str, str)

    def __init__(self, chat_display, status_label, tts_status_label, media_player):
        super().__init__()
        self.chat_display = chat_display
        self.status_label = status_label
        self.tts_status_label = tts_status_label
        self.media_player = media_player

        self.tts_client = None
        self.tts_connected = False
        self.pending_tts_tasks = {}
        self._play_queue = []
        self._current_msg_id = None

        # 口型同步
        self._lip_timer = QTimer(self)
        self._lip_timer.timeout.connect(self._on_lip_tick)
        self._lip_envelope = []     # [(time_ms, energy), ...]
        self._lip_play_start = 0    # 播放开始时的 time.perf_counter() ms

        # 内部信号 → 主线程 slot（UI 更新都在主线程执行）
        self._status_update.connect(self._update_status)
        self._show_pending.connect(self._do_show_tts_pending)
        self._show_ready.connect(self._do_show_audio_ready)
        self._show_error.connect(self._do_show_tts_error)

        if TTS_AVAILABLE:
            self._init_client()

    # ==================== 初始化 ====================

    def _init_client(self):
        try:
            self.tts_client = TTSWebSocketClient(
                server_url="ws://localhost:8770",
                http_base_url="http://localhost:8005",
                auto_reconnect=True,
                reconnect_interval=5
            )

            self.tts_client.on_connected = self._on_connected
            self.tts_client.on_disconnected = self._on_disconnected
            self.tts_client.on_task_completed = self._on_task_completed
            self.tts_client.on_task_failed = self._on_task_failed
            self.tts_client.on_error = self._on_error

            self.tts_client.connect()
            threading.Thread(target=self._wait_for_connection, daemon=True).start()
            logger.info("TTS客户端初始化完成")
        except Exception as e:
            logger.error(f"初始化TTS客户端失败: {e}")

    def _wait_for_connection(self):
        for _ in range(50):
            if self.tts_client and self.tts_client.is_connected():
                self.tts_connected = True
                break
            time.sleep(0.1)
        if not self.tts_connected:
            logger.warning("TTS客户端连接超时")

    # ==================== WebSocket 回调（后台线程） — 只发射信号 ====================

    def _on_connected(self, client_id):
        self.tts_connected = True
        self.connection_changed.emit(True)
        self._status_update.emit("圣痕空间·语音服务已就绪")

    def _on_disconnected(self):
        self.tts_connected = False
        self.connection_changed.emit(False)
        self._status_update.emit("圣痕空间·语音服务断开")
        logger.debug("TTS客户端断开回调")

    def _on_task_completed(self, task_id, audio_url, duration, data):
        if task_id in self.pending_tts_tasks:
            message_id = self.pending_tts_tasks.pop(task_id)
            self._show_ready.emit(message_id, audio_url, duration)

    def _on_task_failed(self, task_id, error_msg, data):
        if task_id in self.pending_tts_tasks:
            message_id = self.pending_tts_tasks.pop(task_id)
            self._show_error.emit(message_id, error_msg)

    def _on_error(self, error_code, error_msg, data):
        logger.error(f"TTS服务错误: {error_code} - {error_msg}")
        self._status_update.emit(f"语音服务异常: {error_code}")

    # ==================== 公开方法（主线程调用） ====================

    def synthesize(self, text, message_id):
        if not TTS_AVAILABLE or not self.tts_connected or not self.tts_client:
            return
        if message_id != self._current_msg_id:
            self._play_queue.clear()
            self.media_player.stop()
            self._stop_lip_sync()
            self._current_msg_id = message_id
        try:
            tts_task_id = self.tts_client.synthesize_speech(
                text=text,
                ref_audio_path=TTS_CONFIG["default_ref_audio_path"],
                ref_text=TTS_CONFIG["default_ref_text"]
            )

            if tts_task_id:
                self.pending_tts_tasks[tts_task_id] = message_id
                self._do_show_tts_pending(message_id)
            else:
                self._do_show_tts_error(message_id, "请求发送失败")
        except Exception as e:
            self._do_show_tts_error(message_id, str(e))

    def stop_playback(self):
        """打断：渐弱后停止播放 + 清空播放队列"""
        self._stop_lip_sync()
        self._play_queue.clear()
        self._saved_volume = self.media_player.volume()
        self._fade_count = 5
        self._fade_timer = QTimer()
        self._fade_timer.timeout.connect(self._fade_step)
        self._fade_timer.start(30)

    def _fade_step(self):
        self._fade_count -= 1
        if self._fade_count <= 0 or self.media_player.state() != QMediaPlayer.PlayingState:
            self.media_player.stop()
            self._fade_timer.stop()
            self.pending_tts_tasks.clear()
            self.media_player.setVolume(getattr(self, '_saved_volume', 100))
            logger.info("TTS播放已打断")
        else:
            vol = max(0, self.media_player.volume() - 20)
            self.media_player.setVolume(vol)

    def cleanup(self):
        self._stop_lip_sync()
        self._play_queue.clear()
        if self.tts_client:
            try:
                self.tts_client.cleanup()
            except Exception:
                pass
            self.tts_client = None
            logger.info("TTS客户端已清理")

    # ==================== UI 更新（这些 slot 在主线程执行） ====================

    def _do_show_tts_pending(self, message_id):
        logger.debug(f"TTS合成中: msg={message_id}")

    def _do_show_audio_ready(self, message_id, audio_url, duration):
        logger.info(f"TTS合成完成: msg={message_id} 时长={duration:.1f}s")
        filename = audio_url.rsplit("/", 1)[-1]
        local_path = os.path.join(TTS_CONFIG["output_dir"], filename)
        if os.path.exists(local_path):
            play_url = "file:///" + local_path.replace("\\", "/")
        else:
            play_url = audio_url
        # 正在播放中 → 加入播放队列
        if self.media_player.state() == QMediaPlayer.PlayingState:
            self._play_queue.append((play_url, duration))
            return
        self._analyze_audio_envelope(audio_url)
        self.media_player.setMedia(QMediaContent(QUrl(play_url)))
        self.media_player.play()
        self._start_lip_sync()
        try:
            self.media_player.stateChanged.disconnect()
        except Exception:
            pass
        self.media_player.stateChanged.connect(self._on_playback_state_changed)

    def _do_show_tts_error(self, message_id, error_msg):
        logger.error(f"TTS合成失败: msg={message_id} error={error_msg[:100]}")

    # ==================== 口型同步 ====================

    def _analyze_audio_envelope(self, audio_url):
        """从 WAV 文件预分析能量包络"""
        self._lip_envelope = []
        try:
            # URL → 本地路径
            filename = audio_url.rsplit("/", 1)[-1]
            local_path = os.path.join(TTS_CONFIG["output_dir"], filename)
            if not os.path.exists(local_path):
                logger.warning(f"音频文件不存在，无法分析口型: {local_path}")
                return

            audio, sr = sf.read(local_path, dtype="float32")
            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)

            window_ms = 33       # ~30fps
            window_samples = int(sr * window_ms / 1000)
            hop_samples = window_samples  # 不重叠

            raw_envelope = []
            for i in range(0, len(audio) - window_samples, hop_samples):
                chunk = audio[i : i + window_samples]
                rms = np.sqrt(np.mean(chunk ** 2))
                raw_envelope.append(rms)

            if not raw_envelope:
                return

            # RMS 归一化 + EMA 平滑
            raw_envelope = np.array(raw_envelope)
            max_rms = np.max(raw_envelope)
            if max_rms > 1e-8:
                raw_envelope = raw_envelope / max_rms

            smoothed = raw_envelope.copy()
            alpha = 0.45  # EMA 平滑系数
            for i in range(1, len(smoothed)):
                smoothed[i] = alpha * raw_envelope[i] + (1 - alpha) * smoothed[i - 1]

            # 生成 (time_ms, energy) 包络表
            for i, energy in enumerate(smoothed):
                t_ms = i * window_ms
                self._lip_envelope.append((t_ms, float(energy)))

            logger.debug(f"口型包络分析完成: {len(self._lip_envelope)} 帧")

        except Exception as e:
            logger.warning(f"音频包络分析失败: {e}")

    def _start_lip_sync(self):
        import time as _time
        self._lip_play_start = _time.perf_counter() * 1000
        self._lip_timer.start(33)

    def _on_lip_tick(self):
        import time as _time
        elapsed = _time.perf_counter() * 1000 - self._lip_play_start

        # 二分查找当前时间对应的能量值
        if not self._lip_envelope:
            return

        target_energy = 0.0
        lo, hi = 0, len(self._lip_envelope) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            t, energy = self._lip_envelope[mid]
            if t <= elapsed:
                target_energy = energy
                lo = mid + 1
            else:
                hi = mid - 1

        # 非线性映射 + 静音阈值
        target_energy = max(0, min(1, target_energy))
        threshold = 0.02
        if target_energy < threshold:
            target_energy = 0.0
        else:
            target_energy = (target_energy - threshold) / (1 - threshold)
            target_energy = target_energy ** 0.55  # 非线性，小音量也有可见开合

        self.mouth_open.emit(target_energy)

    def _stop_lip_sync(self):
        self._lip_timer.stop()
        self.mouth_open.emit(0.0)

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.StoppedState:
            self._stop_lip_sync()
            if self._play_queue:
                play_url, duration = self._play_queue.pop(0)
                self._analyze_audio_envelope(play_url)
                self.media_player.setMedia(QMediaContent(QUrl(play_url)))
                self.media_player.play()
                self._start_lip_sync()
            else:
                self._update_status("圣痕空间·待机中")

    # ==================== 辅助 ====================

    def _run_js(self, code):
        try:
            self.chat_display.page().runJavaScript(code)
        except Exception as e:
            logger.error(f"JavaScript执行错误: {e}")

    def _update_status(self, text):
        if self.status_label:
            self.status_label.setText(text)
