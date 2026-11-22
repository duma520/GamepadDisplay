# -*- coding: utf-8 -*-
"""
手柄状态监视器 GamepadDisplay
版本: v7.0

修复要点（相对 v6.0）:
  P0-1 按键索引映射错误（按下 Y 键界面无反应） -> 改为显式索引映射表，可配置
  P0-2 配置文件相对路径（打包后失效）          -> exe 同目录优先，不可写则回退 %APPDATA%
  P0-3 icon.ico 缺失                            -> 启动时若缺失自动生成
  P0-4 启动脚本使用裸 python                    -> 由 0.bat / 1.bat 固定为绝对路径
  P1   右摇杆/R3 缺失、单手柄、单方向键、轴/按钮数量写死、设置项不生效、
       窗口状态不恢复、版本号写死、重复 init 手柄
  P2   刷新 UI 节流、设置对话框、改名提示、按钮初始文本、清理导入、进度条语义
"""

import os
import sys
import json
import time
import warnings
from datetime import datetime

# PyQt5 + Python 3.10 在类定义阶段会输出 sipPyTypeDict() 弃用警告（上游问题），
# 必须在导入 PyQt5 之前/之后、类定义之前屏蔽，放在 main() 里已来不及。
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pygame
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import (QFont, QFontDatabase, QPalette, QColor, QIcon,
                         QPainter, QBrush, QPen)
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QGroupBox, QMessageBox, QProgressBar, QLineEdit,
                             QDialog, QDialogButtonBox, QFormLayout, QTabWidget,
                             QTextEdit, QSplitter, QFrame, QScrollArea,
                             QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
                             QSizePolicy)

APP_NAME = "GamepadDisplay"
VERSION = "7.1.0"
CONFIG_NAME = "joystick_config.json"
ICON_NAME = "icon.ico"

# ---------------------------------------------------------------- 路径工具

def get_app_dir():
    """程序所在目录（兼容 PyInstaller 打包）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    """资源文件路径（打包后优先从 _MEIPASS 读取）"""
    base = getattr(sys, '_MEIPASS', None)
    if base:
        packed = os.path.join(base, name)
        if os.path.exists(packed):
            return packed
    return os.path.join(get_app_dir(), name)


def get_config_path():
    """
    配置文件路径：
      1) 程序目录已存在配置 -> 便携模式（沿用旧配置）
      2) 程序目录可写       -> 便携模式
      3) 否则               -> %APPDATA%/GamepadDisplay/（打包安装场景）
    """
    app_dir = get_app_dir()
    portable = os.path.join(app_dir, CONFIG_NAME)
    try:
        if os.path.exists(portable):
            return portable
        probe = os.path.join(app_dir, ".write_test.tmp")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        os.remove(probe)
        return portable
    except Exception:
        pass
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, APP_NAME)
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        return portable
    return os.path.join(folder, CONFIG_NAME)


CONFIG_FILE = get_config_path()
ICON_FILE = resource_path(ICON_NAME)


def pick_font_family():
    """挑选可用的免费商用中文字体（禁用微软雅黑/苹方/方正/汉仪）"""
    candidates = ["HarmonyOS Sans SC", "Source Han Sans SC", "Noto Sans SC",
                  "WenQuanYi Micro Hei", "Sans"]
    try:
        families = set(QFontDatabase().families())
    except Exception:
        families = set()
    for name in candidates:
        if name in families:
            return name
    return ""


FONT_FAMILY = None  # 在 main() 中初始化


def ui_font(size=9, bold=False):
    f = QFont(FONT_FAMILY, size)
    f.setBold(bold)
    return f


# ---------------------------------------------------------------- 按键定义

# 逻辑键 -> 默认显示名
LOGICAL_BUTTONS = [
    ("action_Y", "Y"), ("action_X", "X"), ("action_B", "B"), ("action_A", "A"),
    ("shoulder_LB", "LB"), ("shoulder_RB", "RB"),
    ("shoulder_LT", "LT"), ("shoulder_RT", "RT"),
    ("center_Select", "Select"), ("center_Start", "Start"),
    ("center_Guide", "Guide"), ("center_Mode", "Mode"),
    ("left_L3", "L3"), ("right_R3", "R3"),
    ("dpad_up", "上"), ("dpad_down", "下"), ("dpad_left", "左"), ("dpad_right", "右"),
]
LOGICAL_KEYS = [k for k, _ in LOGICAL_BUTTONS]
LOGICAL_DEFAULT_NAME = dict(LOGICAL_BUTTONS)

# 按键映射预设：逻辑键 -> pygame 按钮索引（-1 表示不映射）
PRESET_XBOX = {
    "action_A": 0, "action_B": 1, "action_X": 2, "action_Y": 3,
    "shoulder_LB": 4, "shoulder_RB": 5,
    "center_Select": 6, "center_Start": 7, "center_Guide": 8,
    "left_L3": 9, "right_R3": 10,
}
PRESET_EXTENDED = {
    "action_A": 0, "action_B": 1, "action_X": 2, "action_Y": 3,
    "shoulder_LB": 4, "shoulder_RB": 5, "shoulder_LT": 6, "shoulder_RT": 7,
    "center_Select": 8, "center_Start": 9, "center_Guide": 10,
    "left_L3": 11, "right_R3": 12, "center_Mode": 13,
}
PRESET_DPAD = {
    "action_A": 0, "action_B": 1, "action_X": 2, "action_Y": 3,
    "shoulder_LB": 4, "shoulder_RB": 5,
    "center_Select": 6, "center_Start": 7, "center_Guide": 8,
    "left_L3": 9, "right_R3": 10,
    "dpad_up": 11, "dpad_down": 12, "dpad_left": 13, "dpad_right": 14,
}
PRESETS = {
    "Xbox 标准（A/B/X/Y + LB/RB + Select/Start/Guide + L3/R3）": PRESET_XBOX,
    "扩展（LT/RT 为按键，共 14 键）": PRESET_EXTENDED,
    "D-pad 按键方案（方向键为按钮 11-14）": PRESET_DPAD,
}
DEFAULT_PRESET = "Xbox 标准（A/B/X/Y + LB/RB + Select/Start/Guide + L3/R3）"

AXIS_NAMES = ["左摇杆 X", "左摇杆 Y", "右摇杆 X", "右摇杆 Y",
              "LT 扳机", "RT 扳机", "轴6", "轴7"]

# 扳机（LT/RT）工作模式：多数手柄（Xbox / XInput）把扳机做成"轴"而非按钮
TRIGGER_MODES = {
    "分离轴（LT=轴4，RT=轴5）": "axis_separate",
    "合并轴（轴2：负=LT，正=RT）": "axis_combined",
    "按键（LT/RT 走 button 索引）": "button",
    "不使用": "none",
}
DEFAULT_TRIGGER_MODE = "分离轴（LT=轴4，RT=轴5）"
DEFAULT_TRIGGER_AXIS_LT = 4
DEFAULT_TRIGGER_AXIS_RT = 5
DEFAULT_TRIGGER_AXIS_COMBINED = 2

DEFAULT_SETTINGS = {
    "window_geometry": None,
    "window_state": None,
    "button_names": {},
    "auto_connect": True,
    "update_rate": 25,
    "deadzone": 0.05,
    "button_map": dict(PRESET_XBOX),
    "device_index": 0,
    "preset": DEFAULT_PRESET,
    "trigger_mode": "axis_separate",
    "trigger_threshold": 0.5,
    "trigger_axis_lt": DEFAULT_TRIGGER_AXIS_LT,
    "trigger_axis_rt": DEFAULT_TRIGGER_AXIS_RT,
    "trigger_axis_combined": DEFAULT_TRIGGER_AXIS_COMBINED,
}


def ensure_icon():
    """图标缺失时自动生成（需 Pillow；失败则忽略）"""
    if os.path.exists(ICON_FILE):
        return True
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False
    try:
        size = 256
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([20, 70, 236, 196], radius=58, fill=(45, 45, 55, 255))
        d.ellipse([30, 130, 110, 226], fill=(45, 45, 55, 255))
        d.ellipse([146, 130, 226, 226], fill=(45, 45, 55, 255))
        d.ellipse([52, 96, 100, 144], fill=(240, 240, 240, 255))
        d.ellipse([66, 110, 86, 130], fill=(90, 90, 100, 255))
        d.rectangle([42, 160, 70, 188], fill=(240, 240, 240, 255))
        d.rectangle([54, 148, 58, 200], fill=(240, 240, 240, 255))
        for cx, cy, col in ((196, 118, (76, 175, 80, 255)),
                            (172, 142, (229, 115, 115, 255)),
                            (220, 142, (100, 149, 237, 255)),
                            (196, 166, (255, 193, 7, 255))):
            d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], fill=col)
        d.ellipse([150, 160, 190, 200], fill=(240, 240, 240, 255))
        d.ellipse([160, 170, 180, 190], fill=(90, 90, 100, 255))
        img.save(ICON_FILE, format="ICO",
                 sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
        return os.path.exists(ICON_FILE)
    except Exception:
        return False


# ---------------------------------------------------------------- 控件

class JoystickButton(QLabel):
    """手柄按键控件（右键 / 双击可改名）"""

    clicked = pyqtSignal(object)

    STYLE_ON = """
        QLabel { background-color: #4CAF50; border: 2px solid #2E7D32;
                 border-radius: 8px; color: white; font-weight: bold;
                 font-size: 12px; padding: 4px; }
    """
    STYLE_OFF = """
        QLabel { background-color: #F5F5F5; border: 2px solid #9E9E9E;
                 border-radius: 8px; color: #333; font-weight: bold;
                 font-size: 12px; padding: 4px; }
        QLabel:hover { background-color: #E0E0E0; border: 2px solid #757575; }
    """

    def __init__(self, key, default_name, parent=None):
        super().__init__(parent)
        self.key = key
        self.default_name = default_name
        self.custom_name = default_name
        self.is_pressed = False
        self._style_state = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(52, 40)
        self.setMaximumSize(96, 68)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("右键单击（或双击）可自定义名称")
        self.setText(default_name)
        self.set_pressed(False)

    def set_pressed(self, pressed):
        pressed = bool(pressed)
        if self.is_pressed == pressed and self._style_state is not None:
            return
        self.is_pressed = pressed
        if self._style_state != pressed:
            self._style_state = pressed
            self.setStyleSheet(self.STYLE_ON if pressed else self.STYLE_OFF)

    def set_custom_name(self, name):
        self.custom_name = (name or "").strip() or self.default_name
        self.setText(self.custom_name)

    def set_index_tip(self, index):
        tip = "右键单击（或双击）可自定义名称"
        if index is None or index < 0:
            tip = f"未绑定按键索引\n{tip}"
        else:
            tip = f"绑定索引: {index}\n{tip}"
        self.setToolTip(tip)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.clicked.emit(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.clicked.emit(self)
        event.accept()


class JoystickAxisWidget(QWidget):
    """单轴条形显示控件"""

    def __init__(self, axis_id, axis_name, parent=None):
        super().__init__(parent)
        self.axis_id = axis_id
        self.axis_name = axis_name
        self.value = 0.0
        self.setMinimumHeight(34)
        self.setMaximumHeight(48)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if abs(v - self.value) < 0.002:
            return
        self.value = v
        self.update()

    def set_name(self, name):
        if name and name != self.axis_name:
            self.axis_name = name
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(190, 190, 190), 1))
        p.setBrush(QBrush(QColor(250, 250, 250)))
        p.drawRoundedRect(1, 1, w - 2, h - 2, 4, 4)

        cx = w // 2
        cy = h // 2 + 4
        half = max((w - 16) // 2, 1)
        p.setPen(QPen(QColor(215, 215, 215), 1))
        p.drawLine(cx, 4, cx, h - 4)

        vx = int(cx + self.value * half)
        color = QColor(76, 175, 80, 170)
        if self.value >= 0:
            p.fillRect(cx, cy - 5, max(vx - cx, 0), 10, color)
        else:
            p.fillRect(vx, cy - 5, max(cx - vx, 0), 10, color)

        p.setPen(QPen(QColor(33, 150, 243), 2))
        p.setBrush(QBrush(QColor(100, 180, 255)))
        p.drawEllipse(vx - 6, cy - 6, 12, 12)

        p.setPen(Qt.black)
        p.setFont(ui_font(8))
        p.drawText(6, 2, w - 12, 14, Qt.AlignLeft | Qt.AlignTop,
                   f"{self.axis_name}: {self.value:+.3f}")


class JoystickXYWidget(QWidget):
    """摇杆 XY 平面显示控件"""

    def __init__(self, title="摇杆", parent=None):
        super().__init__(parent)
        self.title = title
        self.x = 0.0
        self.y = 0.0
        self.setMinimumSize(96, 96)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_value(self, x, y):
        try:
            nx, ny = float(x), float(y)
        except (TypeError, ValueError):
            return
        if abs(nx - self.x) < 0.003 and abs(ny - self.y) < 0.003:
            return
        self.x, self.y = nx, ny
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        size = max(min(w, h) - 26, 10)
        cx, cy = w // 2, h // 2 + 6          # Qt 绘图 API 只接受 int
        left, top = cx - size // 2, cy - size // 2

        p.setPen(QPen(QColor(60, 60, 60), 2))
        p.setBrush(QBrush(QColor(238, 238, 238)))
        p.drawEllipse(left, top, size, size)

        p.setPen(QPen(QColor(205, 205, 205), 1))
        p.drawLine(left, cy, left + size, cy)
        p.drawLine(cx, top, cx, top + size)

        r = size // 2 - 9
        px = int(cx + self.x * r)
        py = int(cy + self.y * r)
        p.setPen(QPen(QColor(33, 150, 243), 2))
        p.setBrush(QBrush(QColor(100, 180, 255, 220)))
        p.drawEllipse(px - 8, py - 8, 16, 16)

        p.setPen(Qt.black)
        p.setFont(ui_font(9, True))
        p.drawText(0, 2, w, 16, Qt.AlignHCenter | Qt.AlignTop, self.title)


class JoystickHatWidget(QWidget):
    """十字键（Hat）圆盘显示控件"""

    def __init__(self, hat_id, parent=None):
        super().__init__(parent)
        self.hat_id = hat_id
        self.x = 0
        self.y = 0
        self.setMinimumSize(92, 92)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_value(self, x, y):
        try:
            nx, ny = int(x), int(y)
        except (TypeError, ValueError):
            return
        if nx == self.x and ny == self.y:
            return
        self.x, self.y = nx, ny
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        size = max(min(w, h) - 24, 10)
        cx, cy = w // 2, h // 2               # Qt 绘图 API 只接受 int
        left, top = cx - size // 2, cy - size // 2

        p.setPen(QPen(QColor(60, 60, 60), 2))
        p.setBrush(QBrush(QColor(232, 232, 232)))
        p.drawEllipse(left, top, size, size)

        p.setPen(QPen(QColor(190, 190, 190), 1))
        p.drawLine(cx, top, cx, top + size)
        p.drawLine(left, cy, left + size, cy)

        if self.x or self.y:
            step = size // 3
            # pygame 约定：y = 1 表示上、-1 表示下（屏幕坐标 y 向下为正，故取负号）
            px = cx + self.x * step
            py = cy - self.y * step
            p.setPen(QPen(QColor(46, 125, 50), 2))
            p.setBrush(QBrush(QColor(76, 175, 80, 210)))
            p.drawEllipse(px - size // 8, py - size // 8, size // 4, size // 4)

            direction = ""
            if self.y == 1:
                direction += "上"
            elif self.y == -1:
                direction += "下"
            if self.x == -1:
                direction += "左"
            elif self.x == 1:
                direction += "右"
            p.setPen(Qt.black)
            p.setFont(ui_font(10, True))
            p.drawText(0, h - 18, w, 16, Qt.AlignHCenter | Qt.AlignBottom, direction)

        p.setPen(QColor(90, 90, 90))
        p.setFont(ui_font(8))
        p.drawText(0, 2, w, 14, Qt.AlignHCenter | Qt.AlignTop, f"十字键 {self.hat_id}")


# ---------------------------------------------------------------- 对话框

class ButtonEditDialog(QDialog):
    """按键改名对话框"""

    def __init__(self, button, parent=None):
        super().__init__(parent)
        self.button = button
        self.setWindowTitle("编辑按键名称")
        self.setModal(True)
        self.setFixedSize(340, 170)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        self.name_edit = QLineEdit(button.custom_name)
        self.name_edit.selectAll()
        self.name_edit.setMinimumHeight(28)
        form.addRow("默认名称:", QLabel(button.default_name))
        form.addRow("显示名称:", self.name_edit)
        layout.addLayout(form)

        info = QLabel("提示：可在“设置 → 按键映射”中修改该按键绑定的手柄索引")
        info.setWordWrap(True)
        info.setStyleSheet("color:#777; font-size:11px;")
        layout.addWidget(info)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_new_name(self):
        return self.name_edit.text().strip() or self.button.default_name


class SettingsDialog(QDialog):
    """设置对话框：常规 + 按键映射"""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(600, 540)
        self.spins = {}

        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # ---- 常规 ----
        general = QWidget()
        gl = QFormLayout(general)
        gl.setSpacing(10)

        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(5, 120)
        self.rate_spin.setSuffix(" Hz")
        self.rate_spin.setValue(int(settings.get("update_rate", 25)))
        gl.addRow("数据更新频率:", self.rate_spin)

        self.deadzone_spin = QDoubleSpinBox()
        self.deadzone_spin.setRange(0.0, 0.30)
        self.deadzone_spin.setSingleStep(0.01)
        self.deadzone_spin.setDecimals(2)
        self.deadzone_spin.setValue(float(settings.get("deadzone", 0.05)))
        gl.addRow("摇杆死区（绝对值小于此值归零）:", self.deadzone_spin)

        self.auto_chk = QCheckBox("启动时自动开始监控")
        self.auto_chk.setChecked(bool(settings.get("auto_connect", True)))
        gl.addRow("", self.auto_chk)

        gl.addRow("", QLabel("<b>扳机 LT / RT</b>"))
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems(list(TRIGGER_MODES.keys()))
        saved_mode = settings.get("trigger_mode", "axis_separate")
        for text, key in TRIGGER_MODES.items():
            if key == saved_mode:
                self.trigger_combo.setCurrentText(text)
                break
        self.trigger_combo.setToolTip(
            "多数手柄（Xbox 等）把 LT/RT 做成轴而不是按钮，所以按键映射里点不亮它们。"
            "选“分离轴”时按 轴4/轴5 的行程判断；选“按键”时走下方按键映射的 shoulder_LT/RT 索引。")
        gl.addRow("扳机工作模式:", self.trigger_combo)

        self.trigger_thr_spin = QDoubleSpinBox()
        self.trigger_thr_spin.setRange(0.05, 0.95)
        self.trigger_thr_spin.setSingleStep(0.05)
        self.trigger_thr_spin.setDecimals(2)
        self.trigger_thr_spin.setValue(float(settings.get("trigger_threshold", 0.5)))
        gl.addRow("扳机触发阈值（轴值）:", self.trigger_thr_spin)

        tip = QLabel("设置会立即保存，下次启动自动沿用。")
        tip.setStyleSheet("color:#777;")
        gl.addRow("", tip)
        tabs.addTab(general, "常规")

        # ---- 按键映射 ----
        mapping = QWidget()
        ml = QVBoxLayout(mapping)
        top = QHBoxLayout()
        top.addWidget(QLabel("预设方案:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESETS.keys()))
        saved_preset = settings.get("preset", DEFAULT_PRESET)
        if saved_preset in PRESETS:
            self.preset_combo.setCurrentText(saved_preset)
        self.preset_combo.currentTextChanged.connect(self.apply_preset)
        top.addWidget(self.preset_combo, 1)
        ml.addLayout(top)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setSpacing(6)
        grid.addWidget(QLabel("<b>逻辑按键</b>"), 0, 0)
        grid.addWidget(QLabel("<b>手柄索引</b>"), 0, 1)
        grid.addWidget(QLabel("<b>逻辑按键</b>"), 0, 2)
        grid.addWidget(QLabel("<b>手柄索引</b>"), 0, 3)

        current_map = settings.get("button_map") or dict(PRESET_XBOX)
        row, col = 1, 0
        for key, name in LOGICAL_BUTTONS:
            label = QLabel(f"{name}")
            label.setToolTip(key)
            spin = QSpinBox()
            spin.setRange(-1, 63)
            spin.setSpecialValueText("未绑定")
            spin.setValue(int(current_map.get(key, -1)))
            self.spins[key] = spin
            grid.addWidget(label, row, col)
            grid.addWidget(spin, row, col + 1)
            col += 2
            if col > 2:
                col = 0
                row += 1
        ml.addWidget(grid_widget)

        hint = QLabel("说明：索引为 pygame 的 button 编号，-1 表示该按键不参与显示。\n"
                      "若某个键无反应，可切换预设方案或手动调整索引。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777; font-size:11px;")
        ml.addWidget(hint)
        ml.addStretch()
        tabs.addTab(mapping, "按键映射")

        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.RestoreDefaults |
                                   QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.RestoreDefaults).setText("恢复默认")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(buttons)

    def apply_preset(self, name):
        preset = PRESETS.get(name)
        if not preset:
            return
        for key, spin in self.spins.items():
            spin.setValue(int(preset.get(key, -1)))

    def restore_defaults(self):
        self.rate_spin.setValue(25)
        self.deadzone_spin.setValue(0.05)
        self.auto_chk.setChecked(True)
        self.preset_combo.setCurrentText(DEFAULT_PRESET)
        self.apply_preset(DEFAULT_PRESET)
        self.trigger_combo.setCurrentText(DEFAULT_TRIGGER_MODE)
        self.trigger_thr_spin.setValue(0.5)

    def get_settings(self):
        return {
            "update_rate": int(self.rate_spin.value()),
            "deadzone": float(self.deadzone_spin.value()),
            "auto_connect": bool(self.auto_chk.isChecked()),
            "button_map": {k: int(v.value()) for k, v in self.spins.items()},
            "preset": self.preset_combo.currentText(),
            "trigger_mode": TRIGGER_MODES.get(self.trigger_combo.currentText(), "axis_separate"),
            "trigger_threshold": float(self.trigger_thr_spin.value()),
        }


# ---------------------------------------------------------------- 监控线程

class JoystickMonitor(QThread):
    """手柄数据读取线程"""

    data_updated = pyqtSignal(dict)
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    devices_updated = pyqtSignal(list)

    def __init__(self, update_rate=25, device_index=0):
        super().__init__()
        self.running = False
        self.paused = False
        self.update_rate = max(1, min(120, int(update_rate)))
        self.device_index = max(0, int(device_index))
        self._joy = None
        self._joy_index = None
        self._reinit = True
        self._rescan = False
        self._last_count = -1
        self._error_reported = False
        self._ready = False
        self._init_pygame()

    def _init_pygame(self):
        try:
            if not pygame.get_init():
                pygame.init()
            pygame.joystick.init()
            self._ready = True
        except Exception as e:
            self._ready = False
            self.error_occurred.emit(f"pygame 初始化失败: {e}")

    def set_update_rate(self, rate):
        try:
            self.update_rate = max(1, min(120, int(rate)))
        except (TypeError, ValueError):
            pass

    def set_device_index(self, index):
        try:
            index = max(0, int(index))
        except (TypeError, ValueError):
            return
        if index != self.device_index:
            self.device_index = index
            self._reinit = True

    def set_paused(self, paused):
        self.paused = bool(paused)

    def request_reinit(self):
        self._reinit = True

    def request_rescan(self):
        """重新扫描手柄子系统（在线程内执行，避免跨线程 SDL 调用）"""
        self._rescan = True
        self._reinit = True
        self._last_count = -1

    def stop(self):
        self.running = False

    def _read_devices(self, count):
        names = []
        for i in range(count):
            try:
                joy = pygame.joystick.Joystick(i)
                joy.init()
                names.append(joy.get_name())
            except Exception:
                names.append(f"手柄 {i}")
        return names

    def run(self):
        self.running = True
        while self.running:
            delay = 1.0 / max(1, self.update_rate)
            try:
                if not self._ready:
                    self._init_pygame()
                    if not self._ready:
                        time.sleep(1.0)
                        continue

                if self._rescan:
                    self._rescan = False
                    try:
                        pygame.joystick.quit()
                        pygame.joystick.init()
                        self._joy = None
                    except Exception as e:
                        self.error_occurred.emit(f"重新扫描失败: {e}")

                pygame.event.pump()
                count = pygame.joystick.get_count()

                if count != self._last_count:
                    self._last_count = count
                    self._reinit = True
                    self.devices_updated.emit(self._read_devices(count) if count else [])
                    if count == 0:
                        self.status_updated.emit("未检测到手柄")
                    else:
                        self.status_updated.emit(f"检测到 {count} 个手柄")

                if count == 0:
                    self.data_updated.emit({"connected": False})
                    time.sleep(max(delay, 0.25))
                    continue

                if self.paused:
                    self.data_updated.emit({"connected": False, "paused": True})
                    time.sleep(0.25)
                    continue

                idx = self.device_index if self.device_index < count else 0
                if self._reinit or self._joy is None or self._joy_index != idx:
                    self._joy = pygame.joystick.Joystick(idx)
                    self._joy.init()
                    self._joy_index = idx
                    self._reinit = False

                joy = self._joy
                data = {
                    "connected": True,
                    "name": joy.get_name(),
                    "num_axes": joy.get_numaxes(),
                    "num_buttons": joy.get_numbuttons(),
                    "num_hats": joy.get_numhats(),
                    "instance_id": joy.get_instance_id(),
                    "device_index": idx,
                    "axes": [], "buttons": [], "hats": [],
                }
                for i in range(joy.get_numaxes()):
                    try:
                        data["axes"].append(float(joy.get_axis(i)))
                    except Exception:
                        data["axes"].append(0.0)
                for i in range(joy.get_numbuttons()):
                    try:
                        data["buttons"].append(bool(joy.get_button(i)))
                    except Exception:
                        data["buttons"].append(False)
                for i in range(joy.get_numhats()):
                    try:
                        hx, hy = joy.get_hat(i)
                        data["hats"].append({"x": int(hx), "y": int(hy)})
                    except Exception:
                        data["hats"].append({"x": 0, "y": 0})

                self.data_updated.emit(data)
                self._error_reported = False
                time.sleep(delay)

            except Exception as e:
                self._reinit = True
                self._joy = None
                if not self._error_reported:
                    self._error_reported = True
                    self.error_occurred.emit(f"读取手柄数据出错: {e}")
                self.data_updated.emit({"connected": False, "error": str(e)})
                time.sleep(0.5)

        try:
            pygame.joystick.quit()
            pygame.quit()
        except Exception:
            pass


# ---------------------------------------------------------------- 主窗口

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        self.button_map = self._sanitize_map(self.settings.get("button_map"))

        self.button_widgets = {}
        self.axis_widgets = {}
        self.hat_widgets = {}
        self.button_labels = []
        self._label_state = {}
        self.hat_empty_label = None

        self._fps_time = time.time()
        self._fps_frames = 0
        self.fps = 0.0
        self._detail_last = 0.0
        self._pending_detail = None

        self.init_ui()
        self.apply_settings()
        self.init_monitor()

    # ---------------- 设置读写 ----------------

    def load_settings(self):
        settings = dict(DEFAULT_SETTINGS)
        settings["button_map"] = dict(PRESET_XBOX)
        settings["button_names"] = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    settings.update(loaded)
            except Exception as e:
                print(f"加载设置失败: {e}")
        if not isinstance(settings.get("button_map"), dict):
            settings["button_map"] = dict(PRESET_XBOX)
        if not isinstance(settings.get("button_names"), dict):
            settings["button_names"] = {}
        return settings

    def _sanitize_map(self, raw):
        result = {}
        if not isinstance(raw, dict):
            raw = {}
        for key, idx in raw.items():
            if key not in LOGICAL_KEYS:
                continue
            try:
                result[key] = int(idx)
            except (TypeError, ValueError):
                continue
        return result or dict(PRESET_XBOX)

    def save_settings(self):
        try:
            if not self.isMaximized():
                self.settings["window_geometry"] = self.saveGeometry().toBase64().data().decode()
            self.settings["window_state"] = self.saveState().toBase64().data().decode()
            self.settings["button_names"] = {
                key: btn.custom_name for key, btn in self.button_widgets.items()
            }
            self.settings["button_map"] = self.button_map
            if getattr(self, "device_combo", None) is not None and self.device_combo.count():
                self.settings["device_index"] = max(0, self.device_combo.currentIndex())
            folder = os.path.dirname(CONFIG_FILE)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            os.rename(tmp, CONFIG_FILE)
        except Exception as e:
            print(f"保存设置失败: {e}")

    def schedule_save(self):
        if not hasattr(self, "_save_timer"):
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.timeout.connect(self.save_settings)
        self._save_timer.start(800)

    def apply_settings(self):
        geo = self.settings.get("window_geometry")
        state = self.settings.get("window_state")
        if geo:
            try:
                self.restoreGeometry(bytes(geo, "utf-8"))
            except Exception:
                self.resize(980, 760)
        else:
            self.resize(980, 760)
        if state:
            try:
                self.restoreState(bytes(state, "utf-8"))
            except Exception:
                pass

        names = self.settings.get("button_names", {})
        for key, name in names.items():
            btn = self.button_widgets.get(key)
            if btn is not None and isinstance(name, str):
                btn.set_custom_name(name)
        self.refresh_button_tooltips()

    def refresh_button_tooltips(self):
        mode = str(self.settings.get("trigger_mode", "axis_separate"))
        mode_text = next((t for t, k in TRIGGER_MODES.items() if k == mode), mode)
        for key, btn in self.button_widgets.items():
            btn.set_index_tip(int(self.button_map.get(key, -1) or -1))
            base = btn.toolTip()
            if key in ("shoulder_LT", "shoulder_RT"):
                btn.setToolTip(f"扳机通常是轴而非按钮，由「设置 → 扳机工作模式」驱动（当前：{mode_text}）\n{base}")
            elif key.startswith("dpad_"):
                btn.setToolTip(f"方向键：手柄若把方向键报为十字键(Hat)，此处自动联动\n{base}")

    # ---------------- UI ----------------

    def init_ui(self):
        self.setWindowTitle(f"手柄状态监视器 v{VERSION}")
        if os.path.exists(ICON_FILE):
            try:
                self.setWindowIcon(QIcon(ICON_FILE))
            except Exception:
                pass

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)

        main_layout.addWidget(self.create_toolbar())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.controller_tab = QWidget()
        self.detail_tab = QWidget()
        self.create_controller_layout()
        self.create_detail_layout()
        self.tabs.addTab(self.controller_tab, "🎮 手柄布局")
        self.tabs.addTab(self.detail_tab, "📊 详细信息")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        main_layout.addWidget(self.tabs, 1)

        main_layout.addWidget(self.create_bottom_panel())

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color:#666; padding:2px;")
        self.statusBar().addWidget(self.status_label)
        ver = QLabel(f"v{VERSION}")
        ver.setStyleSheet("color:#999; padding:2px;")
        self.statusBar().addPermanentWidget(ver)

    def create_toolbar(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        self.connect_label = QLabel("⚪ 未连接")
        self.connect_label.setStyleSheet("color:#d32f2f; font-weight:bold; padding:3px;")
        layout.addWidget(self.connect_label)

        self.name_label = QLabel("手柄: -")
        self.name_label.setStyleSheet("color:#333; padding:3px;")
        layout.addWidget(self.name_label)

        layout.addWidget(QLabel("设备:"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(240)
        self.device_combo.setToolTip("选择要监控的手柄")
        self.device_combo.addItem("（无可用手柄）", -1)
        self.device_combo.currentIndexChanged.connect(self.on_device_selected)
        layout.addWidget(self.device_combo, 1)

        self.pause_btn = QPushButton("⏸ 暂停")
        self.pause_btn.setFixedHeight(30)
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setToolTip("暂停 / 继续读取手柄数据")
        self.pause_btn.clicked.connect(self.toggle_pause)
        layout.addWidget(self.pause_btn)

        self.refresh_btn = QPushButton("🔄 刷新手柄")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setToolTip("重新扫描手柄设备")
        self.refresh_btn.clicked.connect(self.refresh_joystick)
        layout.addWidget(self.refresh_btn)

        self.settings_btn = QPushButton("⚙ 设置")
        self.settings_btn.setFixedHeight(30)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_btn)

        return widget

    def create_controller_layout(self):
        layout = QVBoxLayout(self.controller_tab)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(5)
        splitter.setStyleSheet("QSplitter::handle { background-color:#ddd; }")

        top = QWidget()
        self.create_joystick_layout(top)
        bottom = QWidget()
        self.create_axes_layout(bottom)
        splitter.addWidget(top)
        splitter.addWidget(bottom)
        splitter.setSizes([520, 220])

        content_layout.addWidget(splitter)
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def _make_button(self, key):
        btn = JoystickButton(key, LOGICAL_DEFAULT_NAME.get(key, key))
        btn.clicked.connect(self.edit_button_name)
        self.button_widgets[key] = btn
        return btn

    def create_joystick_layout(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(5, 5, 5, 5)

        frame = QFrame()
        frame.setFrameStyle(QFrame.Box)
        frame.setStyleSheet(
            "QFrame { background-color:#f8f8f8; border:1px solid #ccc; border-radius:5px; }")
        grid = QGridLayout(frame)
        grid.setSpacing(12)
        grid.setContentsMargins(14, 14, 14, 14)

        # 左摇杆
        left_group = QGroupBox("左摇杆")
        left_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        left_layout = QVBoxLayout(left_group)
        self.left_xy = JoystickXYWidget("左摇杆")
        left_layout.addWidget(self.left_xy, 0, Qt.AlignCenter)
        left_layout.addWidget(self._make_button("left_L3"), 0, Qt.AlignCenter)
        grid.addWidget(left_group, 0, 0)

        # 功能键
        center_group = QGroupBox("功能键")
        center_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        center_layout = QGridLayout(center_group)
        center_layout.addWidget(self._make_button("center_Select"), 0, 0)
        center_layout.addWidget(self._make_button("center_Guide"), 0, 1)
        center_layout.addWidget(self._make_button("center_Start"), 0, 2)
        center_layout.addWidget(self._make_button("center_Mode"), 1, 1)
        grid.addWidget(center_group, 0, 1)

        # 右摇杆
        right_group = QGroupBox("右摇杆")
        right_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        right_layout = QVBoxLayout(right_group)
        self.right_xy = JoystickXYWidget("右摇杆")
        right_layout.addWidget(self.right_xy, 0, Qt.AlignCenter)
        right_layout.addWidget(self._make_button("right_R3"), 0, Qt.AlignCenter)
        grid.addWidget(right_group, 0, 2)

        # 方向键（按键型；手柄若为十字键 Hat 则自动联动）
        dpad_group = QGroupBox("方向键")
        dpad_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        dpad_group.setToolTip("手柄把方向键做成独立按钮时走按键映射；"
                              "做成十字键(Hat)时本组由 Hat 自动联动显示。")
        dpad_layout = QGridLayout(dpad_group)
        dpad_layout.addWidget(self._make_button("dpad_up"), 0, 1)
        dpad_layout.addWidget(self._make_button("dpad_left"), 1, 0)
        dpad_layout.addWidget(self._make_button("dpad_right"), 1, 2)
        dpad_layout.addWidget(self._make_button("dpad_down"), 2, 1)
        grid.addWidget(dpad_group, 1, 0)

        # 动作键
        action_group = QGroupBox("动作键")
        action_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        action_layout = QGridLayout(action_group)
        action_layout.addWidget(self._make_button("action_Y"), 0, 1)
        action_layout.addWidget(self._make_button("action_X"), 1, 0)
        action_layout.addWidget(self._make_button("action_B"), 1, 2)
        action_layout.addWidget(self._make_button("action_A"), 2, 1)
        grid.addWidget(action_group, 1, 1)

        # 十字键（Hat，动态创建）
        hat_group = QGroupBox("十字键（Hat）")
        hat_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        self.hat_container_layout = QHBoxLayout(hat_group)
        self.hat_container_layout.setAlignment(Qt.AlignCenter)
        self.hat_empty_label = QLabel("手柄未报告十字键")
        self.hat_empty_label.setStyleSheet("color:#888;")
        self.hat_container_layout.addWidget(self.hat_empty_label)
        grid.addWidget(hat_group, 1, 2)

        # 肩键 / 扳机
        shoulder_group = QGroupBox("肩键 / 扳机")
        shoulder_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        shoulder_layout = QHBoxLayout(shoulder_group)
        shoulder_layout.setSpacing(10)
        for key in ("shoulder_LB", "shoulder_LT", "shoulder_RT", "shoulder_RB"):
            shoulder_layout.addWidget(self._make_button(key))
        grid.addWidget(shoulder_group, 2, 0, 1, 3)

        layout.addWidget(frame)

    def create_axes_layout(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(5, 5, 5, 5)
        self.axes_group = QGroupBox("摇杆轴状态")
        self.axes_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        self.axes_layout = QGridLayout(self.axes_group)
        self.axes_layout.setSpacing(8)
        self.ensure_axis_widgets(8)
        layout.addWidget(self.axes_group)

    def create_detail_layout(self):
        layout = QVBoxLayout(self.detail_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Vertical)

        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_group = QGroupBox("原始数据")
        text_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        tg_layout = QVBoxLayout(text_group)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setLineWrapMode(QTextEdit.NoWrap)
        self.detail_text.setFont(QFont("Consolas", 10))
        tg_layout.addWidget(self.detail_text)
        text_layout.addWidget(text_group)
        splitter.addWidget(text_widget)

        btn_widget = QWidget()
        btn_layout = QVBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        self.button_group = QGroupBox("按钮状态列表")
        self.button_group.setStyleSheet("QGroupBox { font-weight:bold; }")
        self.button_grid_layout = QGridLayout(self.button_group)
        self.button_grid_layout.setSpacing(5)
        self.ensure_button_labels(20)
        btn_layout.addWidget(self.button_group)
        splitter.addWidget(btn_widget)

        splitter.setSizes([320, 300])
        layout.addWidget(splitter)

    def create_bottom_panel(self):
        widget = QWidget()
        widget.setFixedHeight(40)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setToolTip("实际数据刷新率占目标刷新率的比例")
        self.progress_bar.setStyleSheet("""
            QProgressBar { border:1px solid #ccc; border-radius:4px; background-color:#f0f0f0; }
            QProgressBar::chunk { background-color:#4CAF50; border-radius:3px; }
        """)

        self.bottom_status = QLabel("等待手柄连接...")
        self.bottom_status.setStyleSheet("color:#666; font-size:10px;")
        self.bottom_status.setFixedHeight(20)

        self.fps_label = QLabel("0 / 0 Hz")
        self.fps_label.setStyleSheet("color:#666; font-size:10px;")
        self.fps_label.setFixedWidth(96)
        self.fps_label.setToolTip("实际刷新率 / 目标刷新率")

        self.time_label = QLabel()
        self.time_label.setStyleSheet("color:#999; font-size:10px;")
        self.time_label.setFixedWidth(62)
        self.update_time()

        self.time_timer = QTimer(self)
        self.time_timer.timeout.connect(self.update_time)
        self.time_timer.start(1000)

        self.fps_timer = QTimer(self)
        self.fps_timer.timeout.connect(self.update_fps)
        self.fps_timer.start(500)

        layout.addWidget(self.progress_bar, 3)
        layout.addWidget(self.bottom_status, 2)
        layout.addWidget(self.fps_label)
        layout.addWidget(self.time_label)
        return widget

    # ---------------- 动态控件 ----------------

    def ensure_axis_widgets(self, count):
        for i in range(count):
            if i in self.axis_widgets:
                continue
            name = AXIS_NAMES[i] if i < len(AXIS_NAMES) else f"轴{i}"
            widget = JoystickAxisWidget(i, name)
            self.axis_widgets[i] = widget
            self.axes_layout.addWidget(widget, i // 2, i % 2)

    def ensure_button_labels(self, count):
        while len(self.button_labels) < count:
            i = len(self.button_labels)
            label = QLabel(f"按钮 {i:2d}: -")
            label.setMinimumHeight(25)
            label.setStyleSheet("QLabel { padding:3px; background-color:#f5f5f5;"
                                "border:1px solid #ddd; border-radius:3px; }")
            self.button_grid_layout.addWidget(label, i // 4, i % 4)
            self.button_labels.append(label)
            self._label_state[i] = None

    def ensure_hat_widgets(self, count):
        if count <= 0:
            return
        for i in range(count):
            if i in self.hat_widgets:
                continue
            if self.hat_empty_label is not None:
                self.hat_container_layout.removeWidget(self.hat_empty_label)
                self.hat_empty_label.setParent(None)
                self.hat_empty_label = None
            widget = JoystickHatWidget(i)
            self.hat_widgets[i] = widget
            self.hat_container_layout.addWidget(widget)

    # ---------------- 监控 ----------------

    def init_monitor(self):
        self.monitor = JoystickMonitor(
            update_rate=self.settings.get("update_rate", 25),
            device_index=self.settings.get("device_index", 0),
        )
        self.monitor.data_updated.connect(self.update_display)
        self.monitor.status_updated.connect(self.update_status)
        self.monitor.error_occurred.connect(self.show_error)
        self.monitor.devices_updated.connect(self.update_devices)
        self.paused = False
        if self.settings.get("auto_connect", True):
            self.monitor.start()
            self.set_pause_button(False)
        else:
            self.set_pause_button(True)
            self.update_status("已暂停（可在“设置 → 常规”中开启自动开始）")

    def set_pause_button(self, paused):
        self.paused = bool(paused)
        self.pause_btn.setText("▶ 继续" if self.paused else "⏸ 暂停")

    def toggle_pause(self):
        if not self.monitor.isRunning():
            self.monitor.start()
            self.monitor.set_paused(False)
            self.set_pause_button(False)
            self.update_status("已开始监控")
            return
        new_state = not self.paused
        self.monitor.set_paused(new_state)
        self.set_pause_button(new_state)
        self.update_status("已暂停监控" if new_state else "已继续监控")

    def refresh_joystick(self):
        self.update_status("正在重新扫描手柄...")
        if not self.monitor.isRunning():
            self.monitor.start()
        self.monitor.set_paused(self.paused)
        self.monitor.request_rescan()

    def on_device_selected(self, index):
        if index is None or index < 0:
            return
        self.settings["device_index"] = int(index)
        if hasattr(self, "monitor"):
            self.monitor.set_device_index(int(index))
        self.schedule_save()

    def update_devices(self, names):
        names = list(names or [])
        current = self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if names:
            for i, name in enumerate(names):
                self.device_combo.addItem(f"[{i}] {name}", i)
            target = self.settings.get("device_index", 0)
            try:
                target = int(target)
            except (TypeError, ValueError):
                target = 0
            if isinstance(current, int) and 0 <= current < len(names):
                target = current
            target = min(max(target, 0), len(names) - 1)
            self.device_combo.setCurrentIndex(target)
        else:
            self.device_combo.addItem("（无可用手柄）", -1)
        self.device_combo.blockSignals(False)
        if names and hasattr(self, "monitor"):
            self.monitor.set_device_index(self.device_combo.currentIndex())

    # ---------------- 数据更新 ----------------

    def update_display(self, data):
        self._fps_frames += 1

        if not data.get("connected", False):
            if data.get("paused"):
                self.connect_label.setText("⏸ 已暂停")
                self.connect_label.setStyleSheet("color:#f57c00; font-weight:bold;")
            else:
                self.connect_label.setText("⚪ 未连接")
                self.connect_label.setStyleSheet("color:#d32f2f; font-weight:bold;")
                self.name_label.setText("手柄: -")
                self.clear_button_states()
            self._pending_detail = None
            return

        self.connect_label.setText("🟢 已连接")
        self.connect_label.setStyleSheet("color:#388e3c; font-weight:bold;")
        self.name_label.setText(f"手柄: {data.get('name', 'Unknown')}")

        try:
            deadzone = float(self.settings.get("deadzone", 0.0))
        except (TypeError, ValueError):
            deadzone = 0.0
        axes = [float(v) for v in (data.get("axes", []) or [])]
        if deadzone > 0:
            axes = [0.0 if abs(v) < deadzone else v for v in axes]

        self.ensure_axis_widgets(max(len(axes), 8))
        for i, value in enumerate(axes):
            self.axis_widgets[i].set_value(value)

        if len(axes) >= 2:
            self.left_xy.set_value(axes[0], axes[1])
        if len(axes) >= 4:
            self.right_xy.set_value(axes[2], axes[3])

        hats = data.get("hats", []) or []
        if hats:
            self.ensure_hat_widgets(len(hats))
            for i, hat in enumerate(hats):
                widget = self.hat_widgets.get(i)
                if widget is not None:
                    widget.set_value(hat.get("x", 0), hat.get("y", 0))

        buttons = [bool(b) for b in (data.get("buttons", []) or [])]
        self.ensure_button_labels(max(len(buttons), 20))

        index_to_keys = {}
        for key, idx in self.button_map.items():
            if idx is None or idx < 0:
                continue
            index_to_keys.setdefault(int(idx), []).append(key)

        for i, pressed in enumerate(buttons):
            if i < len(self.button_labels) and self._label_state.get(i) is not pressed:
                self._label_state[i] = pressed
                label = self.button_labels[i]
                label.setText(f"按钮 {i:2d}: {'按下' if pressed else '松开'}")
                if pressed:
                    label.setStyleSheet("QLabel { padding:3px; background-color:#4CAF50;"
                                        "color:white; border:1px solid #2E7D32;"
                                        "border-radius:3px; font-weight:bold; }")
                else:
                    label.setStyleSheet("QLabel { padding:3px; background-color:#f5f5f5;"
                                        "border:1px solid #ddd; border-radius:3px; }")
            for key in index_to_keys.get(i, []):
                btn = self.button_widgets.get(key)
                if btn is not None:
                    btn.set_pressed(pressed)

        # 扳机 LT/RT：多数手柄是轴（Xbox 为轴4/轴5，静止 -1，按下 +1），不走按钮索引
        mode = str(self.settings.get("trigger_mode", "axis_separate"))
        if mode in ("axis_separate", "axis_combined"):
            try:
                thr = float(self.settings.get("trigger_threshold", 0.5))
            except (TypeError, ValueError):
                thr = 0.5
            if mode == "axis_separate":
                lt_idx = int(self.settings.get("trigger_axis_lt", 4) or 4)
                rt_idx = int(self.settings.get("trigger_axis_rt", 5) or 5)
                lt_on = 0 <= lt_idx < len(axes) and axes[lt_idx] > thr
                rt_on = 0 <= rt_idx < len(axes) and axes[rt_idx] > thr
            else:
                idx = int(self.settings.get("trigger_axis_combined", 2) or 2)
                value = axes[idx] if 0 <= idx < len(axes) else 0.0
                lt_on = value < -thr
                rt_on = value > thr
            self._set_button_state("shoulder_LT", lt_on)
            self._set_button_state("shoulder_RT", rt_on)

        # 方向键（按键）组：手柄若把方向键做成按钮则走映射，否则用十字键(Hat)联动
        dpad_mapped = any(
            int(self.button_map.get(k, -1) or -1) >= 0
            for k in ("dpad_up", "dpad_down", "dpad_left", "dpad_right")
        )
        if hats and not dpad_mapped:
            hx = int(hats[0].get("x", 0) or 0)
            hy = int(hats[0].get("y", 0) or 0)
            self._set_button_state("dpad_up", hy == 1)
            self._set_button_state("dpad_down", hy == -1)
            self._set_button_state("dpad_left", hx == -1)
            self._set_button_state("dpad_right", hx == 1)

        if self.tabs.currentWidget() is self.detail_tab:
            self.render_detail(data, axes, buttons, hats)
        else:
            self._pending_detail = (data, axes, buttons, hats)

    def _set_button_state(self, key, state):
        btn = self.button_widgets.get(key)
        if btn is not None:
            btn.set_pressed(bool(state))

    def clear_button_states(self):
        for btn in self.button_widgets.values():
            btn.set_pressed(False)
        for i, label in enumerate(self.button_labels):
            if self._label_state.get(i) is not False:
                self._label_state[i] = False
                label.setText(f"按钮 {i:2d}: 松开")
                label.setStyleSheet("QLabel { padding:3px; background-color:#f5f5f5;"
                                    "border:1px solid #ddd; border-radius:3px; }")

    def on_tab_changed(self, index):
        if self.tabs.widget(index) is self.detail_tab and self._pending_detail:
            data, axes, buttons, hats = self._pending_detail
            self._pending_detail = None
            self.render_detail(data, axes, buttons, hats)

    def render_detail(self, data, axes, buttons, hats):
        now = time.time()
        if now - self._detail_last < 0.1:
            return
        self._detail_last = now

        text = "=" * 52 + "\n"
        text += f"手柄详细信息    (GamepadDisplay v{VERSION})\n"
        text += "=" * 52 + "\n\n"
        text += f"名称      : {data.get('name', 'Unknown')}\n"
        text += f"设备索引  : {data.get('device_index', 0)}\n"
        text += f"轴数量    : {data.get('num_axes', 0)}\n"
        text += f"按钮数量  : {data.get('num_buttons', 0)}\n"
        text += f"十字键数  : {data.get('num_hats', 0)}\n"
        text += f"实例 ID   : {data.get('instance_id', 'N/A')}\n\n"

        text += "轴状态:\n" + "-" * 34 + "\n"
        for i, value in enumerate(axes):
            name = AXIS_NAMES[i] if i < len(AXIS_NAMES) else f"轴{i}"
            filled = int(min(abs(value), 1.0) * 20)
            bar = "█" * filled + "░" * (20 - filled)
            text += f"  {name:8s}: [{bar}] {value:+.3f}\n"

        text += "\n按钮状态:\n" + "-" * 34 + "\n"
        if buttons:
            for i in range(0, len(buttons), 4):
                line = "  "
                for j in range(4):
                    if i + j < len(buttons):
                        line += f"按钮{i + j:2d}: {'●' if buttons[i + j] else '○'}  "
                text += line + "\n"
        else:
            text += "  （无按钮数据）\n"

        text += "\n十字键状态:\n" + "-" * 34 + "\n"
        if hats:
            for i, hat in enumerate(hats):
                direction = ""
                if hat.get("y") == 1:          # pygame: y=1 为上
                    direction += "上"
                elif hat.get("y") == -1:       # pygame: y=-1 为下
                    direction += "下"
                if hat.get("x") == -1:
                    direction += "左"
                elif hat.get("x") == 1:
                    direction += "右"
                text += (f"  十字键{i}: {direction or '居中'} "
                         f"({hat.get('x', 0):+d}, {hat.get('y', 0):+d})\n")
        else:
            text += "  （无十字键）\n"

        self.detail_text.setPlainText(text)

    def update_status(self, status):
        self.status_label.setText(status)
        self.bottom_status.setText(status)

    def show_error(self, error):
        self.status_label.setText(f"⚠️ {error}")
        self.bottom_status.setText(f"⚠️ {error}")

    def update_time(self):
        self.time_label.setText(datetime.now().strftime("%H:%M:%S"))

    def update_fps(self):
        now = time.time()
        elapsed = now - self._fps_time
        if elapsed <= 0:
            return
        self.fps = self._fps_frames / elapsed
        self._fps_time = now
        self._fps_frames = 0
        target = self.monitor.update_rate if hasattr(self, "monitor") else 25
        ratio = 0.0 if target <= 0 else min(self.fps / target, 1.0)
        self.progress_bar.setValue(int(ratio * 100))
        self.fps_label.setText(f"{self.fps:.1f} / {target} Hz")

    # ---------------- 交互 ----------------

    def edit_button_name(self, button):
        if not isinstance(button, JoystickButton):
            return
        dialog = ButtonEditDialog(button, self)
        if dialog.exec_() == QDialog.Accepted:
            button.set_custom_name(dialog.get_new_name())
            self.save_settings()
            self.update_status(f"已更新按键名称: {button.custom_name}")

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        new_settings = dialog.get_settings()
        self.settings["update_rate"] = new_settings["update_rate"]
        self.settings["deadzone"] = new_settings["deadzone"]
        self.settings["auto_connect"] = new_settings["auto_connect"]
        self.settings["preset"] = new_settings["preset"]
        self.settings["trigger_mode"] = new_settings["trigger_mode"]
        self.settings["trigger_threshold"] = new_settings["trigger_threshold"]
        self.button_map = self._sanitize_map(new_settings["button_map"])
        self.refresh_button_tooltips()
        self.clear_button_states()
        if hasattr(self, "monitor"):
            self.monitor.set_update_rate(new_settings["update_rate"])
        self.save_settings()
        self.update_status("设置已保存并生效")

    # ---------------- 窗口事件 ----------------

    def moveEvent(self, event):
        super().moveEvent(event)
        self.schedule_save()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.schedule_save()

    def closeEvent(self, event):
        try:
            self.save_settings()
        except Exception:
            pass
        if hasattr(self, "monitor") and self.monitor:
            self.monitor.stop()
            self.monitor.wait(2000)
        for name in ("time_timer", "fps_timer", "_save_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        event.accept()


# ---------------------------------------------------------------- 入口

def main():
    global FONT_FAMILY
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    FONT_FAMILY = pick_font_family()
    if FONT_FAMILY:
        app.setFont(ui_font(9))

    ensure_icon()

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(245, 245, 245))
    palette.setColor(QPalette.WindowText, Qt.black)
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(240, 240, 240))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.black)
    palette.setColor(QPalette.Text, Qt.black)
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ButtonText, Qt.black)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Highlight, QColor(76, 175, 80))
    palette.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(palette)

    window = MainWindow()
    if os.path.exists(ICON_FILE):
        try:
            window.setWindowIcon(QIcon(ICON_FILE))
        except Exception:
            pass
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
