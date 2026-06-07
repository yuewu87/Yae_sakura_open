"""
记忆管理对话框
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QTextEdit, QPushButton, QFrame, QMessageBox)
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QFont, QMouseEvent


class MemoryDialog:
    """管理记忆查看/清空对话框"""

    def __init__(self, parent, memory_manager):
        self.parent = parent
        self.memory_manager = memory_manager
        self._dlg = None

    def show(self):
        if self._dlg and self._dlg.isVisible():
            self._dlg.raise_()
            return
        if not self.memory_manager:
            QMessageBox.warning(self.parent, "记忆管理", "记忆系统未启用")
            return

        dialog = QDialog(self.parent)
        dialog.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        dialog.setAttribute(Qt.WA_TranslucentBackground)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.setGeometry(300, 200, 680, 500)
        dialog.setStyleSheet(self._dialog_style())

        # 主容器
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        container = QFrame()
        container.setObjectName("container")
        inner = QVBoxLayout(container)
        inner.setContentsMargins(24, 0, 24, 20)
        inner.setSpacing(12)

        # ---- 自定义标题栏 ----
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(0, 10, 4, 10)

        title = QLabel("  八重樱的记忆")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        title.setStyleSheet("color: #ffb7c5;")
        title_bar.addWidget(title)
        title_bar.addStretch()

        close_btn = QPushButton("×")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,.05);color:rgba(255,255,255,.4);"
            "border-radius:16px;font-size:18px;padding:0;}"
            "QPushButton:hover{background:rgba(200,60,60,.4);color:#fff;}")
        close_btn.clicked.connect(dialog.close)
        title_bar.addWidget(close_btn)
        inner.addLayout(title_bar)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255,255,255,.08);")
        inner.addWidget(line)

        # 统计标签
        stats_lbl = QLabel()
        stats_lbl.setFont(QFont("Microsoft YaHei", 10))
        stats_lbl.setStyleSheet("color: rgba(255,255,255,.35); padding: 2px 0;")
        stats_lbl.setText(self._get_stats())
        inner.addWidget(stats_lbl)

        # 记忆内容
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setMinimumHeight(280)
        text_edit.setText(self._get_memory_info())
        inner.addWidget(text_edit)

        # 按钮区
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        clear_btn = QPushButton("清空记忆")
        clear_btn.setStyleSheet(self._btn_style("danger"))
        clear_btn.clicked.connect(lambda: self._clear(dialog))

        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(self._btn_style("secondary"))
        refresh_btn.clicked.connect(lambda: (
            text_edit.setText(self._get_memory_info()),
            stats_lbl.setText(self._get_stats())
        ))

        confirm_btn = QPushButton("关闭")
        confirm_btn.setStyleSheet(self._btn_style("primary"))
        confirm_btn.clicked.connect(dialog.close)

        btn_layout.addStretch()
        btn_layout.addWidget(refresh_btn)
        btn_layout.addWidget(clear_btn)
        btn_layout.addWidget(confirm_btn)
        inner.addLayout(btn_layout)

        outer.addWidget(container)

        # 拖拽移动
        def mouse_press(e: QMouseEvent):
            if e.button() == Qt.LeftButton:
                dialog._drag_pos = e.globalPos() - dialog.frameGeometry().topLeft()

        def mouse_move(e: QMouseEvent):
            if e.buttons() == Qt.LeftButton and hasattr(dialog, '_drag_pos'):
                dialog.move(e.globalPos() - dialog._drag_pos)

        container.mousePressEvent = mouse_press
        container.mouseMoveEvent = mouse_move

        dialog.destroyed.connect(lambda: setattr(self, '_dlg', None))
        self._dlg = dialog
        dialog.show()

    def _get_stats(self):
        try:
            from need.memory.vault import get_all_memories
            n_vault = len(get_all_memories())
            n_rounds = self.memory_manager.total_rounds
            return f"Vault: {n_vault} 条 | 对话: {n_rounds} 轮"
        except Exception:
            return ""

    def _get_memory_info(self):
        try:
            return self.memory_manager.get_formatted_entities()
        except Exception as e:
            return f"获取记忆信息时发生错误:\n{str(e)}"

    def _clear(self, dialog):
        self.memory_manager.clear_memory()
        try:
            from need.memory.vault import clear_vault
            clear_vault()
        except Exception:
            pass
        QMessageBox.information(self.parent, "记忆管理", "八重樱的记忆已清空")
        dialog.close()

    @staticmethod
    def _dialog_style():
        return """
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
        """

    @staticmethod
    def _btn_style(kind):
        base = ("QPushButton{font-family:'Microsoft YaHei';font-size:13px;"
                "padding:8px 22px;border-radius:16px;border:none;}")
        if kind == "primary":
            return base + (
                "QPushButton{background:rgba(255,150,170,.22);color:#ffb7c5;}"
                "QPushButton:hover{background:rgba(255,150,170,.4);}")
        elif kind == "danger":
            return base + (
                "QPushButton{background:rgba(200,80,80,.18);color:#e08080;}"
                "QPushButton:hover{background:rgba(200,80,80,.35);}")
        else:
            return base + (
                "QPushButton{background:rgba(255,255,255,.06);color:rgba(255,255,255,.5);}"
                "QPushButton:hover{background:rgba(255,255,255,.12);color:#ddd;}")
