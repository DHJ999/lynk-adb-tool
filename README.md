<h1 align="center" id="lynk-adb-tool">领克8155车机 ADB 安装工具</h1>

<p align="center"><strong>领克8155车机 ADB 安装工具：Windows GUI，上传/安装/启动 APK。</strong></p>

<p align="center">
  <a href="https://github.com/DHJ999/lynk-adb-tool"><img src="https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6?style=flat-square&logo=windows" alt="Platform"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://www.android.com/"><img src="https://img.shields.io/badge/Android-11-3DDC84?style=flat-square&logo=android&logoColor=white" alt="Android"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License"></a>
  <a href="https://github.com/DHJ999/lynk-adb-tool/releases/latest"><img src="https://img.shields.io/github/v/release/DHJ999/lynk-adb-tool?style=flat-square&label=release" alt="Release"></a>
  <a href="https://github.com/DHJ999/lynk-adb-tool/releases"><img src="https://img.shields.io/github/downloads/DHJ999/lynk-adb-tool/total?style=flat-square" alt="Downloads"></a>
  <a href="https://github.com/DHJ999/lynk-adb-tool/stargazers"><img src="https://img.shields.io/github/stars/DHJ999/lynk-adb-tool?style=flat-square" alt="Stars"></a>
</p>

> 在25款03 OSN2.0车机上测试使用编写。

## 下载即用

从 [Releases](https://github.com/DHJ999/lynk-adb-tool/releases/latest) 下载
`LynkAdbTool-win64.zip`，解压后双击 `LynkAdbTool.exe`。

发布包已内置 adb，**不需要安装 Python，也不需要 Android SDK**。

## 功能

- 一键上传、安装、启动、卸载 APK
- 列出已安装应用（应用名 + 包名），支持输入包名卸载
- 绕过车机 adbd 对 `install` 字符串的过滤
- USB 断线自动重连，失败自动重试
- 签名冲突时自动卸载旧版再安装
- 上传后校验设备端文件大小，避免半截包
- 一键抓取 logcat 到本地

## 快速开始

1. 解压 `LynkAdbTool-win64.zip`
2. 双击 `LynkAdbTool.exe`
3. 车机开启 USB 调试，连接 USB，弹窗点「允许」
4. 选择 APK → **① 上传到车机** → **② 安装** → **③ 启动应用**
5. 出问题点 **④ 抓日志**
6. 要卸载软件点 **⑤ 应用列表**，可按应用名/包名搜索

> 应用名需要读取 APK 资源，首次刷新会慢一些；勾选「包含系统应用」后会明显更慢。

## 为什么需要它

这台车机的 adbd 有三个坑，普通 `adb install` 全部失败：

| 坑 | 现象 | 本工具的处理 |
|---|---|---|
| adbd 过滤命令里的 `install` | `adb install` / `pm install` 返回 `error: closed` | 用 `ins''tall` 引号拼接绕过 |
| USB 链路不稳 | 随机 `error: closed` / `offline` | 自动 `kill-server` 重连，失败重试 3 次 |
| 车机 ADB 重启后关闭 | `adb devices` 为空 | 「重新检测」重新握手 |

## 从源码运行

需要 Windows 10/11 + Python 3.10+（带 tkinter）。

```text
车机App安装工具.bat  主启动器（中文入口）
run.bat              实际启动逻辑（桌面入口可直接调用）
诊断启动.bat         带控制台启动，排错用
检查环境.bat         检查 Python / tkinter / adb / aapt2
lynk_adb_tool.py     主程序
```

adb 会自动从 `tools\adb\`、Android SDK 或 PATH 查找，也可以在界面里手动指定。
aapt2 是可选的，只用于自动解析 APK 包名。

## 自己打包

```bat
python -m pip install pyinstaller
build_release.bat
```

输出：

```text
release\LynkAdbTool\LynkAdbTool.exe
release\LynkAdbTool-win64.zip
```

推送 `v*` 标签时，GitHub Actions 会自动构建并发布新的 Release。

## 常见问题

**双击后没反应、闪退，或提示缺模块？**  
双击 `诊断启动.bat`，它会用带控制台的 `python.exe` 启动并显示完整报错。

**adb 显示 offline？**  
软件里开关 USB 调试通常无效。请在车机端拔插 USB，或重启车机，再点「重新检测」。

**同时插了手机？**  
工具默认选 `adb devices` 里第一台 `device` 设备，使用前先拔掉手机，避免装错设备。

**没有 aapt2？**  
不影响上传和安装，只是启动/卸载需要手动填包名。

## 许可证

本项目使用 [MIT License](LICENSE)。  
分发的 Android platform-tools 归 Google 所有，遵循 Apache 2.0 许可。

## 讨杯水

如果这个工具帮到了你，可以请我喝杯水。完全自愿，不影响使用和更新。

<div align="center">

<table>
  <tr>
    <td align="center">
      <img src="assets/donate/wechat.jpg" width="240" alt="微信赞赏码"><br>
      <b>微信</b>
    </td>
    <td align="center">
      <img src="assets/donate/alipay.jpg" width="240" alt="支付宝赞赏码"><br>
      <b>支付宝</b>
    </td>
  </tr>
</table>

</div>
