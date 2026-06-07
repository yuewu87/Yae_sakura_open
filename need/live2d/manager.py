"""
独立Live2D展示组件
用于在PyQt5应用中展示Live2D模型
"""

import os
import sys
import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QMessageBox
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFont
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings

logger = logging.getLogger("Sakura-Live2D")

class Live2DWidget(QWidget):
    """独立的Live2D模型展示组件"""
    
    def __init__(self, parent=None, model_dir=None, default_size=(480, 600)):
        """
        初始化Live2D组件
        
        Args:
            parent: 父组件
            model_dir: Live2D模型目录路径
            default_size: 默认显示尺寸 (宽度, 高度)
        """
        super().__init__(parent)
        
        # 配置参数
        self.model_dir = model_dir or "E:/Study_Projects/yuewu_bachong/data/live2d_models"
        self.default_width, self.default_height = default_size
        self.model_options = {}  # 存储模型名称和路径的映射
        self.current_model_path = None
        
        # 初始化UI
        self.init_ui()
        
        # 扫描模型目录
        self.scan_live2d_models()
        
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("Live2D模型展示")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                color: white;
                padding: 10px;
                background-color: #ff6b8b;
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.3);
            }
        """)
        layout.addWidget(title_label)
        
        # 模型选择下拉列表
        self.model_combo = QComboBox()
        self.model_combo.setFont(QFont("Microsoft YaHei", 10))
        self.model_combo.setFixedHeight(35)
        self.model_combo.setStyleSheet("""
            QComboBox {
                background: rgba(255, 255, 255, 0.9);
                border: 2px solid #ff6b8b;
                border-radius: 20px; /* 主组件圆角 */
                padding: 5px 20px;
                selection-background-color: #ffb7c5;
            }
            QComboBox:hover {
                border-color: #ff8a9e;
                background: white;
            }
            QComboBox::drop-down {
                border: none;
                border-radius: 0 20px 20px 0; /* 下拉按钮右半部分圆角 */
                background: transparent;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ff6b8b;
                margin-right: 10px;
            }
            QComboBox::down-arrow:on {
                border-top: none;
                border-bottom: 5px solid #ff6b8b;
            }
            /* 下拉列表框的样式 */
            QComboBox QAbstractItemView {
                border: 2px solid #ff6b8b;
                border-radius: 10px; /* 下拉列表框圆角 */
                background: white;
                selection-background-color: #ffb7c5;
            }
        """)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        
        layout.addWidget(self.model_combo)
        
        # Live2D显示容器
        self.live2d_container = QWidget()
        self.live2d_container.setStyleSheet("""
            QWidget {
                background-color: linear-gradient(135deg, #667eea 0%, #764ba2 100%);;
                border-radius: 15px;
                border: 3px solid rgba(255, 255, 255, 0.3);
            }
        """)
        
        container_layout = QVBoxLayout(self.live2d_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建WebEngineView用于显示Live2D模型
        self.live2d_view = QWebEngineView()
        self.live2d_view.setFixedSize(self.default_width, self.default_height)
        self.live2d_view.setStyleSheet("border: none; border-radius: 12px;")
        self.live2d_view.setContextMenuPolicy(Qt.NoContextMenu)
        
        # 设置WebEngine支持本地文件访问
        self.live2d_view.settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessFileUrls, True
        )
        self.live2d_view.settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessRemoteUrls, True
        )
        
        container_layout.addWidget(self.live2d_view)
        
        layout.addWidget(self.live2d_container, 1)
        
        # 初始化时显示占位符
        self.show_fallback_image()
    
    def scan_live2d_models(self):
        """扫描Live2D模型目录"""
        try:
            if not os.path.exists(self.model_dir):
                logger.warning(f"Live2D模型目录不存在: {self.model_dir}")
                return
            
            # 清空现有选项（阻止信号避免重复加载）
            self.model_combo.blockSignals(True)
            self.model_combo.clear()
            self.model_options.clear()

            # 获取所有子目录
            for item in os.listdir(self.model_dir):
                item_path = os.path.join(self.model_dir, item)
                if os.path.isdir(item_path):
                    # 检查目录中是否有.model3.json文件
                    for file in os.listdir(item_path):
                        if file.endswith('.model3.json'):
                            self.model_options[item] = item_path
                            self.model_combo.addItem(item)
                            logger.debug(f"找到Live2D模型: {item}")
                            break
            
            if not self.model_options:
                logger.warning("未找到Live2D模型")
                self.model_combo.addItem("无可用模型")
            else:
                # 优先加载八重樱，否则加载第一个
                self.model_combo.blockSignals(False)
                default_model = "八重樱" if "八重樱" in self.model_options else list(self.model_options.keys())[0]
                self.model_combo.setCurrentText(default_model)
                self.load_live2d_model(default_model)
                
        except Exception as e:
            logger.error(f"扫描Live2D模型时出错: {e}")
            self.model_combo.addItem("扫描失败")
    
    def load_live2d_model(self, model_name):
        """加载Live2D模型"""
        if model_name not in self.model_options:
            logger.warning(f"模型 '{model_name}' 不存在")
            self.show_fallback_image()
            return
        
        model_path = self.model_options[model_name]
        self.current_model_path = model_path
        
        # 查找模型JSON文件
        model_json_file = None
        for file in os.listdir(model_path):
            if file.endswith('.model3.json'):
                model_json_file = file
                break
        
        if not model_json_file:
            logger.warning(f"在模型目录中未找到.model3.json文件: {model_path}")
            self.show_fallback_image()
            return
        
        # 构建完整的文件路径
        model_file_url = f"file:///{model_path}/{model_json_file}".replace('\\', '/')
        
        # 创建HTML内容
        html_content = self.create_live2d_html(model_file_url)
        
        # 设置HTML内容
        self.live2d_view.setHtml(html_content, QUrl("file:///"))
        
        logger.debug(f"已加载Live2D模型: {model_name}")
    
    def create_live2d_html(self, model_file_url):
        """创建Live2D模型显示的HTML页面"""
        # 使用本地 libs 目录，避免 CDN 加载失败
        libs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "libs"))
        libs_url = f"file:///{libs_dir}".replace("\\", "/")

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    width: 100%;
                    height: 100%;
                    background: transparent;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    overflow: hidden;
                }}

                #canvas {{
                    width: 100%;
                    height: 100%;
                    position: absolute;
                    left: 0;
                    top: 0;
                    background: transparent;
                }}
                
                .loading {{
                    position: absolute;
                    color: #ff6b8b;
                    font-family: 'Microsoft YaHei', Arial, sans-serif;
                    font-size: 16px;
                    z-index: 10;
                    background: rgba(255, 255, 255, 0.9);
                    padding: 10px 20px;
                    border-radius: 20px;
                    box-shadow: 0 2px 10px rgba(255, 107, 139, 0.3);
                }}
            </style>
            <!-- Live2D依赖库（本地文件） -->
            <script src="{libs_url}/live2dcubismcore.min.js"></script>
            <script src="{libs_url}/live2d.min.js"></script>
            <script src="{libs_url}/pixi.min.js"></script>
            <script src="{libs_url}/index.min.js"></script>
        </head>
        <body>
            <canvas id="canvas"></canvas>
            
            <script>
                // 全局变量：供外部 setMouthOpen 调用
                var g_model = null;
                var g_animFrame = null;

                (async function main() {{
                    try {{
                        // 等待所有库加载完成
                        if (typeof PIXI === 'undefined') {{
                            console.error('PIXI.js未加载');
                            return;
                        }}

                        if (!PIXI.live2d) {{
                            console.error('pixi-live2d-display未加载');
                            return;
                        }}

                        // 创建PIXI应用
                        const app = new PIXI.Application({{
                            view: document.getElementById('canvas'),
                            width: {self.default_width},
                            height: {self.default_height},
                            transparent: true,
                            autoStart: true,
                            backgroundAlpha: 0
                        }});

                        console.log('正在加载模型:', '{model_file_url}');

                        // 加载Live2D模型
                        const model = await PIXI.live2d.Live2DModel.from('{model_file_url}');

                        // 模型居中偏下（适配沉浸式全屏布局）
                        model.x = app.screen.width * 0.15;
                        model.y = app.screen.height * 0.05;

                        // 计算合适的缩放比例
                        const scale = Math.min(
                            app.screen.width / model.width * 1.5,
                            app.screen.height / model.height * 1.5
                        );
                        model.scale.set(scale);

                        // 添加到舞台
                        app.stage.addChild(model);

                        // 保存全局引用
                        g_model = model;

                        console.log('模型加载成功！');

                        // 尝试播放空闲动作
                        if (model.internalModel && model.internalModel.motionManager) {{
                            try {{
                                const motionGroups = model.internalModel.motionManager.motionGroups;
                                if (motionGroups && motionGroups.idle && motionGroups.idle.length > 0) {{
                                    model.motion('idle', 0);
                                }}
                            }} catch (motionError) {{
                                console.warn('无法播放动作:', motionError);
                            }}
                        }}

                    }} catch (error) {{
                        console.error('加载Live2D模型失败:', error);
                    }}
                }})();

                // 口型同步函数：外部通过 runJavaScript 调用
                // value: 0.0(闭嘴) ~ 1.0(全开)
                var _mouth_target = 0;
                var _mouth_current = 0;
                var _mouth_smooth = 0.35;  // 平滑系数(越小越平滑)

                function setMouthOpen(value) {{
                    _mouth_target = Math.max(0, Math.min(1, Number(value) || 0));
                    if (g_animFrame === null) {{
                        _tickMouth();
                    }}
                }}

                function _tickMouth() {{
                    // EMA 平滑逼近目标值
                    _mouth_current += (_mouth_target - _mouth_current) * _mouth_smooth;

                    // 微小值归零，避免不必要的更新
                    if (_mouth_current < 0.005) _mouth_current = 0;

                    if (g_model && g_model.internalModel) {{
                        try {{
                            g_model.internalModel.coreModel.setParameterValueById(
                                'ParamMouthOpenY', _mouth_current
                            );
                        }} catch(e) {{}}
                    }}

                    // 如果目标为0且当前已接近0，停止循环
                    if (_mouth_target === 0 && _mouth_current < 0.001) {{
                        g_animFrame = null;
                        return;
                    }}

                    g_animFrame = requestAnimationFrame(_tickMouth);
                }}
            </script>
        </body>
        </html>
        """
        return html
    
    def show_fallback_image(self):
        """显示降级图片"""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    width: 100%;
                    height: 100%;
                    background: linear-gradient(135deg, #ffb7c5 0%, #ff9aac 100%); /* 与主界面一致的粉色渐变 */
                    display: flex;
                    justify-content: center;
                    align-items: center;
                }}
                
                .placeholder {{
                    text-align: center;
                    color: white;
                    font-family: 'Microsoft YaHei', Arial, sans-serif;
                }}
                
                .placeholder h2 {{
                    margin-bottom: 10px;
                    font-size: 24px;
                }}
                
                .placeholder p {{
                    margin: 5px 0;
                    font-size: 14px;
                }}
            </style>
        </head>
        <body>
            <div class="placeholder">
                <h2>🌸 Live2D 模型 🌸</h2>
                <p>模型加载中...</p>
                <p>请在下拉列表中选择可用模型</p>
            </div>
        </body>
        </html>
        """
        self.live2d_view.setHtml(html_content)
    
    def on_model_changed(self, model_name):
        """当模型选择改变时调用"""
        if model_name and model_name != "无可用模型" and model_name != "扫描失败":
            self.load_live2d_model(model_name)
    
    def set_mouth_open(self, value):
        """设置口型开合度 0.0~1.0"""
        js = f"if(typeof setMouthOpen==='function')setMouthOpen({value});"
        self.live2d_view.page().runJavaScript(js)