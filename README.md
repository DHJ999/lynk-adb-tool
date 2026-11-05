# 领克车机 ADB 工具

连接领克 CS11（`geely_fx11` / Android 11）车机，一键上传、安装、启动 APK 的
Windows 桌面小工具。本目录是整理后的自包含版本，双击 `车机安装工具.bat` 即可运行。

GitHub：<https://github.com/DHJ999/lynk-adb-tool>

## 目录内容

| 文件 | 作用 |
|---|---|
| `车机安装工具.bat` | 主启动器，自动寻找带 tkinter 的 pythonw.exe |
| `诊断启动.bat` | 用 python.exe 启动，出错时能看到完整报错 |
| `lynk_adb_tool.py` | 主程序（唯一需要的 .py） |
| `检查环境.bat` | 检查 Python / tkinter / adb / aapt2 |
| `依赖说明.txt` | 依赖清单 |
| `requirements.txt` | 空依赖，表示没有 pip 包 |

## 为什么需要它

这台车机的 adbd 有三个坑，普通 `adb install` 全部失败：

| 坑 | 现象 | 本工具的处理 |
|---|---|---|
| adbd 过滤命令字符串里的 `install` | `adb install` / `pm install` 一律 `error: closed` | 用 `ins''tall` 引号拼接绕过，adbd 看到的字符串不含 `install` |
| USB 链路不稳（自制线） | 随机 `error: closed` / `offline` | 每次操作前自动 `kill-server` 重连，命令失败自动重试 3 次 |
| 车机 ADB 重启后关闭 | `adb devices` 为空 | 「重新检测」按钮重新走一遍握手 |

## 为什么只有一个 .py

程序只导入了 Python 标准库：

```text
os queue re subprocess sys threading time tkinter
```

没有自定义模块，也没有第三方 pip 包。`tkinter` 是 Python 自带模块，不是单独文件。
之前看起来“还需要一些 py 文件”，通常是 Python 环境缺少 `tkinter`，而不是项目缺文件。

## 运行环境

- Windows 10/11
- Python 3.10+，必须带 tkinter；启动器优先使用 uv 的 3.12 解释器
- adb：必需，自动从 `%ANDROID_HOME%`、`%LOCALAPPDATA%\Android\Sdk`、
  `D:\Android\Sdk` 等位置查找，也可在界面里手动指定
- aapt2（可选）：从 SDK `build-tools` 自动定位，用于解析包名和启动入口

## 使用

1. 双击 `检查环境.bat`，确认：
   - `tkinter: OK`
   - `adb:` 后面有路径
   - `aapt2:` 有路径（可选）
2. 双击 `车机安装工具.bat`
3. 确认状态灯为绿色「已连接」（红色则点「重新检测」，或检查车机开发者选项里的 USB 调试）
4. 浏览选择 APK → **① 上传到车机** → **② 安装** → **③ 启动应用**
5. 出问题点 **④ 抓日志**，日志落到 `E:\Code\_logs\xiaoba_logcat_<时间戳>.txt`

### 装重签名包（例如小八桌面的改造版）

原版签名和新包签名不同，`pm install -r` 必然报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`。
默认勾选的「覆盖安装」会自动处理：**先卸旧版，再装新版**，不需要手动点卸载。

> 卸载会清掉该应用的数据。对小八桌面这类 Launcher，卸载到装回之间车机会短暂回落到原厂桌面。

## 2026-11-04 修订

| 改动 | 原因 |
|---|---|
| 安装遇 `UPDATE_INCOMPATIBLE` 自动卸旧版重装（可关） | 装改造包必踩，原来要手动点「卸载」再回来点「安装」 |
| 上传后核对设备端文件大小（`stat -c %s`） | 自制 USB 线传 76 MB 容易半截中断；原来只看 "pushed" 字样，会把半截包当成功 |
| 上传超时 300s → 600s | 76 MB 走不稳的链路，300 秒不够 |
| 未上传就点「安装」直接拦下 | 原来会装 `/data/local/tmp/upload.apk` 里**上一次残留的包**，可能装错应用 |
| 新增「④ 抓日志」 | 桌面起不来时不用另开命令行 |
| `_health` 区分 unauthorized / offline / 未连接 | 原来三种情况都只报「未检测到设备」 |
| 修 `find_aapt2` 版本比较 bug | 原来拿路径首字符当版本号比较，实际靠排序巧合选对 |

## 2026-11-05 修订

- 启动器修正了 uv Python 路径：`%APPDATA%\uv\python\...`，不再误用 `%LOCALAPPDATA%`
- 启动前执行 `pythonw -c "import tkinter"` 自检，缺 tkinter 时给出可见提示
- 所有 `.bat` 改为 CRLF 行尾，避免 cmd 解析截断
- 新增 `诊断启动.bat`，用带控制台的 `python.exe` 显示完整报错

## 发布到 GitHub（让别人下载就能用）

推荐分两种东西：

1. **源码仓库**：只放 `.py`、`.bat`、README、LICENSE，不放 Python 运行时。
2. **Release 压缩包**：放 PyInstaller 打出来的 `LynkAdbTool.exe` + `tools\adb\`，
   用户解压后双击 exe，不需要安装 Python，也不需要 Android SDK。

### Python 要不要放进目录

**不要。** 两种做法选一种：

- 源码运行：要求用户安装 Python 3.10+（带 tkinter），双击 `车机安装工具.bat`
- 发布 exe：用 PyInstaller 把 Python 运行时打进 `LynkAdbTool.exe`，
  用户不需要 Python

不要把整个 Python 安装目录提交到 Git，体积大、平台绑定、也没必要。

### adb 要不要放进目录

**发布包里要放，源码仓库里不放。**

- 程序优先找 `tools\adb\adb.exe`（见 `lynk_adb_tool.py` 的 `find_adb`）
- 源码仓库用 `.gitignore` 排除 adb 二进制
- `build_release.bat` / GitHub Actions 在打包时从 Android SDK 或 Google
  官方 platform-tools 复制进来

这样仓库不会因为 8 MB 的 exe 变臃肿，下载 Release 的用户又能开箱即用。

`aapt2` 是可选依赖：想在没有 Android SDK 的电脑上自动解析包名，
就把 `aapt2.exe` 放到 `tools\aapt2\`；不放也能上传/安装，只是启动和卸载
需要手动填包名。

### 本地打发布包

```bat
python -m pip install pyinstaller
build_release.bat
```

输出：

```text
release\LynkAdbTool\LynkAdbTool.exe
release\LynkAdbTool\tools\adb\adb.exe
release\LynkAdbTool-win64.zip
```

把 `LynkAdbTool-win64.zip` 上传到 GitHub Releases 即可。

### 提交源码仓库

```bash
git init
git add .
git commit -m "feat: 领克车机 ADB 安装工具"
git branch -M main
git remote add origin https://github.com/DHJ999/lynk-adb-tool.git
git push -u origin main
```

### 发 Release

```bash
git tag v1.0.0
git push origin v1.0.0
```

仓库里的 `.github/workflows/release.yml` 会在推送 `v*` 标签时自动：

1. 下载官方 platform-tools
2. 用 PyInstaller 打包 exe
3. 把 adb 放进 `tools\adb\`
4. 生成 `LynkAdbTool-win64.zip`
5. 创建 GitHub Release 并上传压缩包

需要在仓库的 **Settings → Actions → General → Workflow permissions**
里允许 `Read and write permissions`。

### 发布前检查

- `git status` 里没有 `*.apk`、`*.log`、`build/`、`dist/`、`release/`
- 在**没装 Python、没装 Android SDK** 的 Windows 上解压 Release ZIP，
  双击 `LynkAdbTool.exe` 能打开界面并识别 `tools\adb\adb.exe`
- README 里写清楚：只支持 Windows；车机需要开启 USB 调试
- 自己的代码用 MIT；分发的 platform-tools 保留 Google 的 Apache 2.0 许可与 NOTICE

## 目录结构

```text
领克8155车机安装工具/
├── 车机安装工具.bat      主启动器
├── 诊断启动.bat          带控制台启动，排错用
├── 检查环境.bat          Python/tkinter/adb/aapt2 自检
├── lynk_adb_tool.py      主程序
├── LynkAdbTool.spec      PyInstaller 配置
├── build_release.bat     本地打发布包
├── requirements.txt      空依赖
├── 依赖说明.txt          依赖清单
├── README.md             本文件
├── LICENSE               MIT
├── .gitignore
├── .github/workflows/release.yml
└── tools/
    ├── adb/README.md     adb 放置说明
    └── aapt2/README.md   aapt2 放置说明（可选）
```

## 常见问题

### 双击后闪一下就没反应

原来启动器选中了 PATH 里的 `D:\python-3.10.9-embed-amd64\pythonw.exe`，
这个嵌入式 Python 没有 tkinter；`pythonw` 又没有控制台，所以界面创建失败时
只能看到终端闪一下。

现在启动器会优先使用 `%APPDATA%\uv\python\cpython-3.12.13...\pythonw.exe`，
并在启动前执行 tkinter 自检。仍然闪退时，双击 `诊断启动.bat` 查看完整报错。

**如果双击后没反应、闪退，或提示缺模块：双击 `诊断启动.bat`，把终端里的报错保留下来排查。**

### adb 显示 offline

软件里关闭再打开 USB 调试通常无效。请在**车机端**拔插 USB（不是只拔电脑端），
或重启车机；弹窗出现时点「允许 / 始终允许」。

### 同时插了手机

本工具默认选 `adb devices` 里第一台 `device` 状态的设备。如果同时插了手机，
可能装到手机上。使用前先拔掉手机，或只保留车机的 USB 连接。

### 没有 aapt2

不影响上传和安装，只是无法自动解析包名，启动/卸载按钮需要手动填包名。

## 已知限制

- 只做「上传 / 安装 / 启动 / 卸载」四件事，不做应用管理列表
- 安装成功后若未找到 aapt2，需手动填包名才能卸载/启动
- 车机断线时所有操作会阻塞在重连，最长约 30 秒后报错
