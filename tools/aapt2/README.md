# aapt2 放置目录（可选）

如果希望发布包在**没有 Android SDK** 的电脑上也能自动解析 APK 包名，
可以把 `aapt2.exe` 放到本目录：

```text
tools/aapt2/aapt2.exe
```

程序会优先使用本目录的 aapt2，找不到才去 SDK `build-tools` 查找。

没有 aapt2 不影响上传和安装，只是“启动应用 / 卸载”需要手动填包名。
