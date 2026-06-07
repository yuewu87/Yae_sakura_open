"""
视觉管理器 — 摄像头人脸检测、表情识别、预览帧输出
MediaPipe Face Mesh（优先）→ 468 关键点 + 表情判定
OpenCV Haar Cascade（降级）→ 仅人脸存在检测
全程本地处理，不上传
"""
import threading
import time
import logging
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

logger = logging.getLogger("Sakura-Vision")

VISION_AVAILABLE = False

try:
    import cv2
    VISION_AVAILABLE = True
except ImportError:
    logger.warning("OpenCV 未安装。pip install opencv-python")

# ---- 表情判定参数 ----
SMILE_THRESHOLD = 0.35        # 嘴角宽高比 > 此值 = 微笑
LAUGH_SMILE_THRESHOLD = 0.30  # 大笑时嘴角宽高比 > 此值
LAUGH_JAW_THRESHOLD = 0.25    # 大笑时嘴部高宽比 > 此值
SAD_BROW_THRESHOLD = 0.14     # 眉-眼距/面高 > 此值 = 悲伤(内眉上扬)
SAD_MOUTH_THRESHOLD = 0.08    # 嘴角下沉量/面高 > 此值 = 悲伤


class VisionManager(QObject):

    # 存在检测
    user_arrived = pyqtSignal()
    user_left = pyqtSignal()
    user_present_changed = pyqtSignal(bool)

    # 预览帧
    frame_captured = pyqtSignal(np.ndarray)

    # 表情识别（仅 MediaPipe 模式）
    expression_changed = pyqtSignal(str)   # "微笑" / "大笑" / "悲伤" / "平静"

    def __init__(self, check_interval=3.0, debounce_frames=2, preview_fps=5):
        super().__init__()
        self.check_interval = check_interval
        self.preview_fps = max(preview_fps, 1)
        self.preview_interval = 1.0 / self.preview_fps
        self._detection_every_n = max(1, int(check_interval / self.preview_interval))

        # 不对称防抖：归来快(1帧)，离开慢(debounce_frames帧)
        self._arrival_debounce = 1
        self._departure_debounce = debounce_frames

        self._cap = None
        self._running = False
        self._thread = None
        self._user_present = False
        self._first_detection = True   # 首次检测到人脸不触发问候

        # 表情状态
        self._current_expression = "平静"
        self._expression_counter = 0
        self._expression_debounce = 5  # 连续 N 帧才切换表情

        # 检测器延迟到 start() 时初始化
        self._face_detector = None
        self._detection_mode = "none"

    def _init_mediapipe(self):
        try:
            import mediapipe as mp
            self.mp_face_mesh = mp.solutions.face_mesh
            self.mp_drawing = mp.solutions.drawing_utils
            self.mp_styles = mp.solutions.drawing_styles
        except ImportError:
            logger.info("MediaPipe 未安装，使用 OpenCV 降级模式")
            self._init_opencv()
            return
        self._face_detector = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.4,
            min_tracking_confidence=0.3,  # 降低以容忍侧脸
        )
        self._detection_mode = "mediapipe"

    def _init_opencv(self):
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._face_cascade = cv2.CascadeClassifier(cascade_path)
        self._detection_mode = "opencv"

    def start(self):
        if not VISION_AVAILABLE:
            logger.warning("视觉系统不可用")
            return
        if self._running:
            return

        # 延迟加载检测器（首次启动时）
        if self._face_detector is None and self._detection_mode == "none":
            self._init_mediapipe()
            logger.info("MediaPipe 已加载，启用表情识别")

        try:
            self._cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not self._cap.isOpened():
                logger.warning("无法打开摄像头")
                self._cap = None
                return

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            logger.info(f"视觉系统已启动（{self._detection_mode}），检测间隔 {self.check_interval}s，预览 {self.preview_fps}fps")
        except Exception as e:
            logger.warning(f"视觉系统启动失败: {e}")
            self._cap = None

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._face_detector:
            try:
                self._face_detector.close()
            except Exception:
                pass
            self._face_detector = None
        logger.info("视觉系统已停止")

    def is_user_present(self):
        return self._user_present

    # ==================== 主循环 ====================

    def _loop(self):
        consecutive_change = 0
        last_detected = self._user_present
        iteration = 0

        while self._running:
            time.sleep(self.preview_interval)
            if not self._running:
                break

            ret, frame = self._cap.read()
            if not ret or frame is None:
                continue

            if self._detection_mode == "mediapipe":
                face_found, frame = self._process_mediapipe(frame)
            else:
                face_found = self._detect_opencv(frame)

            # 预览帧
            try:
                self.frame_captured.emit(frame.copy())
            except Exception:
                pass

            # 定期检测人脸存在状态（不对称防抖）
            if iteration % self._detection_every_n == 0:
                if face_found != last_detected:
                    consecutive_change += 1
                    limit = self._departure_debounce if last_detected else self._arrival_debounce
                    if consecutive_change >= limit:
                        last_detected = face_found
                        consecutive_change = 0
                        self._on_state_changed(face_found)
                else:
                    consecutive_change = 0

            iteration += 1

    # ==================== MediaPipe 检测 + 表情 ====================

    def _process_mediapipe(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._face_detector.process(rgb)
        rgb.flags.writeable = True

        if not results.multi_face_landmarks:
            return False, frame

        landmarks = results.multi_face_landmarks[0]

        # 绘制关键点
        self.mp_drawing.draw_landmarks(
            image=frame,
            landmark_list=landmarks,
            connections=self.mp_face_mesh.FACEMESH_CONTOURS,
            landmark_drawing_spec=None,
            connection_drawing_spec=self.mp_styles.get_default_face_mesh_contours_style(),
        )

        # 表情分析
        expression = self._classify_expression(landmarks)
        self._update_expression(expression)

        return True, frame

    def _classify_expression(self, landmarks):
        """从 468 个关键点计算表情"""
        pts = landmarks.landmark

        def dist(i, j):
            return np.sqrt((pts[i].x - pts[j].x) ** 2 + (pts[i].y - pts[j].y) ** 2)

        # 嘴部指标
        mouth_width = dist(61, 291)             # 嘴角间距
        mouth_height = dist(13, 14)              # 上下唇距
        jaw_ratio = mouth_height / max(mouth_width, 0.001)
        smile_ratio = mouth_width / dist(234, 454)  # 嘴宽 / 面宽

        # 悲伤 = 内眉上扬 + 嘴角下沉
        face_height = dist(10, 152)  # 额头到下巴
        brow_raise = ((dist(66, 159) + dist(296, 386)) / 2) / max(face_height, 0.001)
        mouth_center_y = (pts[61].y + pts[291].y) / 2
        cheek_center_y = (pts[234].y + pts[454].y) / 2
        mouth_droop = (mouth_center_y - cheek_center_y) / max(face_height, 0.001)
        if brow_raise > SAD_BROW_THRESHOLD and mouth_droop > SAD_MOUTH_THRESHOLD:
            return "悲伤"

        # 大笑 = 嘴角拉开 + 嘴张大
        if smile_ratio > LAUGH_SMILE_THRESHOLD and jaw_ratio > LAUGH_JAW_THRESHOLD:
            return "大笑"
        # 微笑 = 嘴角拉开 + 嘴不张
        if smile_ratio > SMILE_THRESHOLD:
            return "微笑"
        return "平静"

    def _update_expression(self, expression):
        if expression == self._current_expression:
            self._expression_counter = 0
            return

        self._expression_counter += 1
        if self._expression_counter >= self._expression_debounce:
            self._current_expression = expression
            self._expression_counter = 0
            self.expression_changed.emit(expression)

    # ==================== OpenCV 降级检测 ====================

    def _detect_opencv(self, frame):
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
            )
            return len(faces) > 0
        except Exception:
            return False

    # ==================== 状态变化 ====================

    def _on_state_changed(self, present):
        self._user_present = present
        self.user_present_changed.emit(present)

        if present:
            if self._first_detection:
                self._first_detection = False
                logger.info("视觉系统：首次检测到用户")
                return
            logger.info("检测到用户出现")
            self.user_arrived.emit()
        else:
            logger.info("检测到用户离开")
            self.user_left.emit()
