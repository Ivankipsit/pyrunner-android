# Concurrency spike

Question: can PyRunner run more than one script at the same time, and kill one of them even if that script swallows `KeyboardInterrupt`?

## What was built

Android declares three services, `:runner0`, `:runner1`, and `:runner2`. Each service runs in its own process and starts its own Chaquopy interpreter. The UI process does not start Python unless the process runners fail and the app falls back to threads.

The main process binds to a free slot, sends it a script path (the source stays in the app's private files, not in a Binder transaction), and streams stdout/stderr back over a `Messenger`. **Stop** sets a flag that the runner turns into `KeyboardInterrupt`, including during `time.sleep`. **Kill** calls `Process.killProcess` on that slot's pid. Processes of the same app share a uid, so the main process is allowed to do that. The slot comes back clean on the next bind.

A file lock around `Python.start` keeps two slots from unpacking the Chaquopy runtime at the same instant.

If a slot does not answer within 45 seconds, the app switches to thread fallback and says so. Thread fallback runs up to three scripts inside the UI process. Stop still raises `KeyboardInterrupt`. Kill cannot tear down a stuck native call, and the Kill button says so. Device → "Use process runners" switches back.

The desktop host does not use threads for this. Each script is a subprocess in its own session (`start_new_session` on POSIX, `CREATE_NEW_PROCESS_GROUP` on Windows). Stop sends `SIGINT` (or `CTRL_BREAK` on Windows, which the child turns into `KeyboardInterrupt`). Kill sends `SIGKILL` or `TerminateProcess` to that process group. A script that catches `KeyboardInterrupt` keeps running after Stop; Kill still ends it. The other scripts are separate processes and are not affected.

Both hosts expose the same check: Device → "Test parallel kill". It starts a script that ignores `KeyboardInterrupt` and a second script that sleeps and prints a token, kills the first, and checks that the second still finishes.

## What was verified here

The desktop proof is `windows/tests/test_supervisor.py`. These tests passed on this dev host (CPython 3.13, Linux), including a real `SIGKILL` of one process while the other printed its second token, and a spawn-mode `multiprocessing` pool:

- `test_kill_one_of_two` runs the probe and requires the catch-loop script to end as `killed` while the other script prints its second token.
- `test_stop_does_not_force_a_catch_loop` checks that Stop is only an interrupt.
- `test_stop_interrupts_sleep` checks that a normal `time.sleep` does stop.
- `test_queue_respects_slot_limit` checks the queue.
- `test_multiprocessing_spawn` runs `examples/desktop/multiprocess_check.py` with the spawn start method, which is the Windows path.

`runtime` tests also run two `execute_source` calls in parallel and check that their stdout does not mix. That is the thread-fallback output path.

The Android APK build is the compile-time check: the manifest contains the three slot processes, and Chaquopy packages the runner. This environment has no Android emulator and no phone, so the slot processes were not started and Chaquopy was not asked to boot twice. Do not treat a green APK build as a passed probe.

## What to run on a phone

Install the debug APK, open Device, and tap **Test parallel kill**. The first run can take a while because each slot unpacks Python on first use. A pass means process kill works on that phone. A fail, or the notice "Switching to the shared interpreter", means this phone is on the thread fallback. The result is stored and shown on that screen after the next launch.

A manual check: run `background_demo.py`, leave the app, and lock the screen. The notification should stay and the log should keep growing. That is the foreground service (`specialUse`, not `dataSync`, because Android 15 limits data-sync services). A partial wake lock is held for at most 12 hours, which is also the per-run timeout.

## Risks that are still open

- Chaquopy does not document multi-process use. Each process has its own VM, which is what we want, but a future Chaquopy release could add process-global native state.
- Three interpreters with numpy and pandas can use a lot of RAM. The phone decision for this project is 12 GB, and the app sets `largeHeap`, but a low-memory kill of one slot marks that run killed and leaves the others up.
- `multiprocessing` inside an Android script still does not work. There is no usable `python` executable and no System V IPC. The desktop subprocess host does support it.
- Thread fallback shares `sys.path` and the process working directory. Process mode and the desktop host give each run its own working directory.
- On Windows, Kill ends the script process. A `multiprocessing` pool is a child of that process; POSIX Kill also signals the process group, which covers those children.

## Decision

Ship process slots as the Android default, with an automatic thread fallback and a button to switch back. The desktop app uses subprocesses only. The on-device result is not known until the probe above is run on hardware.
