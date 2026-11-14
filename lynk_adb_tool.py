# -*- coding: utf-8 -*-
"""
领克车机 ADB 工具
=================
连接领克 CS11（geely_fx11 / Android 11）车机，上传 APK 并安装。

针对这台车机的三个已知坑做了专门处理：
1. adbd 会拒绝任何包含 "install" 子串的 shell 命令 → 用 ins''tall 引号拼接绕过
2. USB 链路不稳（自制线），经常 error: closed / offline → 自动重连重试
3. Git Bash 路径转换 → 本程序直接调 adb，不经过 shell，无此问题

依赖：Python 3.10+ / tkinter（uv python 自带）
"""
import os
import queue
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import zipfile
from tkinter import filedialog, messagebox, scrolledtext, ttk

APP_TITLE = "领克车机 ADB 工具"
REMOTE_APK = "/data/local/tmp/upload.apk"
FEEDBACK_EMAIL = "hjd2002@yeah.net"

# 命令终端的预设命令：(按钮名, 模式, 命令)
#   shell = 车机内执行（adb shell xxx）；adb = 本机 adb 子命令；shot = 走特殊流程（截图并拉回本地）
ADB_PRESETS = [
    ("设备信息", "shell", "getprop ro.product.model; getprop ro.build.version.release; "
                          "getprop ro.build.display.id"),
    ("分辨率/密度", "shell", "wm size; wm density"),
    ("电池状态", "shell", "dumpsys battery"),
    ("存储空间", "shell", "df -h /data /sdcard"),
    ("前台应用", "shell", "dumpsys activity activities | grep -E 'mResumedActivity|mFocusedApp'"),
    ("CPU 占用", "shell", "top -n 1 -b -o %CPU,ARGS | head -15"),
    ("内存占用", "shell", "dumpsys meminfo | head -25"),
    ("网络地址", "shell", "ip addr show | grep -E 'inet |state'"),
    ("第三方应用数", "shell", "pm list packages -3 | wc -l"),
    ("最近崩溃", "shell", "logcat -d -b crash -t 80"),
    ("亮屏/息屏", "shell", "input keyevent 26"),
    ("返回桌面", "shell", "input keyevent 3"),
    ("截图到本地", "shot", ""),
    ("重连 adb", "adb", "reconnect"),
    ("adb 版本", "adb", "version"),
]

# 主题：跟随 Windows 显示模式（注册表 AppsUseLightTheme，0=深色）
def detect_dark_mode() -> bool:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        light, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
        return light == 0
    except Exception:
        return True   # 读不到默认深色

THEMES = {
    "dark": dict(BG="#16181D", PANEL="#1F232B", PANEL2="#262B34", FG="#E8EDF2",
                 FG_DIM="#8A97A5", ACCENT="#01AAFF", ACCENT_FG="#0B0F12",
                 RED="#FF5A5A", AMBER="#FFB020", BORDER="#0B0D10",
                 HOVER="#333B46", HOVER_ACCENT="#4FC3FF"),
    "light": dict(BG="#F2F4F7", PANEL="#FFFFFF", PANEL2="#E9EDF2", FG="#1B1F24",
                  FG_DIM="#5A6470", ACCENT="#01AAFF", ACCENT_FG="#0B0F12",
                  RED="#D94848", AMBER="#A96E00", BORDER="#D8DDE3",
                  HOVER="#DCE2E9", HOVER_ACCENT="#0090D8"),
}
IS_DARK = detect_dark_mode()
_T = THEMES["dark" if IS_DARK else "light"]
BG, PANEL, PANEL2 = _T["BG"], _T["PANEL"], _T["PANEL2"]
FG, FG_DIM = _T["FG"], _T["FG_DIM"]
ACCENT, ACCENT_FG = _T["ACCENT"], _T["ACCENT_FG"]
RED, AMBER, BORDER = _T["RED"], _T["AMBER"], _T["BORDER"]
HOVER, HOVER_ACCENT = _T["HOVER"], _T["HOVER_ACCENT"]


def set_theme_globals(is_dark: bool):
    """运行时切换主题：重赋值全局配色（各窗口重建后生效）。"""
    global BG, PANEL, PANEL2, FG, FG_DIM, ACCENT, ACCENT_FG, RED, AMBER, BORDER, HOVER, HOVER_ACCENT
    _T = THEMES["dark" if is_dark else "light"]
    BG, PANEL, PANEL2 = _T["BG"], _T["PANEL"], _T["PANEL2"]
    FG, FG_DIM = _T["FG"], _T["FG_DIM"]
    ACCENT, ACCENT_FG = _T["ACCENT"], _T["ACCENT_FG"]
    RED, AMBER, BORDER = _T["RED"], _T["AMBER"], _T["BORDER"]
    HOVER, HOVER_ACCENT = _T["HOVER"], _T["HOVER_ACCENT"]


def make_button(parent, text, command, accent=False, danger=False):
    """深色扁平按钮；accent=主题绿主按钮，danger=红色危险操作。
    配合 set_enabled() 做优雅禁用（保留原配色信息在 _bg/_fg）。"""
    if accent:
        bg, fg, hbg = ACCENT, ACCENT_FG, HOVER_ACCENT
    elif danger:
        bg, fg, hbg = RED, "#FFFFFF", hexshade(RED, 0.85 if IS_DARK else 1.12)
    else:
        bg, fg, hbg = PANEL2, FG, HOVER
    b = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                  activebackground=hbg, activeforeground=fg, relief="flat", bd=0,
                  padx=14, pady=6, highlightthickness=0, cursor="hand2",
                  font=("Microsoft YaHei UI", 10, "bold") if accent else ("Microsoft YaHei UI", 10))
    b._bg, b._fg, b._hbg = bg, fg, hbg
    b._enabled = True
    # 禁用态不参与 hover，否则鼠标划过再移开会把按钮刷回正常配色，看着像没禁用
    b.bind("<Enter>", lambda _e: b._enabled and b.configure(bg=b._hbg))
    b.bind("<Leave>", lambda _e: b._enabled and b.configure(bg=b._bg))
    return b


def set_enabled(b, enabled: bool):
    """禁用时降为暗色，恢复时回到按钮自己的配色。"""
    b._enabled = enabled
    if enabled:
        b.configure(state="normal", bg=b._bg, fg=b._fg)
    else:
        b.configure(state="disabled", bg=PANEL2, fg=FG_DIM)


def hexshade(color: str, factor: float) -> str:
    """颜色明暗调整：factor>1 变亮，<1 变暗。"""
    c = color.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    f = lambda v: max(0, min(255, int(v * factor)))
    return f"#{f(r):02X}{f(g):02X}{f(b):02X}"


def flat_panel(parent) -> tk.Frame:
    """扁平面板：纯色底 + 1px 细边。"""
    return tk.Frame(parent, bg=PANEL, highlightthickness=1,
                    highlightbackground=BORDER, highlightcolor=BORDER)


def app_dir() -> str:
    """源码运行时是 .py 所在目录；PyInstaller 打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = app_dir()


def enable_dpi_awareness():
    """声明 DPI 感知：高缩放屏上字体由系统按矢量渲染，不再被拉伸发糊。
    必须在创建 tk.Tk() 之前调用。用 system-aware（1），tkinter 对
    per-monitor 的 WM_DPICHANGED 支持不好，跨屏拖动会乱。"""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def asset_path(*parts) -> str:
    """资源文件路径：源码运行时在 APP_DIR，PyInstaller 打包后在 _MEIPASS。"""
    for base in (APP_DIR, getattr(sys, "_MEIPASS", APP_DIR)):
        p = os.path.join(base, *parts)
        if os.path.isfile(p):
            return p
    return ""


def window_icon():
    """窗口图标路径：源码运行在 assets/，打包后在 _internal/assets/。"""
    return asset_path("assets", "icon.ico")


def apply_window_icon(window):
    """给窗口挂自定义图标；找不到图标文件时静默跳过（保留默认）。"""
    p = window_icon()
    if p:
        try:
            window.iconbitmap(p)
        except Exception:
            pass

ADB_CANDIDATES = [
    os.path.join(APP_DIR, "tools", "adb", "adb.exe"),
    os.path.join(APP_DIR, "tools", "platform-tools", "adb.exe"),
    os.path.expandvars(r"%ANDROID_HOME%\platform-tools\adb.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    r"D:\Android\Sdk\platform-tools\adb.exe",
    r"C:\Android\Sdk\platform-tools\adb.exe",
    r"D:\Android\platform-tools\adb.exe",
]


def find_adb() -> str:
    for p in ADB_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    # PATH 兜底
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("adb.exe", "adb"):
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return cand
    return "adb"


def find_aapt2() -> str:
    """从 SDK build-tools 里找最新的 aapt2，用来解析包名。
    查找顺序：环境变量 LYNK_AAPT2 → 程序自带 tools\\aapt2 → 各 SDK 的 build-tools 最新版。"""
    env = os.environ.get("LYNK_AAPT2", "").strip()
    if env and os.path.isfile(env):
        return env

    local = os.path.join(APP_DIR, "tools", "aapt2", "aapt2.exe")
    if os.path.isfile(local):
        return local

    sdk_roots = [
        os.path.expandvars(r"%ANDROID_HOME%"),
        os.path.expandvars(r"%ANDROID_SDK_ROOT%"),
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk"),
        r"D:\Android\Sdk",
        r"C:\Android\Sdk",
        r"E:\Android\Sdk",
    ]
    # 顺带按「adb 所在目录的父级 / 同级」推测，覆盖 SDK 被改名或放在非标准盘的情况
    adb = find_adb()
    if os.path.isfile(adb):
        adb_dir = os.path.dirname(adb)
        sdk_roots.append(os.path.dirname(adb_dir))           # <sdk>/platform-tools
        sdk_roots.append(os.path.join(os.path.dirname(adb_dir), "sdk"))

    best, best_ver = "", (-1, -1, -1)
    for root in sdk_roots:
        if not root:
            continue
        bt = os.path.join(root, "build-tools")
        if not os.path.isdir(bt):
            continue
        for ver in os.listdir(bt):
            exe = os.path.join(bt, ver, "aapt2.exe")
            if not os.path.isfile(exe):
                continue
            try:
                key = tuple(int(x) for x in ver.split(".")[:3])
            except Exception:
                continue  # 跳过 36.0.0-rc1 之类
            key = key + (0,) * (3 - len(key))
            if key > best_ver:
                best, best_ver = exe, key
    return best


# adb devices 行尾可能出现的合法状态词；用来挡掉 daemon 提示行等噪声
DEVICE_STATES = {
    "device", "offline", "unauthorized", "authorizing", "connecting",
    "bootloader", "recovery", "rescue", "sideload", "host", "no", "unknown",
}


def parse_devices(out: str):
    """解析 `adb devices` 输出 → [(serial, state), ...]。

    adb 启动守护进程时会往输出里掺 `* daemon not running...` / `* daemon started
    successfully`，另外还有 `List of devices attached` 表头。这些行不能当成设备，
    否则会冒出 serial 为 "*" 的幽灵设备，导致误弹设备选择框。
    """
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("*") or line.startswith("List of devices"):
            continue
        if "daemon" in line:
            continue
        parts = line.split()
        if len(parts) < 2 or parts[1] not in DEVICE_STATES:
            continue
        rows.append((parts[0], parts[1]))
    return rows


class AdbClient:
    """带自动重连的 adb 封装。所有方法阻塞，必须放后台线程跑。"""

    def __init__(self, adb_path: str, log, aapt2: str = ""):
        self.adb = adb_path
        self.log = log
        self.aapt2 = aapt2
        self.serial = None
        self.model = ""          # 当前目标设备型号（卸载确认时展示，防打错设备）
        self.label_cache = {}    # {包名: 应用名}，落盘到 label_cache.json，重开秒出
        self.cache_file = os.path.join(APP_DIR, "label_cache.json")
        try:
            if os.path.isfile(self.cache_file):
                import json
                with open(self.cache_file, encoding="utf-8") as f:
                    self.label_cache = json.load(f)
        except Exception:
            pass

    def save_label_cache(self):
        try:
            import json
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.label_cache, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------- 低层 ----------
    @staticmethod
    def _spawn(cmd, timeout):
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            return -1, "命令超时"
        except FileNotFoundError:
            return -1, f"找不到 adb：{cmd[0]}"
        except Exception as e:
            return -1, str(e)

    def _run(self, args, timeout=60):
        cmd = [self.adb] + args
        if self.serial:
            cmd[1:1] = ["-s", self.serial]
        return self._spawn(cmd, timeout)

    @staticmethod
    def _is_link_error(out: str) -> bool:
        """只匹配 adb 链路层的完整错误短语，避免把正常输出误判成断链。"""
        out = out.strip()
        phrases = (
            "error: closed",          # 传输被关闭（车机 adbd 常见）
            "error: device",          # error: device offline / device not found
            "device offline",
            "offline device",
            "no devices",             # no devices/emulators found
            "no emulators found",
            "cannot connect",
        )
        return any(p in out for p in phrases)

    def _restart_server(self):
        self._run(["kill-server"], timeout=15)
        time.sleep(1)
        self._run(["start-server"], timeout=20)

    def _wait_devices(self, seconds=24):
        """轮询设备列表直到有设备上线或超时。返回 {serial: state}。"""
        deadline = time.time() + seconds
        states = {}
        while time.time() < deadline:
            code, out = self._run(["devices"], timeout=15)
            states = dict(parse_devices(out))
            if "device" in states.values():
                return states
            time.sleep(2)
        return states

    def _health(self):
        """恢复 adb 链路。先温和处理（不动 adb server，避免殃及其他 adb 工作流），
        目标掉线或服务器无设备时才 kill-server。返回 (ok, 信息)。"""
        states = dict(self.list_devices())

        # 1) 目标设备仍在线：温和重置该传输通道即可
        if self.serial and states.get(self.serial) == "device":
            self._run(["reconnect"], timeout=10)
            time.sleep(1)
            return True, f"{self.serial} 在线（已温和重连）"

        # 2) 没有指定目标且有任何在线设备：直接可用（由上层选择流程决定目标）
        if "device" in states.values() and not self.serial:
            return True, "、".join(f"{s}({st})" for s, st in states.items())

        # 3) 目标 offline：重启 server 并等待恢复
        if self.serial and states.get(self.serial) == "offline":
            self._restart_server()
            states = self._wait_devices()
            if states.get(self.serial) == "device":
                return True, f"{self.serial} 已恢复"
            return False, "设备 offline：拔插 USB 或重启车机再试"

        # 4) 没有任何在线设备：server 可能卡死，重启后等待
        self._restart_server()
        states = self._wait_devices()
        if "device" in states.values():
            return True, "、".join(f"{s}({st})" for s, st in states.items())
        if "unauthorized" in states.values():
            return False, "设备未授权：看车机屏幕点「允许 USB 调试」，勾选「一律允许」"
        if "offline" in states.values():
            return False, "设备 offline：拔插 USB 或重启 adb（本工具已重试过），换一个车机 USB 口"
        return False, "未检测到设备（检查 USB 线与开发者选项里的 USB 调试）"

    # ---------- 对外 ----------
    def list_devices(self):
        """[(serial, state), ...]"""
        code, out = self._run(["devices"], timeout=15)
        return parse_devices(out)

    def query_model(self, serial: str):
        """查询指定设备的型号。返回 (型号, 是否领克车机)。"""
        code, out = self._spawn(
            [self.adb, "-s", serial, "shell",
             "getprop ro.product.model; getprop ro.product.manufacturer"],
            timeout=20,
        )
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        model = lines[0] if lines else ""
        manu = lines[1].lower() if len(lines) > 1 else ""
        is_lynk = bool(re.search(r"CS\d+", model)) or "geely" in manu or "ecarx" in manu
        return model or "未知型号", is_lynk

    def run_retry(self, args, timeout=120, retries=3, label=""):
        """执行 adb 命令；链路错误时自动重连重试。"""
        last = ""
        for i in range(retries):
            code, out = self._run(args, timeout=timeout)
            if not self._is_link_error(out):
                return code, out
            last = out.strip().splitlines()[-1] if out.strip() else "未知链路错误"
            if i < retries - 1:
                self.log(f"⚠ 链路中断（{last}），第 {i + 1} 次自动重连…")
                ok, _ = self._health()
                if not ok:
                    return -1, "车机未连接"
        return -1, last

    def device_info(self):
        code, out = self.run_retry(
            ["shell", "getprop ro.product.model; getprop ro.build.version.release"],
            timeout=30, retries=2,
        )
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        if len(lines) >= 2:
            return f"{lines[0]} · Android {lines[1]}"
        return "已连接"

    def _pm_paths(self, flag: str):
        """pm list packages -f：一次拿全部包的 APK 路径，省掉每包一次 pm path。"""
        code, out = self.run_retry(
            ["shell", "pm", "list", "packages", "-f", flag],
            timeout=60, retries=2,
        )
        paths = {}
        for line in out.splitlines():
            if not line.startswith("package:"):
                continue
            body = line.split(":", 1)[1].strip()
            if "=" in body:
                apk, pkg = body.rsplit("=", 1)
                paths[pkg.strip()] = apk.strip()
        return paths

    def list_apps(self, include_system=False, progress=None):
        """返回 [(应用名, 包名, 用户/系统), ...]。

        每个包要 2-3 次 adb 往返才能取到应用名，串行跑 100 个应用要几分钟；
        用 6 线程并发取 label，快一个数量级。结果按包名排序保持稳定。
        """
        import concurrent.futures

        user_paths = self._pm_paths("-3")
        system_paths = self._pm_paths("-s") if include_system else {}
        packages = sorted(set(user_paths) | set(system_paths))
        total = len(packages)
        labels = {}
        done = 0
        lock = threading.Lock()

        def work(pkg: str) -> str:
            nonlocal done
            label = self.label_cache.get(pkg)
            if label is None:
                label = self.package_label(pkg, user_paths.get(pkg)
                                           or system_paths.get(pkg))
                if label:
                    self.label_cache[pkg] = label
            with lock:
                done += 1
                if progress:
                    progress(done, total, pkg)
            return label

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(work, pkg): pkg for pkg in packages}
            for fut in concurrent.futures.as_completed(futures):
                pkg = futures[fut]
                try:
                    labels[pkg] = fut.result()
                except Exception:
                    labels[pkg] = ""

        self.save_label_cache()
        rows = []
        for pkg in packages:
            kind = "系统" if pkg in system_paths else "用户"
            rows.append((labels.get(pkg) or "—", pkg, kind))
        return rows

    def package_label(self, pkg: str, apk_path: str = None) -> str:
        """用 AndroidManifest + resources.arsc 生成 mini APK，取应用名。"""
        if not self.aapt2:
            return ""

        apk = apk_path or ""
        if not apk:
            _, out = self.run_retry(
                ["shell", "pm", "path", pkg], timeout=30, retries=1
            )
            for line in out.splitlines():
                if line.startswith("package:") and line.rstrip().endswith("base.apk"):
                    apk = line.split(":", 1)[1].strip()
                    break
            if not apk:
                for line in out.splitlines():
                    if line.startswith("package:"):
                        apk = line.split(":", 1)[1].strip()
                        break
        if not apk:
            return ""

        # 设备端临时文件名必须唯一：取标签是 6 线程并发跑的，
        # 若只用 pid（进程级）命名，各线程会抢写同一个文件、并在 finally 里互删。
        safe_pkg = re.sub(r"[^0-9A-Za-z._-]", "_", pkg)[:40]
        tag = f"{safe_pkg}_{threading.get_ident()}"
        remote_manifest = f"/data/local/tmp/lynk_{tag}_m.xml"
        remote_res = f"/data/local/tmp/lynk_{tag}_r.arsc"
        extract = (
            f"unzip -p '{apk}' AndroidManifest.xml > '{remote_manifest}' 2>/dev/null; "
            f"unzip -p '{apk}' resources.arsc > '{remote_res}' 2>/dev/null"
        )
        self.run_retry(["shell", extract], timeout=60, retries=1)

        try:
            with tempfile.TemporaryDirectory(prefix="lynk_label_") as td:
                local_manifest = os.path.join(td, "AndroidManifest.xml")
                local_res = os.path.join(td, "resources.arsc")
                if self._pull_quiet(remote_manifest, local_manifest) and \
                        self._pull_quiet(remote_res, local_res):
                    mini = os.path.join(td, "mini.apk")
                    try:
                        with zipfile.ZipFile(mini, "w", zipfile.ZIP_DEFLATED) as z:
                            z.write(local_manifest, "AndroidManifest.xml")
                            z.write(local_res, "resources.arsc")
                        label = self._aapt_label(mini)
                        if label:
                            return label
                    except Exception:
                        pass

                # 少数设备没有 unzip：退回拉完整 base.apk
                full = os.path.join(td, "base.apk")
                if self._pull_quiet(apk, full):
                    return self._aapt_label(full)
                return ""
        finally:
            self._run(
                ["shell", f"rm -f '{remote_manifest}' '{remote_res}'"],
                timeout=10,
            )

    def _pull_quiet(self, remote: str, local: str) -> bool:
        code, _ = self.run_retry(
            ["pull", remote, local], timeout=180, retries=1
        )
        return code == 0 and os.path.isfile(local) and os.path.getsize(local) > 0

    def _aapt_label(self, apk: str) -> str:
        try:
            p = subprocess.run(
                [self.aapt2, "dump", "badging", apk],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception:
            return ""
        default = ""
        for line in (p.stdout or "").splitlines():
            if line.startswith("application-label-zh-CN:"):
                return line.split(":", 1)[1].strip().strip("'")
            if line.startswith("application-label-zh:"):
                default = line.split(":", 1)[1].strip().strip("'")
            elif line.startswith("application-label:") and not default:
                default = line.split(":", 1)[1].strip().strip("'")
        return default

    def push(self, local_apk, progress=None):
        """上传 APK。progress 回调传 0~100 整数百分比（解析 adb push 自带的
        `[ 45%]` 输出），失败时清理设备端残留的半截文件。

        这里刻意不再用 `adb shell stat` 轮询设备端大小：progress 回调传的是
        真实的传输百分比，且不会在本就不稳的 USB 链路上再开一条并发通道。
        """
        size = os.path.getsize(local_apk)
        self.log(f"上传 {os.path.basename(local_apk)}（{size / 1048576:.1f} MB）→ {REMOTE_APK}")

        cmd = [self.adb]
        if self.serial:
            cmd[1:1] = ["-s", self.serial]
        cmd += ["push", local_apk, REMOTE_APK]

        last_err = ""
        for attempt in range(3):
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            chunks = []
            last_pct = [-1]

            def pump():
                """边读边解析进度，同时把管道排空（否则输出多了会卡住 adb）。"""
                tail = ""
                while True:
                    chunk = proc.stdout.read(256) if proc.stdout else ""
                    if not chunk:
                        break
                    chunks.append(chunk)
                    tail = (tail + chunk)[-200:]
                    hit = None
                    for m in re.finditer(r"\[\s*(\d{1,3})%\]", tail):
                        hit = int(m.group(1))
                    if hit is not None and hit != last_pct[0]:
                        last_pct[0] = hit
                        if progress:
                            progress(min(99, hit))

            reader = threading.Thread(target=pump, daemon=True)
            reader.start()
            try:
                proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
            finally:
                reader.join(timeout=5)

            if proc.returncode == 0:
                # 设备端核对大小，防止半截文件被当成装好了
                _, sz_out = self.run_retry(
                    ["shell", f"stat -c %s {REMOTE_APK}"], timeout=30, retries=2
                )
                remote_size = None
                for line in sz_out.splitlines():
                    if line.strip().isdigit():
                        remote_size = int(line.strip())
                if remote_size is not None and remote_size != size:
                    self.log(f"✗ 上传不完整：设备端 {remote_size} 字节 / 本地 {size} 字节")
                    self.cleanup_remote(REMOTE_APK)
                    return False
                if progress:
                    progress(100)
                self.log("✓ 上传完成")
                return True

            last_err = "".join(chunks).strip()
            last_err = last_err.splitlines()[-1] if last_err else f"exit={proc.returncode}"
            if not self._is_link_error(last_err) or attempt == 2:
                break
            self.log(f"⚠ 链路中断（{last_err}），第 {attempt + 1} 次自动重连…")
            ok, _ = self._health()
            if not ok:
                break

        self.log(f"✗ 上传失败：{last_err}")
        self.cleanup_remote(REMOTE_APK)   # 清掉半截残留
        return False

    @staticmethod
    def _fail_reason(text: str) -> str:
        m = re.search(r"Failure\s*\[([^\]]+)\]", text)
        if m:
            return m.group(1)
        return text.splitlines()[-1] if text else "未知原因"

    def _pm_install(self):
        """关键：命令字符串里不能出现连续的 install，用 ins''tall 绕过 adbd 过滤。"""
        code, out = self.run_retry(
            ["shell", "pm ins''tall -r " + REMOTE_APK], timeout=300, retries=3
        )
        return out.strip()

    def install(self, pkg=""):
        self.log("开始安装（已启用 install 过滤绕过）…")
        text = self._pm_install()
        if "Success" in text:
            self.log("✓ 安装成功")
            return True, ""
        reason = self._fail_reason(text)

        # 重签名包必然踩这个：签名与已装版本不同，必须先卸旧版。
        # 自动重试一次，避免在车边手动来回点。
        if pkg and "UPDATE_INCOMPATIBLE" in reason:
            self.log("⚠ 签名与已装版本不同（重签名包的正常现象），先卸载旧版再装…")
            if self.uninstall(pkg, quiet=True):
                text = self._pm_install()
                if "Success" in text:
                    self.log(f"✓ 卸载旧版后安装成功（{pkg}）")
                    return True, ""
                self.log(f"✗ 旧版已卸载，但安装仍失败：{self._fail_reason(text)}")
                self.log("⚠ 当前车机上已没有该应用，需要时用 rollback 装回官方原包")
                return False, self._fail_reason(text)

        self.log(f"✗ 安装失败：{reason}")
        return False, reason

    def uninstall(self, pkg, quiet=False):
        # 包名要拼进 shell 命令，先做白名单校验：aapt2 解析出的字符串若不合法，
        # 像 "x; rm -rf /" 这种会被带到设备端执行。
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+", pkg or ""):
            self.log(f"✗ 包名不合法，已拒绝执行：{pkg!r}")
            return False
        if not quiet:
            self.log(f"卸载 {pkg} …")
        code, out = self.run_retry(
            ["shell", "pm unin''stall '" + pkg + "'"], timeout=120, retries=2
        )
        ok = "Success" in out or "not installed" in out.lower()
        if ok:
            if not quiet:
                self.log(f"✓ 已卸载 {pkg}")
        else:
            self.log(f"✗ 卸载失败：{out.strip().splitlines()[-1] if out.strip() else '无输出'}")
        return ok

    def logcat(self, lines=1500):
        """抓最近若干行日志（先落设备文件再拉，避免 USB 大输出断链）。"""
        self.log(f"抓取日志（最近 {lines} 行）…")
        remote = f"/data/local/tmp/lc_{int(time.time())}.txt"   # 每次唯一，避免并发互踩
        cmd = f"logcat -d -t {lines} > {remote}"
        self.run_retry(["shell", cmd], timeout=120, retries=2)
        code, out = self.run_retry(
            ["shell", f"wc -l {remote}"], timeout=30, retries=2
        )
        self.log(f"设备端日志行数：{out.strip()}")
        return remote

    def cleanup_remote(self, path):
        """拉取完成后清掉设备端临时文件，避免 /data/local/tmp 堆垃圾。"""
        self._run(["shell", f"rm -f '{path}'"], timeout=15)

    def pull(self, remote, local):
        self.log(f"拉取 {remote} → {local}")
        os.makedirs(os.path.dirname(local), exist_ok=True)
        code, out = self.run_retry(["pull", remote, local], timeout=300, retries=3)
        if code == 0 and os.path.isfile(local):
            self.log(f"✓ 已保存：{local}（{os.path.getsize(local) / 1024:.0f} KB）")
            return True
        self.log(f"✗ 拉取失败：{out.strip().splitlines()[-1] if out.strip() else '无输出'}")
        return False

    def launch(self, component):
        self.log(f"启动 {component} …")
        code, out = self.run_retry(
            ["shell", "am start -W -n " + component], timeout=60, retries=2
        )
        ok = "Status: ok" in out or "Warning" in out
        if ok:
            self.log("✓ 已启动")
        else:
            self.log(f"✗ 启动失败：{out.strip().splitlines()[-1] if out.strip() else '无输出'}")
        return ok

    # ---------- 自定义命令终端 ----------
    @staticmethod
    def _shield_install(cmd: str) -> str:
        """车机 adbd 会掐掉含 "install" 子串的 shell 命令（返回 error: closed）。
        终端里用户手打的 pm install 同样会踩，这里统一替换成 ins''tall。"""
        return re.sub(r"install", "ins''tall", cmd)

    def shell_cmd(self, cmd: str, timeout=120):
        """在车机内执行一条 shell 命令。返回 (code, 输出)。"""
        cmd = cmd.strip()
        if not cmd:
            return -1, "命令为空"
        if not self.serial:
            return -1, "尚未选择设备，请先点「重新检测」"
        safe = self._shield_install(cmd)
        return self.run_retry(["shell", safe], timeout=timeout, retries=2, label="命令")

    def adb_cmd(self, cmd: str, timeout=120):
        """执行 adb 自身的子命令（reconnect / version / forward …，面向设备时自动带 -s）。"""
        cmd = cmd.strip()
        if not cmd:
            return -1, "命令为空"
        if cmd.startswith("adb "):
            cmd = cmd[4:].strip()
        try:
            args = shlex.split(cmd)
        except ValueError as e:
            return -1, f"命令解析失败：{e}"
        if not args:
            return -1, "命令为空"
        # adb shell 后面的部分要原样交给设备端，不能先被 shlex 拆散再拼回去：
        # 带空格的参数会被 adb 按空格重新拼接，引号就丢了
        if args[0] == "shell":
            rest = cmd[cmd.find("shell") + len("shell"):].strip()
            return self.shell_cmd(rest, timeout=timeout)
        # 只有面向设备的子命令才需要 -s；kill-server/start-server/devices 等带了会报错
        global_cmds = {"kill-server", "start-server", "devices", "version",
                       "help", "connect", "disconnect"}
        if not self.serial or args[0] in global_cmds:
            return self._spawn([self.adb] + args, timeout)
        return self.run_retry(args, timeout=timeout, retries=2, label="命令")

    # ---------- USB 链路稳定性 ----------
    # 这台车机的 USB gadget 功能集默认是 "carplay_carlife,adb"。车上的 CarPlay/CarLife
    # 探测服务会周期性重配 gadget（dmesg 里 USB_STATE=DISCONNECTED→CONNECTED→CONFIGURED
    # 反复刷屏，carplay_cnt 递增），每次重配都会拆掉 adbd 的 FunctionFS 通道
    # （adbd 日志 "UsbFfsConnection being destroyed"），adb 会话立刻断开。
    # 典型现象：Windows 里 USB 硬件一直在，只有 adb 掉线。
    # 把持久配置钉死成 "adb" 后不再被重配，链路稳定。
    # 这台车（CS11 / DesaySV 平台）本身没有 CarPlay 功能，钉死没有副作用。
    CARPLAY_CONFIG = "carplay_carlife,adb"
    ADB_ONLY_CONFIG = "adb"

    def usb_binding(self):
        """读 USB 配置，判断是否存在被周期性重配导致 adb 掉线的风险。"""
        code, out = self.run_retry(
            ["shell", "getprop persist.vendor.usb.config; "
                       "getprop persist.sys.usb.config; "
                       "getprop sys.usb.config; getprop sys.usb.state"],
            timeout=30, retries=2,
        )
        lines = [l.strip() for l in (out or "").splitlines()]
        while len(lines) < 4:
            lines.append("")
        info = {
            "persist_vendor": lines[0],
            "persist_sys": lines[1],
            "sys_config": lines[2],
            "sys_state": lines[3],
            "risky": False,
            "reason": "",
        }
        persisted = f"{info['persist_vendor']} {info['persist_sys']}".lower()
        if "carplay" in persisted or "carlife" in persisted:
            info["risky"] = True
            info["reason"] = ("USB 功能集含 carplay_carlife：车载探测服务会周期性重配 USB，"
                              "每次重配都会拆掉 adbd 通道 → adb 掉线（USB 硬件仍在）")
        elif info["persist_vendor"] != self.ADB_ONLY_CONFIG:
            info["risky"] = True
            info["reason"] = f"USB 持久配置不是 adb（当前 {info['persist_vendor'] or '空'}），可能被其他服务改写"
        return info

    def fix_usb_binding(self):
        """把 USB 持久配置钉死为纯 adb，消除周期性重配导致的掉线。"""
        self.log("正在修复 USB 链路配置（钉死为 adb）…")
        self.run_retry(["shell", f"setprop persist.vendor.usb.config {self.ADB_ONLY_CONFIG}"],
                       timeout=30, retries=2)
        self.run_retry(["shell", f"setprop persist.sys.usb.config {self.ADB_ONLY_CONFIG}"],
                       timeout=30, retries=2)
        time.sleep(1)
        info = self.usb_binding()
        ok = (info["persist_vendor"] == self.ADB_ONLY_CONFIG
              and info["persist_sys"] == self.ADB_ONLY_CONFIG)
        if ok:
            self.log("✓ USB 配置已钉死为 adb，链路重配已消除，adb 不再周期性掉线")
        else:
            self.log(f"✗ 配置未生效：persist.vendor.usb.config={info['persist_vendor'] or '空'}")
        return ok, info

    def restore_usb_binding(self):
        """还原车机出厂 USB 配置 carplay_carlife,adb（排查其他问题时用）。"""
        self.log("正在还原车机出厂 USB 配置（carplay_carlife,adb）…")
        self.run_retry(["shell", f"setprop persist.vendor.usb.config {self.CARPLAY_CONFIG}"],
                       timeout=30, retries=2)
        self.run_retry(["shell", f"setprop persist.sys.usb.config {self.CARPLAY_CONFIG}"],
                       timeout=30, retries=2)
        time.sleep(1)
        info = self.usb_binding()
        ok = self.CARPLAY_CONFIG in info["persist_vendor"]
        if ok:
            self.log("✓ 已还原出厂配置；adb 可能重新开始周期性掉线")
        else:
            self.log(f"✗ 还原未生效：persist.vendor.usb.config={info['persist_vendor'] or '空'}")
        return ok, info

    def link_health(self):
        """采集掉线证据：系统运行时长、adbd 启动点、内核里 USB 重配次数。"""
        code, out = self.run_retry(
            ["shell", "cat /proc/uptime; getprop ro.boottime.adbd; "
                       "dmesg 2>/dev/null | grep -c 'USB_STATE=DISCONNECTED'; "
                       "dmesg 2>/dev/null | grep -c 'USB_STATE=CONFIGURED'"],
            timeout=40, retries=2,
        )
        lines = [l.strip() for l in (out or "").splitlines()]
        while len(lines) < 4:
            lines.append("")
        try:
            uptime = float(lines[0].split()[0])
        except Exception:
            uptime = 0.0
        try:
            adbd_boot = int(float(lines[1])) / 1e9      # ro.boottime.adbd 是纳秒
        except Exception:
            adbd_boot = 0.0
        try:
            disconnects = int(lines[2])
        except Exception:
            disconnects = -1
        try:
            configured = int(lines[3])
        except Exception:
            configured = -1
        return {
            "uptime": uptime,
            "adbd_boot": adbd_boot,
            "disconnects": disconnects,   # -1 = dmesg 读不到（普通 shell 受限）
            "configured": configured,
        }

    def screenshot(self):
        """截图并拉回本地 logs/，返回本地路径。"""
        if not self.serial:
            self.log("✗ 尚未选择设备，请先点「重新检测」")
            return ""
        remote = f"/data/local/tmp/shot_{int(time.time())}.png"
        self.log("正在截图…")
        self.run_retry(["shell", f"screencap -p {remote}"], timeout=60, retries=2)
        ts = time.strftime("%Y%m%d_%H%M%S")
        local = os.path.join(APP_DIR, "logs", f"car_shot_{ts}.png")
        if self.pull(remote, local):
            self.cleanup_remote(remote)
            return local
        return ""


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.logq: queue.Queue[str] = queue.Queue()
        self._log_history = []
        self.busy = False
        self.apk_path = tk.StringVar()
        self.adb_path = tk.StringVar(value=find_adb())
        self.pkg_name = ""
        self.launch_component = ""
        # 状态栏当前文字/颜色：主题热切换要重建界面，重建后靠这两项还原
        self._state_text, self._state_color = "检测中…", AMBER
        self.force_reinstall = tk.BooleanVar(value=True)
        self.aapt2 = find_aapt2()
        self.client = AdbClient(self.adb_path.get(), self.log, self.aapt2)

        self._build_ui()
        self.root.after(120, self._drain_log)
        # 设备选择可能弹选择框（Tk 组件必须主线程创建），不能再放子线程
        self.root.after(200, self._boot)
        # 主题热切换：窗口获得焦点时检查系统深浅色，变了就重建界面
        self.root.bind("<FocusIn>", self._on_focus_check_theme)

    # ---------- UI ----------
    def _build_ui(self):
        r = self.root
        r.title(APP_TITLE)
        r.configure(bg=BG)
        r.geometry("760x660")
        r.minsize(680, 540)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TProgressbar", thickness=8, troughcolor=PANEL2,
                        background=ACCENT, bordercolor=PANEL2,
                        lightcolor=ACCENT, darkcolor=ACCENT)

        # 顶部：标题 + 状态（扁平）
        top = tk.Frame(r, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text="领克车机 ADB 工具", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        self.lbl_state = tk.Label(top, text="● 检测中…", bg=BG, fg=AMBER,
                                  font=("Microsoft YaHei UI", 10, "bold"))
        self.lbl_state.pack(side="right")

        # 设备面板（内嵌）
        dev = flat_panel(r)
        dev.pack(fill="x", padx=16, pady=(4, 6), ipady=8)
        row = tk.Frame(dev, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(row, text="设备", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.lbl_dev = tk.Label(row, text="—", bg=PANEL, fg=FG,
                                font=("Microsoft YaHei UI", 10))
        self.lbl_dev.pack(side="left", padx=10)
        make_button(row, "重新检测", self.on_refresh).pack(side="right")
        self.btn_link = make_button(row, "链路诊断", self.on_link_diag)
        self.btn_link.pack(side="right", padx=(0, 8))

        row2 = tk.Frame(dev, bg=PANEL)
        row2.pack(fill="x", padx=12, pady=(4, 6))
        tk.Label(row2, text="adb", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Entry(row2, textvariable=self.adb_path, bg=PANEL2, fg=FG,
                 insertbackground=FG, relief="flat",
                 font=("Consolas", 9)).pack(side="left", fill="x", expand=True, padx=8)
        make_button(row2, "浏览", self.on_pick_adb).pack(side="right")

        # APK 面板（内嵌）
        apk = flat_panel(r)
        apk.pack(fill="x", padx=16, pady=6, ipady=8)
        row3 = tk.Frame(apk, bg=PANEL)
        row3.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(row3, text="APK", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Entry(row3, textvariable=self.apk_path, bg=PANEL2, fg=FG,
                 insertbackground=FG, relief="flat",
                 font=("Consolas", 9)).pack(side="left", fill="x", expand=True, padx=8)
        make_button(row3, "浏览…", self.on_pick_apk).pack(side="right")

        row4 = tk.Frame(apk, bg=PANEL)
        row4.pack(fill="x", padx=12, pady=(8, 4))
        self.btn_upload = make_button(row4, "① 上传并安装", self.on_upload_install, accent=True)
        self.btn_upload.pack(side="left")
        self.btn_launch = make_button(row4, "② 启动应用", self.on_launch)
        set_enabled(self.btn_launch, False)
        self.btn_launch.pack(side="left", padx=8)
        self.btn_logcat = make_button(row4, "③ 抓日志", self.on_logcat)
        self.btn_logcat.pack(side="right")
        self.btn_openlog = make_button(row4, "日志目录", self.on_openlog)
        self.btn_openlog.pack(side="right", padx=(0, 8))
        self.btn_apps = make_button(row4, "④ 应用列表", self.on_apps)
        self.btn_apps.pack(side="right", padx=(0, 8))

        # 命令终端单独一行：六个按钮挤在一行时 760 宽的窗口装不下，
        # Tk 会把按钮压窄到字都显示不全（"⑤ 命令终端" 变成 "命令终"）
        row4b = tk.Frame(apk, bg=PANEL)
        row4b.pack(fill="x", padx=12, pady=(0, 2))
        self.btn_shell = make_button(row4b, "⑤ 命令终端", self.on_shell)
        self.btn_shell.pack(side="left")
        tk.Label(row4b, text="手输 adb 命令 / 常用预设命令", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 8)).pack(side="left", padx=10)

        row5 = tk.Frame(apk, bg=PANEL)
        row5.pack(fill="x", padx=12, pady=(0, 4))
        tk.Checkbutton(
            row5, text="签名冲突时自动卸载旧版再装（重签名包常见）",
            variable=self.force_reinstall, bg=PANEL, fg=FG_DIM,
            selectcolor=PANEL2, activebackground=PANEL, activeforeground=FG,
            highlightthickness=0, font=("Microsoft YaHei UI", 9),
        ).pack(side="left")

        self.pb = ttk.Progressbar(apk, mode="indeterminate")
        self.pb.pack(fill="x", padx=12, pady=(2, 6))

        # 底栏：adb 路径 + 反馈 / 赞赏入口。
        # 必须先用 side="bottom" 占位，再放会 expand 的日志区：pack 是按顺序分配空间的，
        # 排在 expand 控件之后的 widget 在窗口不够高时会被压成 0 高度（按钮直接看不见）。
        foot = tk.Frame(r, bg=BG)
        foot.pack(side="bottom", fill="x", padx=16, pady=(0, 8))
        tk.Label(foot, text=f"adb: {self.adb_path.get()}", bg=BG, fg=FG_DIM,
                 font=("Consolas", 8), anchor="w").pack(side="left")
        self.btn_donate = make_button(foot, "赞赏", self.on_donate)
        self.btn_donate.pack(side="right")
        self.btn_feedback = make_button(foot, "反馈", self.on_feedback)
        self.btn_feedback.pack(side="right", padx=(0, 8))

        # 日志（终端屏：更深的底色 + 内嵌边）
        box = flat_panel(r)
        box.pack(fill="both", expand=True, padx=16, pady=(6, 4))
        tk.Label(box, text="日志", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", padx=12, pady=(8, 0))
        self.logbox = scrolledtext.ScrolledText(
            box, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat",
            font=("Consolas", 9), state="disabled", wrap="word", height=10,
        )
        self.logbox.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        for tag, color in (("ok", ACCENT), ("err", RED), ("warn", AMBER)):
            self.logbox.tag_config(tag, foreground=color)


    # ---------- 日志 ----------
    def log(self, msg: str):
        self._log_history.append(msg)
        if len(self._log_history) > 500:
            self._log_history = self._log_history[-500:]
        self.logq.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self.logq.get_nowait()
                self.logbox.configure(state="normal")
                tag = ""
                if msg.startswith("✓"):
                    tag = "ok"
                elif msg.startswith("✗"):
                    tag = "err"
                elif msg.startswith("⚠"):
                    tag = "warn"
                ts = time.strftime("%H:%M:%S")
                self.logbox.insert("end", f"[{ts}] {msg}\n", tag)
                self.logbox.see("end")
                self.logbox.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_log)

    def _set_state(self, text, color):
        # 先落盘再画：主题热切换重建界面后要用它还原状态栏（原先只 configure
        # 不保存，重建时会读到不存在的属性而崩溃）
        self._state_text, self._state_color = text, color
        try:
            self.lbl_state.configure(text=f"● {text}", fg=color)
        except tk.TclError:
            pass

    def _set_busy(self, busy: bool):
        self.busy = busy
        set_enabled(self.btn_upload, not busy)
        set_enabled(self.btn_logcat, not busy)
        set_enabled(self.btn_openlog, not busy)
        set_enabled(self.btn_apps, not busy)
        set_enabled(self.btn_shell, not busy)
        set_enabled(self.btn_link, not busy)
        # 启动按钮有前置条件：有入口才可用（卸载在应用列表窗口里）
        set_enabled(self.btn_launch, (not busy) and bool(self.launch_component))
        if busy:
            self.pb.start(12)
        else:
            self.pb.stop()

    # ---------- 设备选择与连接 ----------
    def _on_focus_check_theme(self, _event=None):
        if self.busy:
            return
        global IS_DARK
        dark = detect_dark_mode()
        if dark == IS_DARK:
            return
        set_theme_globals(dark)
        IS_DARK = dark
        state_text = getattr(self, "_state_text", "已连接")
        state_color = getattr(self, "_state_color", ACCENT)
        history = list(self._log_history)
        for w in self.root.winfo_children():
            w.destroy()
        self._build_ui()
        apply_window_icon(self.root)
        for msg in history:
            self.log(msg)
        self._set_busy(self.busy)
        self._set_state(state_text, state_color)

    def _select_device(self):
        """设备选择规则：唯一领克车机 → 直连；非车机或多设备 → 弹窗让用户选。

        探测放后台线程：每台设备要跑一次 getprop（宁可等 20s 也不能冻界面），
        只有「弹选择框」这一步必须回主线程做。
        """
        self.client.adb = self.adb_path.get()
        self._set_busy(True)
        self._set_state("检测中…", AMBER)
        threading.Thread(target=self._detect_worker, daemon=True).start()

    def _detect_worker(self):
        try:
            self._detect_worker_inner()
        except Exception as e:      # 任何意外都要解 busy，否则界面永久卡在"检测中"
            self.root.after(0, lambda: self._detect_failed(f"检测失败：{e}"))

    def _detect_worker_inner(self):
        client = self.client
        devices = client.list_devices()
        online = [s for s, st in devices if st == "device"]
        if not online:
            # 没有在线设备：后台修复 adb 链路后再看一次
            ok, info = client._health()
            if ok:
                online = [s for s, st in client.list_devices() if st == "device"]
            if not online:
                self.root.after(0, lambda: self._detect_failed(info))
                return

        infos = []
        for s in online:
            model, is_lynk = client.query_model(s)
            tag = "领克车机" if is_lynk else (
                "本机模拟器（非USB设备）" if s.startswith("emulator-") else "非领克设备")
            infos.append((s, model, is_lynk, tag))
        self.root.after(0, lambda: self._detect_done(infos))

    def _detect_failed(self, info):
        self._set_busy(False)
        self.lbl_dev.configure(text="—")
        self._set_state("未连接", RED)
        self.log(f"✗ {info}")

    def _detect_done(self, infos):
        lynk = [i for i in infos if i[2]]
        if len(infos) == 1 and lynk:
            self._connect(infos[0][0], infos[0][1])
            return
        if len(infos) == 1:
            self.log("⚠ 检测到的设备不是领克车机（可能是本机模拟器），请确认后选择")
        dlg = DevicePicker(self.root, infos)
        self.root.wait_window(dlg)
        if dlg.chosen:
            self._connect(dlg.chosen, dlg.chosen_model)
        else:
            self._set_busy(False)
            self.lbl_dev.configure(text="—")
            self._set_state("未选择设备", AMBER)
            self.log("⚠ 未选择设备")

    def _connect(self, serial, model):
        self.client.serial = serial
        self.client.model = model
        self.lbl_dev.configure(text=f"{model}  ({serial})")
        self._set_state("连接中…", AMBER)

        def work():
            dinfo = self.client.device_info()   # 又一次 adb 往返，照样放后台

            def done():
                self.lbl_dev.configure(text=f"{dinfo}  ({serial})")
                self._set_state("已连接", ACCENT)
                self.log(f"✓ 已连接：{dinfo}（序列号 {serial}，{model}）")
                self.log(f"adb: {self.adb_path.get()}")
                if self.aapt2:
                    self.log(f"aapt2: {self.aapt2}")
                else:
                    self.log("⚠ 未找到 aapt2，无法自动解析包名（启动按钮不可用，"
                             "卸载仍可在应用列表里按包名操作）")
                self._set_busy(False)
                # 连上就查一次 USB 链路配置：车机默认带 carplay_carlife，
                # CarPlay 探测会周期性重配 USB gadget 导致 adb 掉线
                self._auto_check_link()

            self.root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _auto_check_link(self):
        """连上就检查 USB 配置；发现会被周期性重配就直接自动修好，不打扰用户。"""
        def work():
            try:
                info = self.client.usb_binding()
            except Exception:
                return
            if not info["risky"]:
                self.root.after(0, lambda: self._link_report(info, fixed=False))
                return
            # 有隐患：直接自动修复（这台车没有 CarPlay，钉死 adb 无副作用）
            try:
                ok, info2 = self.client.fix_usb_binding()
            except Exception:
                ok, info2 = False, info
            self.root.after(0, lambda: self._link_report(info2, fixed=True, ok=ok, before=info))

        threading.Thread(target=work, daemon=True).start()

    def _link_report(self, info, fixed=False, ok=False, before=None):
        if self.busy:
            return
        if fixed:
            if ok:
                self.log("✓ USB 链路已自动修复：CarPlay/CarLife 不再抢占 USB，adb 掉线问题消除")
                self.log(f"  persist.vendor.usb.config: {before['persist_vendor'] or '空'} → adb")
            else:
                self.log("⚠ USB 链路自动修复未生效，点「链路诊断」查看详情")
        else:
            self.log("✓ USB 链路配置正常（纯 adb，不会被周期性重配）")

    def on_link_diag(self):
        if self.busy:
            return
        if not self.client.serial:
            messagebox.showwarning(APP_TITLE, "请先连接车机")
            return
        self._open_single("_win_link", LinkDiagWindow)

    def _boot(self):
        self.log("正在检测 adb 与车机…")
        self._select_device()

    def on_refresh(self):
        if self.busy:
            return
        self._set_state("检测中…", AMBER)
        self._select_device()

    def on_pick_adb(self):
        p = filedialog.askopenfilename(title="选择 adb.exe",
                                       filetypes=[("adb", "adb.exe"), ("所有文件", "*.*")])
        if p:
            self.adb_path.set(p)
            self.client.adb = p

    def on_pick_apk(self):
        p = filedialog.askopenfilename(title="选择 APK", filetypes=[("Android 安装包", "*.apk")])
        if not p:
            return
        self.apk_path.set(p)
        self.pkg_name = ""
        self.launch_component = ""
        set_enabled(self.btn_launch, False)
        if self.aapt2:
            threading.Thread(target=self._parse_apk, args=(p,), daemon=True).start()
        else:
            self.log(f"已选择：{os.path.basename(p)}（无 aapt2，安装后需手动启动）")

    def _parse_apk(self, path):
        try:
            p = subprocess.run([self.aapt2, "dump", "badging", path],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            out = p.stdout or ""
            m = re.search(r"package: name='([^']+)'", out)
            a = re.search(r"launchable-activity: name='([^']+)'", out)
            if m:
                self.pkg_name = m.group(1)
            if a and m:
                # badging 给的通常是全限定类名；am start 接受 pkg/全类名 或 pkg/.相对名
                self.launch_component = f"{self.pkg_name}/{a.group(1)}"
            self.log(f"包名：{self.pkg_name or '未知'}｜入口：{a.group(1) if a else '无'}")
        except Exception as e:
            self.log(f"⚠ 解析 APK 失败：{e}")

    def on_upload_install(self):
        if self.busy:
            return
        path = self.apk_path.get()
        if not path or not os.path.isfile(path):
            messagebox.showwarning(APP_TITLE, "请先选择一个 APK 文件")
            return
        self._set_busy(True)

        def progress(pct):
            self.root.after(0, lambda: self.pb.configure(value=pct))

        def work():
            try:
                if not self.client.serial:
                    self.log("✗ 尚未选择设备，请先点「重新检测」")
                    return
                self.root.after(0, lambda: self.pb.configure(
                    mode="determinate", maximum=100, value=0))
                if not self.client.push(path, progress=progress):
                    return   # push() 内部已记录失败原因、清理残留
                # 勾选「覆盖安装」才允许在签名冲突时自动卸旧版；不勾就是纯 -r 覆盖
                pkg = self.pkg_name if self.force_reinstall.get() else ""
                ok, _ = self.client.install(pkg)
                if ok:
                    self.log(f"提示：应用已安装{f'（{self.pkg_name}）' if self.pkg_name else ''}")
            finally:
                def restore():
                    self.pb.configure(mode="indeterminate", value=0)
                    self._set_busy(False)
                self.root.after(0, restore)

        threading.Thread(target=work, daemon=True).start()

    def on_apps(self):
        if self.busy:
            return
        AppListWindow(self)

    def on_shell(self):
        if self.busy:
            return
        self._open_single("_win_shell", ShellWindow)

    def on_logcat(self):
        if self.busy:
            return
        self._set_busy(True)

        def work():
            try:
                if not self.client.serial:
                    self.log("✗ 尚未选择设备，请先点「重新检测」")
                    return
                remote = self.client.logcat()
                ts = time.strftime("%Y%m%d_%H%M%S")
                # 保存到程序目录下的 logs/，不依赖任何特定盘符
                local = os.path.join(APP_DIR, "logs", f"car_logcat_{ts}.txt")
                if self.client.pull(remote, local):
                    self.client.cleanup_remote(remote)   # 拉成功才删设备端临时文件
            finally:
                self.root.after(0, lambda: self._set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    def on_openlog(self):
        path = os.path.join(APP_DIR, "logs")
        os.makedirs(path, exist_ok=True)
        subprocess.Popen(["explorer", path])

    def on_launch(self):
        if self.busy or not self.launch_component:
            return
        self._set_busy(True)

        def work():
            try:
                self.client.launch(self.launch_component)
            finally:
                self.root.after(0, lambda: self._set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    # ---------- 反馈 / 赞赏 ----------
    def _open_single(self, attr, factory):
        """同一窗口只留一个：已开着就提到最前，避免连点堆一堆窗口。"""
        w = getattr(self, attr, None)
        try:
            if w is not None and w.winfo_exists():
                w.deiconify()
                w.lift()
                w.focus_force()
                return
        except tk.TclError:
            pass
        setattr(self, attr, factory(self))

    def on_feedback(self):
        self._open_single("_win_feedback", FeedbackWindow)

    def on_donate(self):
        self._open_single("_win_donate", DonateWindow)


class DevicePicker(tk.Toplevel):
    """多设备/非车机设备时的选择弹窗。"""

    def __init__(self, root: tk.Tk, infos):
        super().__init__(root)
        self.infos = infos          # [(serial, model, is_lynk, tag)]
        self.chosen = ""
        self.chosen_model = ""
        self.title("选择目标设备")
        apply_window_icon(self)
        self.geometry("620x300")
        self.resizable(False, True)
        self.configure(bg=BG)
        self.transient(root)
        self.grab_set()

        tk.Label(self, text="检测到非领克车机或多台设备，请选择要操作的目标（取消则不连接）：",
                 bg=BG, fg=FG, font=("Microsoft YaHei UI", 11)).pack(anchor="w", padx=16, pady=(14, 8))
        self.listbox = tk.Listbox(self, bg=PANEL2, fg=FG, relief="flat",
                                  font=("Consolas", 11), selectbackground="#2E4A56",
                                  selectforeground=FG, highlightthickness=0)
        self.listbox.pack(fill="both", expand=True, padx=16)
        for serial, model, is_lynk, tag in infos:
            self.listbox.insert("end", f"{serial}    {model}    [{tag}]")
        if len(infos) == 1:
            self.listbox.selection_set(0)

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=16, pady=10)
        make_button(row, "确定", self._ok, accent=True).pack(side="right")
        make_button(row, "取消", self.destroy).pack(side="right", padx=8)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Double-1>", lambda _e: self._ok())

    def _ok(self):
        sel = self.listbox.curselection()
        if sel:
            serial, model, _, _ = self.infos[sel[0]]
            self.chosen, self.chosen_model = serial, model
        self.destroy()


class FeedbackWindow(tk.Toplevel):
    """反馈与联系：显示邮箱，支持一键复制与唤起邮件客户端。"""

    def __init__(self, app: App):
        super().__init__(app.root)
        self.app = app
        self.title("反馈与联系")
        apply_window_icon(self)
        self.configure(bg=BG)
        self.geometry("580x400")
        self.resizable(False, False)
        self.transient(app.root)

        box = tk.Frame(self, bg=BG)
        box.pack(fill="both", expand=True, padx=18, pady=(16, 10))

        tk.Label(box, text="反馈与联系", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        tk.Label(box, text="用着有问题、想提建议，或者装成功了想说一声，都欢迎发邮件。",
                 bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 9),
                 justify="left").pack(anchor="w", pady=(6, 12))

        mail = flat_panel(box)
        mail.pack(fill="x", ipady=10)
        tk.Label(mail, text="邮箱", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(12, 8))
        self.lbl_mail = tk.Label(mail, text=FEEDBACK_EMAIL, bg=PANEL, fg=ACCENT,
                                 font=("Consolas", 12, "bold"))
        self.lbl_mail.pack(side="left")
        make_button(mail, "复制", self.copy_email).pack(side="right", padx=12)

        tk.Label(box, text="反馈时附上这几项，定位会快很多：", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w", pady=(14, 4))
        for line in ("· 设备栏里的型号与序列号（主界面顶部）",
                     "· 点过哪几个按钮、完整报错文字",
                     "· 「日志目录」里对应的 car_logcat_*.txt"):
            tk.Label(box, text=line, bg=BG, fg=FG_DIM,
                     font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=1)

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=18, pady=(0, 12))
        make_button(row, "关闭", self.destroy).pack(side="right")
        make_button(row, "用邮件客户端发送", self.open_mail, accent=True).pack(side="right", padx=8)

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def copy_email(self):
        self.clipboard_clear()
        self.clipboard_append(FEEDBACK_EMAIL)
        self.lbl_mail.configure(text=f"{FEEDBACK_EMAIL}  已复制")

        def restore():
            if self._alive():
                self.lbl_mail.configure(text=FEEDBACK_EMAIL)

        self.after(1600, restore)

    def open_mail(self):
        from urllib.parse import quote
        url = f"mailto:{FEEDBACK_EMAIL}?subject={quote('领克车机 ADB 工具反馈')}"
        try:
            os.startfile(url)      # Windows：交给系统默认邮件客户端
        except Exception:
            self.clipboard_clear()
            self.clipboard_append(FEEDBACK_EMAIL)
            messagebox.showinfo(
                APP_TITLE,
                "没能唤起邮件客户端，邮箱已复制到剪贴板：\n" + FEEDBACK_EMAIL,
            )


class DonateWindow(tk.Toplevel):
    """赞赏窗口：并排展示微信 / 支付宝收款码。"""

    def __init__(self, app: App):
        super().__init__(app.root)
        self.app = app
        self.title("赞赏")
        apply_window_icon(self)
        self.configure(bg=BG)
        self.geometry("800x580")
        self.resizable(False, True)
        self.transient(app.root)
        self._imgs = []      # 必须留引用，否则 PhotoImage 会被回收成空白

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=18, pady=(14, 6))
        tk.Label(head, text="赞赏", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        tk.Label(head, text="完全自愿，不影响使用和更新", bg=BG, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=10)

        row = tk.Frame(self, bg=BG)
        row.pack(fill="both", expand=True, padx=18, pady=6)
        for stem, name in (("wechat", "微信"), ("alipay", "支付宝")):
            card = flat_panel(row)
            card.pack(side="left", fill="both", expand=True, padx=(0, 8))
            tk.Label(card, text=name, bg=PANEL, fg=FG,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(pady=(10, 4))
            p = asset_path("assets", "donate", stem + ".png")
            if p:
                img = tk.PhotoImage(file=p)
                self._imgs.append(img)
                tk.Label(card, image=img, bg=PANEL).pack(pady=6)
            else:
                tk.Label(card, text=f"未找到收款码图片\nassets\\donate\\{stem}.png",
                         bg=PANEL, fg=RED, font=("Microsoft YaHei UI", 9),
                         justify="center").pack(pady=60)
            tk.Label(card, text="扫码后转账即可", bg=PANEL, fg=FG_DIM,
                     font=("Microsoft YaHei UI", 9)).pack(pady=(0, 10))

        tk.Label(self, text="如果这个工具帮你少折腾了几次，可以请我喝杯水。",
                 bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 9)).pack(pady=(4, 8))
        make_button(self, "关闭", self.destroy).pack(anchor="e", padx=18, pady=(0, 14))


class AppListWindow(tk.Toplevel):
    """已安装应用列表：应用名 + 包名，支持输入包名卸载。"""

    def __init__(self, app: App):
        super().__init__(app.root)
        self.app = app
        self.all_rows = []
        self.loading = False
        self._closed = False
        self.pkg_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.include_system = tk.BooleanVar(value=False)

        self.title("应用列表")
        apply_window_icon(self)
        self.geometry("840x640")
        self.minsize(720, 520)
        self.configure(bg=BG)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._build()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        self.after(100, self.refresh)

    def _build(self):
        style = ttk.Style(self)
        style.configure(
            "App.Treeview",
            background=PANEL2,
            fieldbackground=PANEL2,
            foreground=FG,
            rowheight=27,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "App.Treeview.Heading",
            background=PANEL,
            foreground=FG_DIM,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "App.Treeview",
            background=[("selected", "#2E4A56")],
            foreground=[("selected", FG)],
        )

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(
            top, text="应用列表", bg=BG, fg=FG,
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(side="left")
        tk.Label(
            top, text="应用名从 APK 资源读取，首次会慢一些", bg=BG, fg=FG_DIM,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=12)

        tools = tk.Frame(self, bg=PANEL)
        tools.pack(fill="x", padx=16, pady=6, ipady=8)

        tk.Label(
            tools, text="搜索", bg=PANEL, fg=FG_DIM,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(12, 6))
        tk.Entry(
            tools, textvariable=self.search_var, bg=PANEL2, fg=FG,
            insertbackground=FG, relief="flat", font=("Consolas", 9), width=24,
        ).pack(side="left", fill="x", expand=True)

        self.btn_refresh = make_button(tools, "刷新列表", self.refresh)
        self.btn_refresh.pack(side="left", padx=8)
        tk.Checkbutton(
            tools, text="包含系统应用（较慢）", variable=self.include_system,
            command=self.refresh, bg=PANEL, fg=FG_DIM, selectcolor=PANEL2,
            activebackground=PANEL, activeforeground=FG,
            highlightthickness=0, font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(0, 12))

        tree_box = tk.Frame(self, bg=PANEL)
        tree_box.pack(fill="both", expand=True, padx=16, pady=6)
        self.tree = ttk.Treeview(
            tree_box,
            columns=("label", "pkg", "kind"),
            show="headings",
            style="App.Treeview",
        )
        self.tree.heading("label", text="应用名")
        self.tree.heading("pkg", text="包名")
        self.tree.heading("kind", text="类型")
        self.tree.column("label", width=240, anchor="w")
        self.tree.column("pkg", width=430, anchor="w")
        self.tree.column("kind", width=70, anchor="center")

        vsb = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(0, 0))
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double)

        bottom = tk.Frame(self, bg=PANEL)
        bottom.pack(fill="x", padx=16, pady=(6, 16), ipady=8)

        row = tk.Frame(bottom, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(
            row, text="包名", bg=PANEL, fg=FG_DIM,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(0, 6))
        tk.Entry(
            row, textvariable=self.pkg_var, bg=PANEL2, fg=FG,
            insertbackground=FG, relief="flat", font=("Consolas", 9),
        ).pack(side="left", fill="x", expand=True)

        self.btn_uninstall = make_button(
            row, "卸载此包名", self.uninstall, danger=True
        )
        self.btn_uninstall.pack(side="left", padx=8)
        make_button(row, "复制包名", self.copy_pkg).pack(side="left")
        # 必须走 _close：直接 destroy 不会置 _closed，加载中关闭会让进度回调
        # 一直往已销毁的控件上写字（一堆 TclError）
        make_button(row, "关闭", self._close).pack(side="left", padx=8)

        self.status = tk.Label(
            bottom, text="准备读取…", bg=PANEL, fg=FG_DIM,
            font=("Microsoft YaHei UI", 9), anchor="w",
        )
        self.status.pack(fill="x", padx=12, pady=(2, 4))

    def refresh(self):
        if self.loading or self._closed:
            return
        if self.app.busy:
            self.status.configure(text="主窗口有操作进行中，请稍后再试")
            return
        self.loading = True
        self.app._set_busy(True)   # 与主窗口互斥，避免并发共用 AdbClient
        set_enabled(self.btn_refresh, False)
        self.status.configure(text="正在读取应用列表…")
        for item in self.tree.get_children():
            self.tree.delete(item)

        include = self.include_system.get()
        threading.Thread(target=self._load_worker, args=(include,), daemon=True).start()

    def _load_worker(self, include_system: bool):
        rows = []
        error = None
        try:
            rows = self.app.client.list_apps(
                include_system=include_system,
                progress=self._progress,
            )
        except Exception as e:
            error = e
        if not self._closed:
            self.after(0, lambda: self._load_done(rows, error))

    def _progress(self, index: int, total: int, pkg: str):
        if self._closed:
            return

        def upd():
            if self._alive():      # 窗口可能已在读取过程中被关掉
                self.status.configure(text=f"正在读取 {index}/{total}：{pkg}")

        self.after(0, upd)

    def _load_done(self, rows, error):
        # 先释放主窗口互斥（即使窗口已关闭也要释放，否则主界面按钮永久禁用）
        if self.loading:
            self.loading = False
            self.app._set_busy(False)
        if not self._alive():
            return
        set_enabled(self.btn_refresh, True)
        if error is not None:
            self.status.configure(text=f"读取失败：{error}")
            return
        self.all_rows = rows
        self._apply_filter()
        self.status.configure(text=f"共 {len(rows)} 个应用")

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        for item in self.tree.get_children():
            self.tree.delete(item)
        shown = 0
        for label, pkg, kind in self.all_rows:
            if query and query not in label.lower() and query not in pkg.lower():
                continue
            self.tree.insert("", "end", values=(label, pkg, kind))
            shown += 1
        if self.all_rows and not self.loading:
            self.status.configure(
                text=f"显示 {shown} / {len(self.all_rows)} 个应用"
            )

    def _selected_pkg(self) -> str:
        selection = self.tree.selection()
        if not selection:
            return ""
        values = self.tree.item(selection[0], "values")
        return values[1] if len(values) > 1 else ""

    def _on_select(self, _event=None):
        pkg = self._selected_pkg()
        if pkg:
            self.pkg_var.set(pkg)

    def _on_double(self, _event=None):
        self._on_select()

    def copy_pkg(self):
        pkg = self.pkg_var.get().strip() or self._selected_pkg()
        if not pkg:
            return
        self.clipboard_clear()
        self.clipboard_append(pkg)
        self.status.configure(text=f"已复制：{pkg}")

    def uninstall(self):
        pkg = self.pkg_var.get().strip() or self._selected_pkg()
        if not pkg:
            messagebox.showwarning(APP_TITLE, "请先选择应用，或输入包名")
            return
        if self.app.busy:
            self.status.configure(text="主窗口有操作进行中，请稍后再试")
            return
        target = f"{self.app.client.serial}（{self.app.client.model or '未知型号'}）"
        if not messagebox.askyesno(APP_TITLE, f"确认卸载 {pkg}？\n\n目标设备：{target}"):
            return
        self.app._set_busy(True)   # 与主窗口互斥
        set_enabled(self.btn_uninstall, False)
        self.status.configure(text=f"正在卸载 {pkg}…")
        threading.Thread(
            target=self._uninstall_worker, args=(pkg,), daemon=True
        ).start()

    def _uninstall_worker(self, pkg: str):
        ok = self.app.client.uninstall(pkg)
        if not self._closed:
            self.after(0, lambda: self._uninstall_done(pkg, ok))

    def _uninstall_done(self, pkg: str, ok: bool):
        self.app._set_busy(False)   # 无论窗口是否还在都要释放主窗口互斥
        if not self._alive():
            return
        set_enabled(self.btn_uninstall, True)
        if ok:
            self.app.client.label_cache.pop(pkg, None)
            self.status.configure(text=f"已卸载 {pkg}")
            self.refresh()
        else:
            self.status.configure(text=f"卸载失败：{pkg}（详见主日志）")

    def _alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _close(self):
        self._closed = True
        if self.loading:
            self.loading = False
            self.app._set_busy(False)
        self.destroy()


class LinkDiagWindow(tk.Toplevel):
    """链路诊断：查 USB gadget 配置，一键修复 CarPlay 抢通道导致的 adb 掉线。"""

    def __init__(self, app: App):
        super().__init__(app.root)
        self.app = app
        self._closed = False
        self.running = False

        self.title("链路诊断")
        apply_window_icon(self)
        self.geometry("820x600")
        self.minsize(720, 500)
        self.configure(bg=BG)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._build()
        self.refresh()

    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text="链路诊断", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        self.lbl_state = tk.Label(top, text="检查中…", bg=BG, fg=AMBER,
                                  font=("Microsoft YaHei UI", 9))
        self.lbl_state.pack(side="right")

        # 结论区
        self.verdict = flat_panel(self)
        self.verdict.pack(fill="x", padx=16, pady=4, ipady=6)
        self.lbl_verdict = tk.Label(
            self.verdict, text="正在读取 USB 配置…", bg=PANEL, fg=FG,
            font=("Microsoft YaHei UI", 11, "bold"), anchor="w", justify="left",
            wraplength=740,
        )
        self.lbl_verdict.pack(fill="x", padx=12, pady=(8, 2))
        self.lbl_reason = tk.Label(
            self.verdict, text="", bg=PANEL, fg=FG_DIM,
            font=("Microsoft YaHei UI", 9), anchor="w", justify="left",
            wraplength=740,
        )
        self.lbl_reason.pack(fill="x", padx=12, pady=(0, 8))

        # 明细区
        box = flat_panel(self)
        box.pack(fill="both", expand=True, padx=16, pady=4)
        tk.Label(box, text="明细", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(
            fill="x", padx=12, pady=(8, 0))
        self.detail = scrolledtext.ScrolledText(
            box, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat",
            font=("Consolas", 9), state="disabled", wrap="word", height=12,
        )
        self.detail.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        for tag, color in (("ok", ACCENT), ("err", RED), ("warn", AMBER), ("dim", FG_DIM)):
            self.detail.tag_config(tag, foreground=color)

        # 按钮区
        foot = tk.Frame(self, bg=BG)
        foot.pack(side="bottom", fill="x", padx=16, pady=(4, 10))
        self.btn_fix = make_button(foot, "一键修复（钉死为 adb）", self.do_fix, accent=True)
        self.btn_fix.pack(side="left")
        self.btn_restore = make_button(foot, "还原出厂配置", self.do_restore)
        self.btn_restore.pack(side="left", padx=8)
        self.btn_refresh = make_button(foot, "重新检查", self.refresh)
        self.btn_refresh.pack(side="left", padx=8)
        make_button(foot, "关闭", self._close).pack(side="right")

        tk.Label(
            self,
            text="原理：车机 USB 功能集默认含 carplay_carlife，车载探测服务会周期性重配 USB gadget，"
                 "每次重配都会拆掉 adbd 通道 → adb 掉线（USB 硬件仍在）。钉死为 adb 后不再被重配。"
                 "本车没有 CarPlay 功能，钉死无副作用；工具在连上设备时会自动执行。",
            bg=BG, fg=FG_DIM, font=("Microsoft YaHei UI", 8),
            wraplength=780, justify="left", anchor="w",
        ).pack(side="bottom", fill="x", padx=16, pady=(0, 4))

    # ---------- 状态 ----------
    def _alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _append(self, text: str, tag: str = ""):
        if not self._alive():
            return
        self.detail.configure(state="normal")
        self.detail.insert("end", text if text.endswith("\n") else text + "\n", tag)
        self.detail.see("end")
        self.detail.configure(state="disabled")

    def _clear(self):
        if not self._alive():
            return
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.configure(state="disabled")

    # ---------- 检查 ----------
    def refresh(self):
        if self.running:
            return
        if self.app.busy:
            self.lbl_state.configure(text="主窗口有操作进行中")
            return
        self.running = True
        self.lbl_state.configure(text="检查中…")
        set_enabled(self.btn_refresh, False)

        def work():
            try:
                info = self.app.client.usb_binding()
                health = self.app.client.link_health()
            except Exception as e:
                info, health = None, {"error": str(e)}
            if self._alive():
                self.after(0, lambda: self._done(info, health))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, info, health):
        self.running = False
        if not self._alive():
            return
        set_enabled(self.btn_refresh, True)
        self._clear()

        if info is None:
            self.lbl_state.configure(text="检查失败")
            self.lbl_verdict.configure(text="✗ 读取失败", fg=RED)
            self.lbl_reason.configure(text=str(health.get("error", "")))
            return

        if info["risky"]:
            self.lbl_verdict.configure(text="⚠ 存在 adb 掉线隐患", fg=AMBER)
            self.lbl_reason.configure(text=info["reason"])
            self.lbl_state.configure(text="需要修复")
        else:
            self.lbl_verdict.configure(text="✓ 链路配置正常", fg=ACCENT)
            self.lbl_reason.configure(text="USB 功能集为纯 adb，不会被 CarPlay 探测重配")
            self.lbl_state.configure(text="正常")

        self._append("—— USB 配置 ——", "dim")
        self._append(f"persist.vendor.usb.config = {info['persist_vendor'] or '(空)'}",
                     "err" if "carplay" in info["persist_vendor"].lower() else "ok")
        self._append(f"persist.sys.usb.config    = {info['persist_sys'] or '(空)'}",
                     "err" if "carplay" in info["persist_sys"].lower() else "ok")
        self._append(f"sys.usb.config            = {info['sys_config'] or '(空)'}")
        self._append(f"sys.usb.state             = {info['sys_state'] or '(空)'}")

        self._append("")
        self._append("—— 运行状态 ——", "dim")
        if health.get("uptime"):
            self._append(f"车机运行时长   = {health['uptime'] / 60:.1f} 分钟")
        if health.get("adbd_boot"):
            self._append(f"adbd 启动于     = 开机后 {health['adbd_boot']:.1f} 秒"
                         "（数值不变说明 adbd 没重启过）")
        if health.get("disconnects") is not None and health["disconnects"] >= 0:
            self._append(f"USB 断开计数   = {health['disconnects']} 次（dmesg）", 
                         "warn" if health["disconnects"] > 3 else "")
            self._append(f"USB 配置完成数 = {health['configured']} 次（dmesg）")
        else:
            self._append("USB 断开计数   = 读不到（普通 shell 无权读 dmesg）", "dim")

    # ---------- 修复 ----------
    def do_fix(self):
        # 本车没有 CarPlay，钉死为 adb 无副作用，不再二次确认
        if self.running or self.app.busy:
            return
        self._run_fix()

    def do_restore(self):
        if self.running or self.app.busy:
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "还原车机出厂 USB 配置（carplay_carlife,adb）？\n\n"
            "还原后 adb 可能重新开始周期性掉线。",
        ):
            return
        self._run_fix(restore=True)

    def _run_fix(self, restore=False):
        self.running = True
        self.app._set_busy(True)
        set_enabled(self.btn_fix, False)
        set_enabled(self.btn_restore, False)
        self.lbl_state.configure(text="正在恢复…" if restore else "正在修复…")

        def work():
            try:
                if restore:
                    ok, info = self.app.client.restore_usb_binding()
                else:
                    ok, info = self.app.client.fix_usb_binding()
            except Exception as e:
                ok, info = False, {"error": str(e)}

            def done():
                self.running = False
                self.app._set_busy(False)
                if not self._alive():
                    return
                set_enabled(self.btn_fix, True)
                set_enabled(self.btn_restore, True)
                self.refresh()

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def _close(self):
        self._closed = True
        self.destroy()


class ShellWindow(tk.Toplevel):
    """命令终端：手输 adb 命令 + 一排预设命令，输出只在本窗口内滚动。"""

    def __init__(self, app: App):
        super().__init__(app.root)
        self.app = app
        self.running = False
        self._closed = False
        self._owns_busy = False
        self.mode_var = tk.StringVar(value="shell")
        self.cmd_var = tk.StringVar()
        self._history = []          # 本次会话输入过的命令，↑/↓ 翻
        self._hist_pos = -1

        self.title("ADB 命令终端")
        apply_window_icon(self)
        self.geometry("900x680")
        self.minsize(760, 540)
        self.configure(bg=BG)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._build()
        self._append_info(self._target_text())
        self._append_info("模式 shell = 车机内执行（自动走 adb shell）；模式 adb = 本机 adb 子命令")
        self._append_info("提示：shell 模式里 pm install 会自动改写成 ins''tall，绕过车机 adbd 过滤")

    # ---------- UI ----------
    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text="命令终端", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        self.lbl_target = tk.Label(top, text=self._target_short(), bg=BG, fg=FG_DIM,
                                   font=("Microsoft YaHei UI", 9))
        self.lbl_target.pack(side="right")

        # 预设命令区：按钮自动换行，宽度按窗口宽度算列数
        preset = flat_panel(self)
        preset.pack(fill="x", padx=16, pady=4, ipady=6)
        tk.Label(preset, text="预设命令", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(
            fill="x", padx=12, pady=(6, 2))
        self.preset_box = tk.Frame(preset, bg=PANEL)
        self.preset_box.pack(fill="x", padx=8, pady=(0, 6))
        self._preset_buttons = []
        self._preset_cols = 0
        self._reflow_presets(5)
        self.bind("<Configure>", self._on_resize)

        # 输入行
        entry_box = flat_panel(self)
        entry_box.pack(fill="x", padx=16, pady=4, ipady=8)
        row = tk.Frame(entry_box, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(row, text="模式", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.cb_mode = ttk.Combobox(row, textvariable=self.mode_var, state="readonly",
                                    values=("shell", "adb"), width=7,
                                    font=("Consolas", 9))
        self.cb_mode.pack(side="left", padx=8)
        self.entry = tk.Entry(row, textvariable=self.cmd_var, bg=PANEL2, fg=FG,
                              insertbackground=FG, relief="flat", font=("Consolas", 10))
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda _e: self.on_run())
        self.entry.bind("<Up>", self._hist_up)
        self.entry.bind("<Down>", self._hist_down)
        self.cb_mode.bind("<<ComboboxSelected>>", lambda _e: self.entry.focus_set())

        self.btn_run = make_button(row, "执行", self.on_run, accent=True)
        self.btn_run.pack(side="left")
        self.btn_clear = make_button(row, "清屏", self.clear)
        self.btn_clear.pack(side="left", padx=8)

        row2 = tk.Frame(entry_box, bg=PANEL)
        row2.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(row2, text="例：shell 模式  ls -l /sdcard   ｜   adb 模式  forward tcp:8080 tcp:8080",
                 bg=PANEL, fg=FG_DIM, font=("Microsoft YaHei UI", 8), anchor="w").pack(
            side="left")

        # 输出区
        out = flat_panel(self)
        out.pack(fill="both", expand=True, padx=16, pady=(4, 4))
        head = tk.Frame(out, bg=PANEL)
        head.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(head, text="输出", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(side="left")
        self.lbl_state = tk.Label(head, text="就绪", bg=PANEL, fg=FG_DIM,
                                  font=("Microsoft YaHei UI", 9))
        self.lbl_state.pack(side="right")
        self.outbox = scrolledtext.ScrolledText(
            out, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat",
            font=("Consolas", 9), state="disabled", wrap="none", height=16,
        )
        self.outbox.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        for tag, color in (("ok", ACCENT), ("err", RED), ("warn", AMBER),
                           ("cmd", HOVER_ACCENT), ("info", FG_DIM)):
            self.outbox.tag_config(tag, foreground=color)

        # 底栏
        foot = tk.Frame(self, bg=BG)
        foot.pack(side="bottom", fill="x", padx=16, pady=(0, 8))
        make_button(foot, "复制输出", self.copy_output).pack(side="right")
        make_button(foot, "关闭", self._close).pack(side="right", padx=(0, 8))
        self.entry.focus_set()

    def _target_short(self) -> str:
        c = self.app.client
        if not c.serial:
            return "未连接设备"
        return f"{c.model or '未知型号'}  ({c.serial})"

    def _target_text(self) -> str:
        return f"目标设备：{self._target_short()}"

    def _reflow_presets(self, cols: int):
        if cols == self._preset_cols:
            return
        self._preset_cols = cols
        for b in self._preset_buttons:
            b.destroy()
        self._preset_buttons = []
        for i, (label, mode, cmd) in enumerate(ADB_PRESETS):
            b = make_button(self.preset_box, label,
                            lambda m=mode, c=cmd, l=label: self.on_preset(m, c, l))
            b.grid(row=i // cols, column=i % cols, padx=3, pady=3, sticky="ew")
            self._preset_buttons.append(b)
        for c in range(cols):
            self.preset_box.grid_columnconfigure(c, weight=1)

    def _on_resize(self, event):
        if event.widget is not self:
            return
        # 每个按钮大约占 110px，最少 3 列
        self._reflow_presets(max(3, min(7, event.width // 115)))

    # ---------- 输出 ----------
    def _alive(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _append(self, text: str, tag: str = ""):
        if not self._alive():
            return
        self.outbox.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        if tag == "cmd":
            self.outbox.insert("end", f"\n[{ts}] {text}\n", tag)
        elif tag == "info":
            self.outbox.insert("end", f"[{ts}] {text}\n", tag)
        else:
            self.outbox.insert("end", text if text.endswith("\n") else text + "\n", tag)
        self.outbox.see("end")
        self.outbox.configure(state="disabled")

    def _append_info(self, text: str):
        self._append(text, "info")

    def clear(self):
        if not self._alive():
            return
        self.outbox.configure(state="normal")
        self.outbox.delete("1.0", "end")
        self.outbox.configure(state="disabled")

    def copy_output(self):
        if not self._alive():
            return
        text = self.outbox.get("1.0", "end").strip()
        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_state.configure(text=f"已复制 {len(text)} 字符")

    # ---------- 历史 ----------
    def _hist_up(self, _event=None):
        if not self._history:
            return "break"
        self._hist_pos = max(0, self._hist_pos - 1) if self._hist_pos >= 0 else len(self._history) - 1
        self.cmd_var.set(self._history[self._hist_pos])
        self.entry.icursor("end")
        return "break"

    def _hist_down(self, _event=None):
        if not self._history:
            return "break"
        self._hist_pos += 1
        if self._hist_pos >= len(self._history):
            self._hist_pos = -1
            self.cmd_var.set("")
        else:
            self.cmd_var.set(self._history[self._hist_pos])
        self.entry.icursor("end")
        return "break"

    # ---------- 执行 ----------
    def on_preset(self, mode: str, cmd: str, label: str):
        if self.running:
            return
        if getattr(self.app, "busy", False):
            self._append("⚠ 主窗口有操作进行中（上传/安装/抓日志），等它结束再执行命令", "warn")
            return
        if mode == "shot":
            self._run_shot()
            return
        if mode:
            self.mode_var.set(mode)
        self.cmd_var.set(cmd)
        self.on_run()

    def on_run(self):
        if self.running:
            self.lbl_state.configure(text="上一条命令还在执行，请稍候")
            return
        if getattr(self.app, "busy", False):
            self._append("⚠ 主窗口有操作进行中（上传/安装/抓日志），等它结束再执行命令", "warn")
            return
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        mode = self.mode_var.get()
        # 用户在输入框里写了 "adb shell ..." 前缀时自动纠正模式，避免重复拼 shell
        if cmd.startswith("adb "):
            rest = cmd[4:].strip()
            if rest == "shell":
                self.mode_var.set("shell")
                self._append("⚠ 请输入 shell 后面的部分，例如 ls -l /sdcard", "warn")
                self.entry.focus_set()
                return
            if rest.startswith("shell "):
                # 去掉 shell 关键字，剩下才是要交给设备端的命令
                mode, cmd = "shell", rest[len("shell "):].strip()
            else:
                mode, cmd = "adb", rest
            self.mode_var.set(mode)
            self.cmd_var.set(cmd)

        if not self.app.client.serial:
            self._append("✗ 尚未选择设备，请回到主窗口点「重新检测」", "err")
            return

        self._history.append(cmd)
        if len(self._history) > 200:
            self._history = self._history[-200:]
        self._hist_pos = -1
        self._append(f"[{mode}] {cmd}", "cmd")
        self._set_running(True)

        def work():
            try:
                if mode == "shell":
                    code, out = self.app.client.shell_cmd(cmd)
                else:
                    code, out = self.app.client.adb_cmd(cmd)
            except Exception as e:
                code, out = -1, f"执行异常：{e}"
            self.after(0, lambda: self._done(code, out))

        threading.Thread(target=work, daemon=True).start()

    def _run_shot(self):
        self._set_running(True)
        self._append("截图 → 拉回本地 logs/ …", "cmd")

        def work():
            try:
                local = self.app.client.screenshot()
                code, out = (0, local) if local else (-1, "截图失败（详见主日志）")
            except Exception as e:
                code, out = -1, f"执行异常：{e}"
            self.after(0, lambda: self._done(code, out, is_shot=True))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, code, out, is_shot=False):
        if not self._alive():
            return
        self._set_running(False)
        if is_shot:
            if code == 0 and out:
                self._append(f"✓ 已保存：{out}", "ok")
            else:
                self._append(f"✗ {out}", "err")
            self.app.log(f"终端截图：{out}")
            return
        body = (out or "").rstrip()
        if body:
            tag = "" if code == 0 else "err"
            self._append(body, tag)
        else:
            self._append("（无输出）", "info")
        if code == 0:
            self.lbl_state.configure(text="完成")
        else:
            self.lbl_state.configure(text=f"退出码 {code}")
            if "车机未连接" in (out or "") or "尚未选择设备" in (out or ""):
                self._append("⚠ 链路可能已断开，回主窗口点「重新检测」", "warn")
        self.entry.focus_set()

    def _set_running(self, running: bool):
        self.running = running
        set_enabled(self.btn_run, not running)
        for b in self._preset_buttons:
            set_enabled(b, not running)
        if running:
            self.lbl_state.configure(text="执行中…")
            # 与主窗口互斥：终端和上传/安装共用同一个 AdbClient 与同一条 USB 通道，
            # 并发会让 push 进度和命令输出互相穿插甚至断链
            self.app._set_busy(True)
            self._owns_busy = True
        else:
            self.lbl_state.configure(text="就绪")
            self._release_busy()

    def _release_busy(self):
        if getattr(self, "_owns_busy", False):
            self._owns_busy = False
            self.app._set_busy(False)

    def _close(self):
        self._closed = True
        # 命令还在跑就关窗：必须把主窗口的互斥还回去，否则主界面按钮永久禁用
        self._release_busy()
        self.destroy()


def main():
    if "--selftest" in sys.argv:
        print("adb:", find_adb())
        print("aapt2:", find_aapt2() or "未找到")
        return
    enable_dpi_awareness()
    root = tk.Tk()
    apply_window_icon(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
