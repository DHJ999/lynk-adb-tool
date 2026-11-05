# adb 放置目录

发布打包时把 Android platform-tools 的这三个文件放到本目录：

```text
tools/adb/
├── adb.exe
├── AdbWinApi.dll
└── AdbWinUsbApi.dll
```

程序会优先使用本目录的 adb，找不到才去 Android SDK / PATH 查找。

源码仓库默认不提交这些二进制（见 `.gitignore`），
由 `build_release.bat` 或 GitHub Actions 在打包时复制进来。
