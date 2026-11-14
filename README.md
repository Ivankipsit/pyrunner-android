# PyRunner

**[Download the Android app](https://github.com/Ivankipsit/pyrunner-android/releases/download/v0.1.1/pyrunner-android-0.1.1.apk)** (sideload APK, 0.1.1) · **[Download the Windows app](https://github.com/Ivankipsit/pyrunner-android/releases/download/v0.1.0/PyRunner-windows-0.1.0.zip)** (portable zip, 0.1.0) · [Releases](https://github.com/Ivankipsit/pyrunner-android/releases)

Android is **0.1.1**. The Windows zip is still **0.1.0** because that build did not change. What shipped, and what **0.2.0** will add, is in [CHANGELOG.md](CHANGELOG.md).

PyRunner runs Python you type or open: scrapers and small scripts, several at once, with a live log. There is an Android app and a Windows app. They share one UI (`ui/`). The phone build is sideloaded. The Windows build is a portable folder. Unzip the Windows download and run `PyRunner.cmd`. On the phone, allow installs from your file manager, or `adb install -r pyrunner-android-0.1.1.apk`.

Nothing in the app phones home. There is no analytics SDK and no crash reporter. The UI is bundled; it does not load a CDN. The Android UI WebView refuses any non-bundled URL. A script you run can still use the network. That is the script, not the app.

The Windows window is pywebview. To show a local page it starts Bottle on **127.0.0.1** and a random port (Bottle's default bind address; it is not `0.0.0.0`). That server only exists so the window can load the bundled UI and the JS bridge. Debug mode is off.

The coding agent is a placeholder screen. A later version is planned to run llama.cpp on the phone (a small model such as Qwen2.5-Coder 3B, for a phone with 12 GB of RAM) and a larger local model on Windows (llama.cpp, or Ollama bound to 127.0.0.1). This milestone does not download or run a model.

## What works

| | Android | Windows |
| --- | --- | --- |
| Run the editor, stream stdout and stderr | Yes | Yes |
| Several scripts at once, each with status, Stop, and Kill | Yes, up to 3 processes. See the spike. | Yes, up to 8 subprocesses |
| Stop (KeyboardInterrupt) | Yes | Yes |
| Kill a script that ignores interrupts | Yes, by killing that app process | Yes, by killing that OS process |
| Save, rename, delete, and reopen scripts | Yes | Yes |
| Open a `.py` from the system file picker | Storage Access Framework. The app runs a copy, so files next to the script are not visible. | Native dialog. The run's working directory is the file's folder, so relative paths and local imports work. |
| Keep running with the screen off | Foreground service plus a partial wake lock, capped at 12 hours | Leave the window open. Closing it stops running scripts. |
| pip while the app is open | No. Native packages are baked into the APK. | Yes. A PyPI name only, not a URL. |
| `multiprocessing` | No | Yes |
| Playwright / Selenium | No | Installed only with the `browsers` extra. Browser binaries are not downloaded for you. |
| On-device coding agent | Placeholder | Placeholder |

Stop asks the script to raise `KeyboardInterrupt`. A script that catches it and keeps going stays running; the status returns to running and the error line says so. Kill is the one that ends it. Details and the on-device check are in [docs/concurrency-spike.md](docs/concurrency-spike.md).

The desktop host also runs on Linux, which is how the tests run. The packaged artifact is the Windows folder.

## Android packages

Pinned in [android/packages.txt](android/packages.txt). Native versions are the CPython 3.13 wheels Chaquopy publishes (`cp313`, `android_24`, `arm64_v8a` and `x86_64`):

| Package | Pin | Why this pin |
| --- | --- | --- |
| numpy | 1.26.2 | Newest cp313 Android wheel in Chaquopy's index |
| pandas | 2.1.3 | Same. It is older than current desktop pandas. |
| lxml | 5.3.0 | Same |
| aiohttp | 3.10.10 | Same, plus the matching frozenlist, multidict, and yarl wheels |
| requests, httpx, beautifulsoup4, python-dotenv, tenacity, tqdm | portable wheels | Pure Python |

Python is 3.13 because current phones use 16 KB memory pages, and Chaquopy recommends 3.13 or newer for that. The build machine must have a CPython 3.13 as well (`buildPython`). `propcache` is pulled in as a pure-Python wheel so yarl 1.16 can import.

`check_packages.py` is seeded into the library. Run it on a phone to see what imports. pandas 2.1.3 and numpy 1.26.2 were not originally shipped for 3.13; Chaquopy built the wheels anyway. If an import fails on device, that script is the check.

Playwright and Selenium are not in the APK. Headless browser binaries do not run inside an Android app.

## Windows packages

[windows/pyproject.toml](windows/pyproject.toml). `uv sync` installs the scraping set: requests, httpx, beautifulsoup4, lxml, pandas, numpy, aiohttp, python-dotenv, tenacity, tqdm, plus pywebview and pip.

```bash
cd windows
uv sync --group dev --extra browsers
```

`--extra browsers` adds Playwright and Selenium. It does not download browser binaries. A script that needs them has to have those binaries installed already; the app will not fetch them.

Runtime installs from the Device screen accept a name like `requests` or `requests==2.32.3`. They reject URLs and paths.

## Build the Android debug APK

Requirements: JDK 17 or 21, Android SDK 35, Build-Tools 35.0.0, a CPython 3.13 on `PATH` or in `PYRUNNER_BUILD_PYTHON`, and the UI bundle already built (`ui/vendor/codemirror-bundle.js` is committed).

```bash
cd ui && npm ci && npm run build   # only if you change the editor bundle
cd ../android
# local.properties is gitignored
echo "sdk.dir=$ANDROID_HOME" > local.properties
echo "build.python=$(uv python find 3.13)" >> local.properties
chmod +x ./gradlew
./gradlew :app:assembleDebug :app:testDebugUnitTest
```

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`. It contains `arm64-v8a` and `x86_64`. A phone wants arm64. The file is large because numpy and pandas are in the APK twice, once per ABI.

Chaquopy is 17.2.0 (MIT). The Android Gradle Plugin is 8.13.0, within the range Chaquopy tests.

### Sideload

The app is not published. On the phone, allow installs from your file manager or `adb`, then:

```bash
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```

Debug builds allow WebView inspection over USB. Release signing is not part of this milestone. For a long scrape, open Device and tap **Allow unrestricted battery use**, then confirm the system dialog. The run notification should stay while a script is active. Each run is stopped after 12 hours.

Scripts and the library stay in the app's private storage. Backup and device transfer are off.

## Build and run on Windows

```bash
cd windows
uv python install 3.13
uv sync --python 3.13 --group dev --extra browsers
uv run pytest
uv run pyrunner
```

`uv run pyrunner` opens the shared UI. Scripts and the library are stored in `%APPDATA%\PyRunner`.

A portable folder, for a machine that should not need a separate Python install:

```bash
uv run python build_portable.py
```

That writes `windows/dist/PyRunner/` and `windows/dist/PyRunner-windows.zip`. Unzip it and double-click `PyRunner.cmd`. The folder includes the uv-managed interpreter and site-packages. `PyRunner.cmd console` keeps a console window. Host errors also go to `%APPDATA%\PyRunner\host.log`.

WebView2, which current Windows already has, is what paints the UI. pywebview's `js_api` is the bridge. The local page is served on 127.0.0.1, as described above. Debug mode is off.

## UI bundle

The editor is CodeMirror 6, bundled into `ui/vendor/codemirror-bundle.js` so the app never fetches it. Rebuild with `npm ci && npm run build` inside `ui/` after changing `ui/editor/entry.js`. The MIT notice is `ui/vendor/NOTICE`.

## Tests

```bash
cd windows && uv sync --group dev && uv run pytest
cd ../android && ./gradlew :app:testDebugUnitTest
```

Desktop tests cover the library, streaming, cooperative stop, process kill while another script continues, the queue, multiprocessing spawn, the JSON API, and a check that the UI files contain no remote URL. Android unit tests cover the same library rules, the WebView URL allow-list, and the run log. They do not boot an emulator.

## GitHub Actions

- `.github/workflows/android-debug.yml` builds the debug APK and uploads it.
- `.github/workflows/windows.yml` runs the pytest suite on Linux and, on `windows-latest`, builds `PyRunner-windows.zip`.

## Layout

```
ui/                  shared HTML, CSS, JS, CodeMirror bundle
runtime/pyrunner_rt  in-process runner used on Android and by tests
examples/            seeded into the library
android/             Kotlin, WebView, Chaquopy, foreground service, 3 slot processes
windows/             Python host, subprocess runner, portable build
docs/concurrency-spike.md
```

The Gradle build copies `ui/`, `runtime/`, and `examples/` into the APK. Don't edit the copies under `android/app/src/main/assets` or `python/`; they are generated and gitignored.

## Privacy

- No telemetry, no analytics, no crash uploads.
- Editor assets are in the APK and in the Windows folder.
- Android WebView: JavaScript is on, remote loads are blocked, cookies and safe browsing are off. Safe browsing would send URLs to Google.
- `INTERNET` is requested so your scripts can scrape. The UI does not make its own requests. The Windows pip button is the exception, and only after you type a package name.
- Cleartext HTTP is allowed for scripts that still talk to `http://` sites.
- The Windows host passes its own environment into the script. If that environment has secrets, the script can read them. The app does not add any of its own.
- Logs and scripts are local files. They are not in git (see `.gitignore`).

## Main branch

`main` accepts changes through a pull request. These checks have to pass before merge: `apk`, `test`, and `package`. Force-pushes and deleting `main` are not allowed. That ruleset is [`.github/rulesets/main.json`](.github/rulesets/main.json). GitHub has not enforced the file on the private repo yet: creating a repository ruleset from here was rejected (the list API asks for GitHub Pro, and this token cannot administer rules).

## Not in 0.1.0

Moved to the [changelog](CHANGELOG.md#next-020). The coding agent is still a placeholder, Android has no signed release APK and no Play Store listing, and JS-heavy pages are not rendered for Android scripts yet.
