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
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

APP_TITLE = "领克车机 ADB 工具"
REMOTE_APK = "/data/local/tmp/upload.apk"

# 深空仪表同款配色
BG = "#16181D"
PANEL = "#1F232B"
PANEL2 = "#262B34"
FG = "#E8EDF2"
FG_DIM = "#8A97A5"
ACCENT = "#00E8C6"
RED = "#FF5A5A"
AMBER = "#FFB020"


def app_dir() -> str:
    """源码运行时是 .py 所在目录；PyInstaller 打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = app_dir()

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
    """从 SDK build-tools 里找最新的 aapt2，用来解析包名。"""
    local = os.path.join(APP_DIR, "tools", "aapt2", "aapt2.exe")
    if os.path.isfile(local):
        return local

    sdk_roots = [
        os.path.expandvars(r"%ANDROID_HOME%"),
        os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk"),
        r"D:\Android\Sdk",
        r"C:\Android\Sdk",
    ]
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


class AdbClient:
    """带自动重连的 adb 封装。所有方法阻塞，必须放后台线程跑。"""

    def __init__(self, adb_path: str, log):
        self.adb = adb_path
        self.log = log
        self.serial = None
        self.pushed_apk = None   # 最近一次成功上传到设备的本地 APK 绝对路径

    # ---------- 低层 ----------
    def _run(self, args, timeout=60):
        cmd = [self.adb] + args
        if self.serial:
            cmd[1:1] = ["-s", self.serial]
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            return -1, "命令超时"
        except FileNotFoundError:
            return -1, f"找不到 adb：{self.adb}"
        except Exception as e:
            return -1, str(e)

    @staticmethod
    def _is_link_error(out: str) -> bool:
        return ("error: closed" in out or "device offline" in out
                or "no devices" in out or "device not found" in out
                or "closed" in out and "error" in out)

    def _health(self):
        """重启 adb server 并等待设备上线。返回 (ok, 信息)。"""
        self._run(["kill-server"], timeout=15)
        time.sleep(1)
        self._run(["start-server"], timeout=20)
        seen = {}
        for _ in range(12):
            code, out = self._run(["devices"], timeout=15)
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 2:
                    continue
                if parts[1] == "device":
                    self.serial = parts[0]
                    return True, parts[0]
                seen[parts[0]] = parts[1]
            time.sleep(2)
        if "unauthorized" in seen.values():
            return False, "设备未授权：看车机屏幕点「允许 USB 调试」，勾选「一律允许」"
        if "offline" in seen.values():
            return False, "设备 offline：拔插 USB 或重启 adb（本工具已重试过），换一个车机 USB 口"
        self.serial = None
        return False, "未检测到设备（检查 USB 线与开发者选项里的 USB 调试）"

    # ---------- 对外 ----------
    def ensure(self):
        ok, info = self._health()
        return ok, info

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

    def push(self, local_apk):
        size = os.path.getsize(local_apk)
        self.pushed_apk = None
        self.log(f"上传 {os.path.basename(local_apk)}（{size / 1048576:.1f} MB）→ {REMOTE_APK}")
        code, out = self.run_retry(
            ["push", local_apk, REMOTE_APK], timeout=600, retries=3
        )
        tail = out.strip().splitlines()[-1] if out.strip() else "无输出"
        if code != 0 or "pushed" not in out.lower():
            self.log(f"✗ 上传失败：{tail}")
            return False
        # 设备端核对大小，防止半截文件被当成装好了
        _, sz_out = self.run_retry(
            ["shell", f"stat -c %s {REMOTE_APK}"], timeout=30, retries=2
        )
        remote_size = None
        for line in sz_out.splitlines():
            if line.strip().isdigit():
                remote_size = int(line.strip())
        if remote_size is not None and remote_size != size:
            self.log(f"✗ 上传不完整：设备端 {remote_size} 字节 / 本地 {size} 字节，请重传")
            return False
        self.pushed_apk = os.path.abspath(local_apk)
        self.log(f"✓ 上传完成（{tail}）")
        return True

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
        if not quiet:
            self.log(f"卸载 {pkg} …")
        code, out = self.run_retry(
            ["shell", "pm unin''stall " + pkg], timeout=120, retries=2
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
        cmd = f"logcat -d -t {lines} > /data/local/tmp/lc.txt"
        self.run_retry(["shell", cmd], timeout=120, retries=2)
        code, out = self.run_retry(
            ["shell", "wc -l /data/local/tmp/lc.txt"], timeout=30, retries=2
        )
        self.log(f"设备端日志行数：{out.strip()}")
        return "/data/local/tmp/lc.txt"

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


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.logq: queue.Queue[str] = queue.Queue()
        self.busy = False
        self.apk_path = tk.StringVar()
        self.adb_path = tk.StringVar(value=find_adb())
        self.pkg_name = ""
        self.launch_component = ""
        self.pushed_apk = None          # 已成功上传到设备的本地路径（防止装错旧包）
        self.force_reinstall = tk.BooleanVar(value=True)
        self.aapt2 = find_aapt2()
        self.client = AdbClient(self.adb_path.get(), self.log)

        self._build_ui()
        self.root.after(120, self._drain_log)
        threading.Thread(target=self._boot, daemon=True).start()

    # ---------- UI ----------
    def _build_ui(self):
        r = self.root
        r.title(APP_TITLE)
        r.configure(bg=BG)
        r.geometry("760x600")
        r.minsize(680, 520)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 6))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(10, 6))
        style.configure("TProgressbar", thickness=6)

        # 顶栏
        top = tk.Frame(r, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text="领克车机 ADB 工具", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        self.lbl_state = tk.Label(top, text="● 检测中…", bg=BG, fg=AMBER,
                                  font=("Microsoft YaHei UI", 10))
        self.lbl_state.pack(side="right")

        # 设备面板
        dev = tk.Frame(r, bg=PANEL, highlightthickness=0)
        dev.pack(fill="x", padx=16, pady=6, ipady=8)
        row = tk.Frame(dev, bg=PANEL)
        row.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(row, text="设备", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.lbl_dev = tk.Label(row, text="—", bg=PANEL, fg=FG,
                                font=("Microsoft YaHei UI", 10))
        self.lbl_dev.pack(side="left", padx=10)
        ttk.Button(row, text="重新检测", command=self.on_refresh).pack(side="right")

        row2 = tk.Frame(dev, bg=PANEL)
        row2.pack(fill="x", padx=12, pady=(4, 6))
        tk.Label(row2, text="adb", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Entry(row2, textvariable=self.adb_path, bg=PANEL2, fg=FG,
                 insertbackground=FG, relief="flat",
                 font=("Consolas", 9)).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row2, text="浏览", command=self.on_pick_adb).pack(side="right")

        # APK 面板
        apk = tk.Frame(r, bg=PANEL)
        apk.pack(fill="x", padx=16, pady=6, ipady=8)
        row3 = tk.Frame(apk, bg=PANEL)
        row3.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(row3, text="APK", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Entry(row3, textvariable=self.apk_path, bg=PANEL2, fg=FG,
                 insertbackground=FG, relief="flat",
                 font=("Consolas", 9)).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row3, text="浏览…", command=self.on_pick_apk).pack(side="right")

        row4 = tk.Frame(apk, bg=PANEL)
        row4.pack(fill="x", padx=12, pady=(8, 4))
        self.btn_upload = ttk.Button(row4, text="① 上传到车机", command=self.on_upload)
        self.btn_upload.pack(side="left")
        self.btn_install = ttk.Button(row4, text="② 安装", style="Accent.TButton",
                                      command=self.on_install)
        self.btn_install.pack(side="left", padx=8)
        self.btn_launch = ttk.Button(row4, text="③ 启动应用", command=self.on_launch, state="disabled")
        self.btn_launch.pack(side="left")
        self.btn_uninstall = ttk.Button(row4, text="卸载", command=self.on_uninstall, state="disabled")
        self.btn_uninstall.pack(side="left", padx=8)
        self.btn_logcat = ttk.Button(row4, text="④ 抓日志", command=self.on_logcat)
        self.btn_logcat.pack(side="right")

        row5 = tk.Frame(apk, bg=PANEL)
        row5.pack(fill="x", padx=12, pady=(0, 4))
        tk.Checkbutton(
            row5, text="覆盖安装（签名不同则先卸载旧版再装）",
            variable=self.force_reinstall, bg=PANEL, fg=FG_DIM,
            selectcolor=PANEL2, activebackground=PANEL, activeforeground=FG,
            highlightthickness=0, font=("Microsoft YaHei UI", 9),
        ).pack(side="left")

        self.pb = ttk.Progressbar(apk, mode="indeterminate")
        self.pb.pack(fill="x", padx=12, pady=(2, 6))

        # 日志
        box = tk.Frame(r, bg=PANEL)
        box.pack(fill="both", expand=True, padx=16, pady=(6, 4))
        tk.Label(box, text="日志", bg=PANEL, fg=FG_DIM,
                 font=("Microsoft YaHei UI", 9), anchor="w").pack(fill="x", padx=12, pady=(8, 0))
        self.logbox = scrolledtext.ScrolledText(
            box, bg=PANEL2, fg="#C9D4DF", insertbackground=FG, relief="flat",
            font=("Consolas", 9), state="disabled", wrap="word",
        )
        self.logbox.pack(fill="both", expand=True, padx=12, pady=(2, 12))
        for tag, color in (("ok", ACCENT), ("err", RED), ("warn", AMBER)):
            self.logbox.tag_config(tag, foreground=color)

        # 底栏
        tk.Label(r, text=f"adb: {self.adb_path.get()}", bg=BG, fg=FG_DIM,
                 font=("Consolas", 8), anchor="w").pack(fill="x", padx=16, pady=(0, 8))

    # ---------- 日志 ----------
    def log(self, msg: str):
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
        self.lbl_state.configure(text=f"● {text}", fg=color)

    def _set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_upload, self.btn_install):
            b.configure(state=state)
        if busy:
            self.pb.start(12)
        else:
            self.pb.stop()

    # ---------- 后台任务 ----------
    def _boot(self):
        self.log("正在检测 adb 与车机…")
        ok, info = self.client.ensure()
        if ok:
            self.client.serial = info
            dinfo = self.client.device_info()
            self.root.after(0, lambda: self.lbl_dev.configure(text=f"{dinfo}  ({info})"))
            self.root.after(0, lambda: self._set_state("已连接", ACCENT))
            self.log(f"✓ 已连接：{dinfo}（序列号 {info}）")
            self.log(f"adb: {self.adb_path.get()}")
            if self.aapt2:
                self.log(f"aapt2: {self.aapt2}")
            else:
                self.log("⚠ 未找到 aapt2，无法自动解析包名（启动/卸载按钮不可用）")
        else:
            self.root.after(0, lambda: self.lbl_dev.configure(text="—"))
            self.root.after(0, lambda: self._set_state("未连接", RED))
            self.log(f"✗ {info}")

    def on_refresh(self):
        if self.busy:
            return
        self._set_busy(True)
        self._set_state("检测中…", AMBER)

        def work():
            self.client.adb = self.adb_path.get()
            ok, info = self.client.ensure()
            if ok:
                self.client.serial = info
                dinfo = self.client.device_info()
                self.root.after(0, lambda: self.lbl_dev.configure(text=f"{dinfo}  ({info})"))
                self.root.after(0, lambda: self._set_state("已连接", ACCENT))
                self.log(f"✓ 已连接：{dinfo}（{info}）")
            else:
                self.root.after(0, lambda: self.lbl_dev.configure(text="—"))
                self.root.after(0, lambda: self._set_state("未连接", RED))
                self.log(f"✗ {info}")
            self.root.after(0, lambda: self._set_busy(False))

        threading.Thread(target=work, daemon=True).start()

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
        self.client.pushed_apk = None      # 换了文件，设备上的旧包作废
        self.btn_launch.configure(state="disabled")
        self.btn_uninstall.configure(state="disabled")
        if self.aapt2:
            threading.Thread(target=self._parse_apk, args=(p,), daemon=True).start()
        else:
            self.log(f"已选择：{os.path.basename(p)}（无 aapt2，安装后需手动启动）")

    def _parse_apk(self, path):
        try:
            p = subprocess.run([self.aapt2, "dump", "badging", path],
                               capture_output=True, text=True, timeout=30,
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
            self.root.after(0, lambda: self.btn_uninstall.configure(
                state="normal" if self.pkg_name else "disabled"))
        except Exception as e:
            self.log(f"⚠ 解析 APK 失败：{e}")

    def on_upload(self):
        if self.busy:
            return
        path = self.apk_path.get()
        if not path or not os.path.isfile(path):
            messagebox.showwarning(APP_TITLE, "请先选择一个 APK 文件")
            return
        self._set_busy(True)

        def work():
            if not self.client.serial:
                ok, info = self.client.ensure()
                if not ok:
                    self.log(f"✗ {info}")
                    self.root.after(0, lambda: self._set_busy(False))
                    return
                self.client.serial = info
            ok = self.client.push(path)
            self.root.after(0, lambda: self._set_busy(False))
            if ok:
                self.root.after(0, lambda: self._set_state("已连接", ACCENT))

        threading.Thread(target=work, daemon=True).start()

    def on_install(self):
        if self.busy:
            return
        apk = self.apk_path.get()
        if not apk or not os.path.isfile(apk):
            messagebox.showwarning(APP_TITLE, "请先选择 APK 文件")
            return
        # 防装错包：设备上的 upload.apk 必须就是当前选中的这个文件
        if os.path.abspath(apk) != (self.client.pushed_apk or ""):
            messagebox.showwarning(APP_TITLE, "设备上还没有当前 APK，请先点「① 上传到车机」")
            return
        self._set_busy(True)

        def work():
            # 勾选「覆盖安装」才允许在签名冲突时自动卸旧版；不勾就是纯 -r 覆盖
            pkg = self.pkg_name if self.force_reinstall.get() else ""
            ok, _ = self.client.install(pkg)
            self.root.after(0, lambda: self._set_busy(False))
            if ok:
                self.root.after(0, lambda: self.btn_launch.configure(state="normal" if self.launch_component else "disabled"))
                self.root.after(0, lambda: self.btn_uninstall.configure(state="normal" if self.pkg_name else "disabled"))
                self.log(f"提示：应用已安装{f'（{self.pkg_name}）' if self.pkg_name else ''}")

        threading.Thread(target=work, daemon=True).start()

    def on_logcat(self):
        if self.busy:
            return
        self._set_busy(True)

        def work():
            if not self.client.serial:
                ok, info = self.client.ensure()
                if not ok:
                    self.log(f"✗ {info}")
                    self.root.after(0, lambda: self._set_busy(False))
                    return
            remote = self.client.logcat()
            ts = time.strftime("%Y%m%d_%H%M%S")
            local = os.path.join(r"E:\Code\_logs", f"xiaoba_logcat_{ts}.txt")
            self.client.pull(remote, local)
            self.root.after(0, lambda: self._set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    def on_launch(self):
        if self.busy or not self.launch_component:
            return
        self._set_busy(True)
        threading.Thread(target=lambda: (self.client.launch(self.launch_component),
                                         self.root.after(0, lambda: self._set_busy(False))),
                         daemon=True).start()

    def on_uninstall(self):
        if self.busy or not self.pkg_name:
            return
        if not messagebox.askyesno(APP_TITLE, f"确认卸载 {self.pkg_name}？"):
            return
        self._set_busy(True)
        threading.Thread(target=lambda: (self.client.uninstall(self.pkg_name),
                                         self.root.after(0, lambda: self._set_busy(False))),
                         daemon=True).start()


def main():
    if "--selftest" in sys.argv:
        print("adb:", find_adb())
        print("aapt2:", find_aapt2() or "未找到")
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
