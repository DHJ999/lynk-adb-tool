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

> 在 25 款领克 03（OSN 2.0，车机代号 CS11 / geely_fx11，8155 平台）上测试编写。

## 免责声明

使用本工具前请务必阅读并理解以下内容，**点击使用即视为已阅读并同意**：

1. 本工具仅供个人学习、研究与开发调试用途，请勿用于任何违法用途。
2. 通过本工具安装、卸载、修改车机应用属于**自行改装行为**，可能导致车辆系统不稳定、
   功能异常或失去质保；由此产生的一切后果由使用者本人承担。
3. 操作前请自行备份重要数据。卸载系统关键应用可能导致车机部分功能不可用。
4. 从第三方渠道获取的 APK 的来源与安全性由使用者自行甄别，作者不对第三方软件
   造成的任何损害负责。
5. 本工具按「现状」提供，不作任何明示或默示的担保；作者不对使用本工具造成的
   直接或间接损失（包括但不限于车辆故障、保修失效、数据丢失）承担责任。
6. 本工具与领克汽车、吉利汽车、ECARX（亿咖通）无任何隶属、授权或合作关系。
7. 请在遵守当地法律法规的前提下使用；驾驶时请勿操作车机调试工具。

## 下载即用

从 [Releases](https://github.com/DHJ999/lynk-adb-tool/releases/latest) 下载
`LynkAdbTool-win64.zip`，解压后双击 `LynkAdbTool.exe`。

发布包已内置 adb 与 aapt2，**不需要安装 Python，也不需要 Android SDK**。

## 功能

- 一键上传、安装、启动、卸载 APK
- 列出已安装应用（应用名 + 包名），支持输入包名卸载
- 绕过车机 adbd 对 `install` 字符串的过滤
- USB 断线自动重连，失败自动重试
- 签名冲突时自动卸载旧版再安装
- 上传进度按 adb 实际传输百分比显示，结束后校验设备端文件大小，避免半截包
- 一键抓取 logcat 到本地
- 界面配色跟随系统深浅色，切换后自动重建
- 内置反馈入口（邮箱一键复制 / 唤起邮件客户端）与赞赏入口（微信、支付宝收款码）

## 快速开始

1. 解压 `LynkAdbTool-win64.zip`
2. 双击 `LynkAdbTool.exe`
3. 车机开启 USB 调试，连接 USB，弹窗点「允许」
4. 选择 APK → **① 上传并安装** → **② 启动应用**
5. 出问题点 **③ 抓日志**
6. 要卸载软件点 **④ 应用列表**，可按应用名/包名搜索

> 应用名需要读取 APK 资源，首次刷新会慢一些；勾选「包含系统应用」后会明显更慢。

## 为什么需要它

这台车机的 adbd 有三个坑，普通 `adb install` 全部失败：

| 坑 | 现象 | 本工具的处理 |
|---|---|---|
| adbd 过滤命令里的 `install` | `adb install` / `pm install` 返回 `error: closed` | 用 `ins''tall` 引号拼接绕过 |
| USB 链路不稳 | 随机 `error: closed` / `offline` | 先温和 `reconnect`，判明确实掉线才 `kill-server` 重启，并重试 3 次 |
| 车机 ADB 重启后关闭 | `adb devices` 为空 | 「重新检测」重新握手 |

## 从源码运行

需要 Windows 10/11 + Python 3.10+（带 tkinter）。

```text
run.bat              主启动器（双击即用，自动找带 tkinter 的 Python）
诊断启动.bat         带控制台启动并先跑自检，打不开时排错用
build_release.bat    打包发布（PyInstaller + 内置 adb/aapt2 + zip）
lynk_adb_tool.py     主程序
```

启动器会自动枚举便携 `python\`、uv 安装目录和 PATH，不再依赖写死的版本号；
找不到带 tkinter 的 Python 时会明确提示，而不是闪退。

adb 会自动从 `tools\adb\`、Android SDK 或 PATH 查找，aapt2 会从 `tools\aapt2\`、
SDK 的 `build-tools` 查找（也可用环境变量 `LYNK_AAPT2` 直接指定），也可以在界面里手动指定 adb。
命令行运行 `python lynk_adb_tool.py --selftest` 可快速查看两者的解析结果。

运行时会生成 `logs\`（logcat 落盘）和 `label_cache.json`（应用名缓存），两者都已在
`.gitignore` 中忽略，不会进仓库。

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
双击 `诊断启动.bat`，它会先用带控制台的 `python.exe` 打印自检结果，再启动程序并显示完整报错。

**adb 显示 offline？**  
软件里开关 USB 调试通常无效。请在车机端拔插 USB，或重启车机，再点「重新检测」。

**同时插了手机？**  
工具会读取每台设备的型号做识别：唯一的领克车机直接连接；检测到非领克设备或多台设备时，
会弹出选择框列出 序列号 + 型号，由你手动指定目标。卸载确认框也会再次显示目标设备，
避免装错/卸错设备。

**没有 aapt2？**  
发布包已内置，免安装版不受影响。从源码运行时程序会自动在 SDK 的 `build-tools` 里找；
一个都没有时仍可上传、安装、按包名卸载，只是「② 启动应用」不可用、应用名显示为「—」。

## 许可证

本项目使用 [MIT License](LICENSE)。  
分发的 Android platform-tools 归 Google 所有，遵循 Apache 2.0 许可。

## 反馈与赞赏

**反馈**：用着有问题、想提建议，或者装成功了想说一声，都可以发邮件到
**hjd2002@yeah.net**；程序底栏的「反馈」按钮里可一键复制邮箱或直接唤起邮件客户端。

反馈时附上设备栏的型号与序列号、点过的按钮和完整报错，以及「日志目录」里对应的
`car_logcat_*.txt`，定位会快很多。

## 讨杯水

如果这个工具帮到了你，可以扫码请我喝杯水。完全自愿，不影响使用和更新。
程序底栏的「赞赏」按钮里也有同样的两张码。

<div align="center">

<table>
  <tr>
    <td align="center">
      <img src="assets/donate/wechat.jpg" width="240" alt="微信收款码"><br>
      <b>微信（扫码后转账）</b>
    </td>
    <td align="center">
      <img src="assets/donate/alipay.jpg" width="240" alt="支付宝收款码"><br>
      <b>支付宝（扫码后转账）</b>
    </td>
  </tr>
</table>

</div>
