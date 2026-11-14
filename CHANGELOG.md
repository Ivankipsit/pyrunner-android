# Changelog

Versions match the app version in the Android `versionName` and the Windows package. Downloads for a version are on the [releases page](https://github.com/Ivankipsit/pyrunner-android/releases).

## 0.1.2

- Android opens the editor. Launch no longer crashes while coloring the status bar, which happened before the window existed on Android 15. The page, stylesheet, and scripts are read from the APK. WebView is not asked to load them as `file://`, and it is not allowed to fetch them from the network.
- Windows is a double-click `PyRunner.exe`. It opens the same UI. Scripts run inside that program, with the built-in scraping packages.

Installers:

- [Android APK](https://github.com/Ivankipsit/pyrunner-android/releases/download/v0.1.2/pyrunner-android-0.1.2.apk)
- [Windows app](https://github.com/Ivankipsit/pyrunner-android/releases/download/v0.1.2/PyRunner.exe)

## 0.1.1

Fixes the Android app opening onto a blank screen.

The UI was loaded as `file://`, and WebView then refused `css/app.css`, the editor bundle, and `js/app.js`. Those files are now read out of the APK by `WebViewAssetLoader` and shown on `https://appassets.androidplatform.net`, which the app intercepts and does not send over the network. Any other URL is refused.

- [Android APK](https://github.com/Ivankipsit/pyrunner-android/releases/download/v0.1.1/pyrunner-android-0.1.1.apk)

The Windows zip did not change. Keep using [0.1.0](https://github.com/Ivankipsit/pyrunner-android/releases/download/v0.1.0/PyRunner-windows-0.1.0.zip).

## 0.1.0

First build you can install.

- Shared editor UI (CodeMirror 6, bundled, no CDN) for Android and Windows. The UI shows only the features that host reports.
- Run a script from the editor with live stdout and stderr.
- Several scripts at once, each with status, Stop, and Kill. Android uses up to three Chaquopy processes and falls back to one shared interpreter if a process slot does not start. Windows uses real subprocesses (up to eight).
- Saved-script library: create, edit, rename, delete, and run.
- Open a `.py` file. Android uses the system document picker and runs a copy. Windows uses a native dialog and runs with that file's folder as the working directory.
- Android keeps a long run going with the screen off (foreground service and a partial wake lock, 12 hour cap).
- Windows can `pip install` a PyPI package by name while the app is open, and scripts can use `multiprocessing`. Playwright and Selenium are an optional extra; the app does not download browser binaries.
- Coding agent screen is a placeholder. No model is downloaded and no cloud model is called.
- Private by design: no telemetry. The Windows UI server binds to 127.0.0.1 only.

Installers:

- [Android APK](https://github.com/Ivankipsit/pyrunner-android/releases/download/v0.1.0/pyrunner-android-0.1.0.apk)
- [Windows zip](https://github.com/Ivankipsit/pyrunner-android/releases/download/v0.1.0/PyRunner-windows-0.1.0.zip)

The Android multi-process kill was proved in code and in the desktop tests. It has not been run on a phone yet. After sideload, use Device → Test parallel kill. See [docs/concurrency-spike.md](docs/concurrency-spike.md).

## Next: 0.2.0

Not started. Planned scope:

- On-device coding agent. Android: llama.cpp with a small model such as Qwen2.5-Coder 3B, sized for a phone with 12 GB of RAM. Windows: a larger local model through llama.cpp, or Ollama bound to 127.0.0.1. No cloud model. You approve a run before it starts.
- Android helper that loads a JS-heavy page in a hidden WebView and hands the finished HTML to the script. Playwright and Selenium stay Windows-only.
- Pure-Python package installs on Android at runtime. Packages with C code still need a new APK.
- Signed sideload APK. Still not a Play Store listing.
- Record the result of the on-phone parallel-kill test in the concurrency note.

Out of scope until a later version: Play Store distribution, and any analytics or crash reporting.
