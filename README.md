# GamepadDisplay v7.1.0

> **一句话**：GamepadDisplay —— 一个用 Python 写的 Windows 桌面程序，
> 主程序为 `GamepadDisplay.py`，界面技术栈 PyQt5（Qt5 社区绑定）。
>
> **适合谁**：想直接用现成工具、不想自己写代码的 Windows 用户。
>
> **解决什么问题**：把这件事做成开箱即用的程序 —— 下载解压、装上依赖、双击就能跑。

---

## 目录

- [1. 这是什么](#1-这是什么)
- [2. 零基础入门（5 分钟跑起来）](#2-零基础入门5-分钟跑起来)
- [3. 功能与界面](#3-功能与界面)
- [4. 命令行参数](#4-命令行参数)
- [5. 配置文件与数据](#5-配置文件与数据)
- [6. 工作原理（技术参考）](#6-工作原理技术参考)
- [7. 排错手册](#7-排错手册)
- [8. 常见问题 FAQ](#8-常见问题-faq)
- [9. 目录结构](#9-目录结构)
- [10. 开发与构建](#10-开发与构建)
- [11. 已知限制与安全说明](#11-已知限制与安全说明)
- [12. 许可](#12-许可)

## 1. 这是什么

| 项目 | 说明 |
| --- | --- |
| 程序名 | `GamepadDisplay` |
| 当前版本 | v7.1.0 |
| 主程序 | `GamepadDisplay.py` |
| 界面技术 | PyQt5（Qt5 社区绑定） |
| 语言 / 运行平台 | Python 3.10 / Windows |
| 源码规模 | 根目录及子模块共 1 个 .py 文件 |
| 仓库 | https://github.com/duma520/GamepadDisplay |

## 2. 零基础入门（5 分钟跑起来）

### 第 1 步：装 Python

1. 打开 <https://www.python.org/downloads/windows/>，下载 Python 3.10 或更新版本。
2. 安装时**务必勾选** `Add python.exe to PATH`（安装向导第一页最下方）。
3. 装完按 `Win + R` 输入 `cmd`，敲 `python --version`，能看到版本号就成功了。

### 第 2 步：拿到源码

- **下载压缩包**：在本仓库 Releases 页下载 `GamepadDisplay-*.zip`，解压到任意目录。
- **git 克隆**：`git clone https://github.com/duma520/GamepadDisplay.git`

### 第 3 步：装依赖

在源码目录打开命令行，执行：

```
pip install Pillow PyQt5 pygame
```

> 清单是从源码的实际 import 汇总出来的；若某个包名不准确，以 pip 报错提示的正确包名为准。

### 第 4 步：启动

```bat
python GamepadDisplay.py
```

目录里还带了 `1.bat`，双击等同于上面的命令（前提是 Python 在 PATH 里）。

## 3. 功能与界面

> 本节只列源码里能确认的事实；具体按钮与交互以运行后的界面为准。

| 维度 | 实际情况 |
| --- | --- |
| 界面框架 | PyQt5（Qt5 社区绑定） |
| 是否有 main 入口 | 是，可直接 python 主程序.py 运行 |
| 第三方依赖数 | 3 个 |

### 版本变更（来自项目自带迭代记录）

| 版本 | 说明 |
| --- | --- |
| 4 | 已暂停 → 发 `{'connected': False, 'paused': True}` |
| 5 | 需要时缓存/重建 `Joystick(idx)`（**不再每帧 init**） |
| 6 | 采集 axes / buttons / hats → `data_updated` 信号 |
| 7 | `time.sleep(1 / update_rate)`，默认 25 Hz（可调 5–120） |
| v6.0 | 最后一个无文档版本；本次对其做了全量审查，登记 19 项缺陷 |
| **v7.0** | 完整重写：修复 P0×4 / P1×8 / P2×7；新增多手柄切换、右摇杆与 R3、XY 摇杆可视化、设置对话框、按键映射预设、死区、暂停/继续、动态轴/按钮/十字键、性能节流；补齐图标与脚本路径 |
| **v7.0.1** | 热修绘制崩溃：`paintEvent` 浮点坐标导致 `drawEllipse` TypeError；改为整数运算；屏蔽 PyQt5 弃用警告；新增渲染回归测试方法 |
| **v7.1.0** | 修正十字键上下方向反了（pygame 约定 y=1 为上）；新增扳机 LT/RT 轴驱动与「扳机工作模式/阈值」设置；方向键组由 Hat 自动联动；补充控件来源 ToolTip |

## 4. 命令行参数

该程序没有定义命令行参数，直接运行即可（操作都在界面里完成）。

## 5. 配置文件与数据

源码目录里可见的配置/数据文件：

- `gamepad_config.json`
- `joystick_config.json`

这些文件在运行时读写；个人数据（路径、账号、历史记录）不会提交到仓库，由 .gitignore 排除，首次运行会自动生成。

## 6. 工作原理（技术参考）

```
用户操作 → PyQt5 → 业务逻辑 → 结果输出
```

- 入口文件 `GamepadDisplay.py`，带 if __name__ == '__main__' 保护。
- 依赖的第三方库：`Pillow`、`PyQt5`、`pygame`。
- 全部业务逻辑在仓库内可见，没有编译产物、没有联网下发代码。

## 7. 排错手册

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| python 不是内部或外部命令 | 安装时没勾 PATH | 重装 Python 并勾选 Add python.exe to PATH，或改用 py 命令 |
| ModuleNotFoundError: No module named xxx | 依赖没装 | 按第 3 步 pip install 对应包 |
| 双击 .bat 一闪而过 | 出错后窗口立即关闭 | 用 cmd 进入目录再执行命令，看清报错 |
| 界面显示乱码 | 控制台编码不是 UTF-8 | 先执行 chcp 65001，或用 python -X utf8 主程序.py |
| 杀毒软件拦截 | 未签名脚本被误判 | 加入信任/白名单；本项目只提供源码，可自行审阅 |

## 8. 常见问题 FAQ

**Q1：需要装 Visual Studio 之类的编译工具吗？**
A：不需要。这里只提供 Python 源码，pip 装的是预编译轮子。

**Q2：能在 macOS / Linux 上跑吗？**
A：本项目按 Windows 环境开发与验证；其他系统未测试，可能需要改路径与系统 API 调用。

**Q3：为什么 Releases 里只有源码 zip，没有 exe？**
A：只分发源码，避免二进制被误判；需要 exe 请按第 10 节自行打包。

**Q4：改了代码怎么运行？**
A：直接 python 主程序.py，改动立即生效，无需编译。

**Q5：数据存在哪？会不会被上传？**
A：只存在本机（程序目录或用户目录）。本程序不含上传逻辑。

**Q6：怎么反馈问题？**
A：到 https://github.com/duma520/GamepadDisplay/issues 提 Issue，附上报错原文与复现步骤。

## 9. 目录结构

```
.workbuddy/
.env.example
.gitignore
0.bat
1.bat
GamepadDisplay.py
README.md
gamepad_config.json
icon.ico
joystick_config.json
软件升级迭代记录.md
.workbuddy\memory/
.workbuddy\memory\2026-09-27.md
.workbuddy\memory\2026-09-28.md
.workbuddy\memory\MEMORY.md
```

## 10. 开发与构建

- 直接运行（开发态）：`python GamepadDisplay.py`
- 语法自检：`python -m py_compile GamepadDisplay.py`
- 打包 exe（可选）：装 pyinstaller 后执行 `pyinstaller -F -w GamepadDisplay.py`

## 11. 已知限制与安全说明

- 只提供源码，不提供预编译二进制。
- 仓库不含任何凭据；.env / *.pem / *.key / 日志与运行期数据均在 .gitignore 中排除。
- 若程序需要联网，请在源码中确认目标地址后再运行。

## 12. 许可

AGPL-3.0，详见仓库根目录 LICENSE。
