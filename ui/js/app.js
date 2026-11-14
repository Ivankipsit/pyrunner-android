(function () {
  const $ = (id) => document.getElementById(id);
  const DEFAULT_SOURCE = 'print("hello", flush=True)\n';
  const FEATURES = [
    ["liveOutput", "Live stdout and stderr"],
    ["concurrentRuns", "Several scripts at once"],
    ["cooperativeStop", "Stop sends KeyboardInterrupt"],
    ["hardKill", "Kill ends the script process"],
    ["scriptLibrary", "Saved script library"],
    ["filePicker", "Open a .py file"],
    ["foregroundService", "Keep running with the screen off"],
    ["pipRuntime", "pip install while the app is open"],
    ["multiprocessing", "multiprocessing inside a script"],
    ["playwright", "Playwright"],
    ["selenium", "Selenium"],
    ["localAgent", "On-device coding agent"],
    ["webviewRender", "Render a JS-heavy page for a script"],
  ];

  const state = {
    view: "editor",
    caps: null,
    scripts: [],
    runs: [],
    logs: {},
    links: {},
    images: {},
    activeRunId: null,
    editorId: null,
    originDir: null,
    name: "untitled.py",
    dirty: false,
    suppress: false,
    probe: null,
  };

  let editor = null;

  function banner(text, kind) {
    const el = $("banner");
    el.hidden = !text;
    el.textContent = text || "";
    el.className = kind === "error" ? "error" : "";
    clearTimeout(banner.timer);
    if (text && kind !== "error") {
      banner.timer = setTimeout(() => {
        el.hidden = true;
      }, 6000);
    }
  }

  function showError(err) {
    banner(err && err.message ? err.message : String(err), "error");
  }

  function hostReady() {
    return Boolean(
      (window.PyRunnerAndroid && window.PyRunnerAndroid.invoke) ||
        (window.pywebview && window.pywebview.api)
    );
  }

  function waitForHost() {
    if (hostReady()) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => resolve();
      window.addEventListener("pywebviewready", done, { once: true });
      setTimeout(done, 1500);
    });
  }

  async function invoke(method, params) {
    const body = JSON.stringify({ method: method, params: params || {} });
    let raw;
    if (window.PyRunnerAndroid && window.PyRunnerAndroid.invoke) {
      raw = window.PyRunnerAndroid.invoke(body);
    } else if (window.pywebview && window.pywebview.api) {
      raw = await window.pywebview.api.invoke(body);
    } else {
      throw new Error("Open this page inside the PyRunner app.");
    }
    const msg = JSON.parse(raw);
    if (!msg.ok) throw new Error(msg.error || "Request failed");
    return msg.result;
  }

  function show(view) {
    state.view = view;
    ["editor", "output", "runs", "library", "device", "agent"].forEach((name) => {
      $("view-" + name).hidden = name !== view;
    });
    document.querySelectorAll("#nav button").forEach((button) => {
      button.classList.toggle("active", button.dataset.view === view);
    });
    if (view === "library") renderLibrary();
    if (view === "device") renderDevice();
    if (view === "runs") renderRuns();
  }

  function updateNav() {
    const live = state.runs.filter((run) =>
      run.status === "running" || run.status === "queued" || run.status === "stopping"
    ).length;
    $("nav-runs").textContent = live ? "Runs " + live : "Runs";
  }

  function showDirty() {
    $("dirty").hidden = !state.dirty;
  }

  function setName(name) {
    state.name = name;
    $("script-name").value = name;
  }

  function setEditorValue(text) {
    state.suppress = true;
    editor.setValue(text);
    state.suppress = false;
    state.dirty = false;
    showDirty();
  }

  function markDirty() {
    if (state.suppress) return;
    state.dirty = true;
    showDirty();
  }

  function noteLog(id) {
    if (!state.logs[id]) {
      state.logs[id] = { text: "", nextSeq: 0, ready: false, pending: [], token: 0, truncated: false, trimmed: false };
    }
    return state.logs[id];
  }

  function trimLog(log) {
    if (log.text.length > 300000) {
      log.text = log.text.slice(-200000);
      log.trimmed = true;
    }
  }

  function applyOutput(log, event) {
    if (event.seq < log.nextSeq) return;
    if (event.seq > log.nextSeq) {
      refetch(event.runId);
      return;
    }
    log.text += event.text;
    log.nextSeq += 1;
    trimLog(log);
    renderLogs();
  }

  async function ensureLog(id) {
    const log = noteLog(id);
    const token = ++log.token;
    try {
      const result = await invoke("readLog", { runId: id, maxChars: 200000 });
      if (log.token !== token) return;
      log.text = result.text || "";
      log.nextSeq = result.nextSeq || 0;
      log.truncated = Boolean(result.truncated);
      log.ready = true;
      const pending = log.pending.splice(0);
      pending.forEach((event) => applyOutput(log, event));
      renderLogs();
    } catch (err) {
      showError(err);
    }
  }

  function refetch(id) {
    const log = noteLog(id);
    log.ready = false;
    ensureLog(id);
  }

  function onOutput(event) {
    const log = noteLog(event.runId);
    if (!log.ready) {
      log.pending.push(event);
      return;
    }
    applyOutput(log, event);
  }

  function upsertRun(run) {
    const index = state.runs.findIndex((item) => item.id === run.id);
    if (index === -1) state.runs.unshift(run);
    else state.runs[index] = run;
  }

  function onStatus(run) {
    upsertRun(run);
    if (!state.activeRunId) state.activeRunId = run.id;
    updateNav();
    renderRuns();
    renderLogs();
    refreshArtifacts(run.id).catch(() => {});
    const log = state.logs[run.id];
    if ((run.status === "running" || run.status === "queued" || run.status === "stopping") && (!log || !log.ready)) {
      ensureLog(run.id);
    }
  }

  function onProbe(msg) {
    state.probe = msg;
    banner(msg.ok ? "Parallel kill test passed." : "Parallel kill test did not pass. " + (msg.detail || ""), msg.ok ? "info" : "error");
    if (state.view === "device") renderDevice();
  }

  window.pyrunner = {
    receive(msg) {
      if (typeof msg === "string") {
        try {
          msg = JSON.parse(msg);
        } catch (err) {
          return;
        }
      }
      if (!msg || !msg.event) return;
      if (msg.event === "output") onOutput(msg);
      else if (msg.event === "status") onStatus(msg.run);
      else if (msg.event === "probe") onProbe(msg);
      else if (msg.event === "notice") banner(msg.text || "", "info");
    },
  };

  function renderLogs() {
    const log = state.activeRunId ? state.logs[state.activeRunId] : null;
    const text = log ? log.text : "";
    ["editor-log", "run-log"].forEach((id) => {
      const pre = $(id);
      const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 48;
      if (pre.textContent !== text) pre.textContent = text;
      if (atBottom) pre.scrollTop = pre.scrollHeight;
    });
    const run = state.runs.find((item) => item.id === state.activeRunId);
    let label = run ? run.name + " · " + run.status : "Output";
    if (log && (log.truncated || log.trimmed)) label += " (latest output)";
    $("editor-run-label").textContent = label;
    $("run-label").textContent = run ? label : "No run selected";
    const controllable = run && (run.status === "running" || run.status === "stopping");
    $("btn-stop").disabled = !controllable;
    $("btn-kill").disabled = !run || (run.status !== "running" && run.status !== "stopping" && run.status !== "queued");
    if (state.activeRunId && window.PyRunnerLive) {
      state.links[state.activeRunId] = window.PyRunnerLive.extractLinks(text);
    }
    renderLive();
  }

  function renderLive() {
    const panel = $("live-panel");
    const linksEl = $("live-links");
    const imagesEl = $("live-images");
    const runId = state.activeRunId;
    const links = (runId && state.links[runId]) || [];
    const images = [];
    const stored = runId && state.images[runId];
    if (stored) {
      Object.keys(stored).forEach((name) => {
        if (stored[name] && stored[name].base64) images.push(stored[name]);
      });
    }
    linksEl.textContent = "";
    links.forEach((url) => {
      const chip = document.createElement("span");
      chip.className = "live-link";
      chip.textContent = url;
      linksEl.append(chip);
    });
    const shown = imagesEl.dataset.names || "";
    const next = images.map((item) => item.name).join("\n");
    if (shown !== next) {
      imagesEl.textContent = "";
      images.forEach((item) => {
        const img = document.createElement("img");
        img.className = "live-image";
        img.alt = item.name;
        img.src = "data:" + item.mime + ";base64," + item.base64;
        imagesEl.append(img);
      });
      imagesEl.dataset.names = next;
    }
    panel.hidden = links.length === 0 && images.length === 0;
  }

  async function refreshArtifacts(runId) {
    if (!runId) return;
    const listed = await invoke("listArtifacts", { runId: runId });
    if (!state.images[runId]) state.images[runId] = {};
    const known = state.images[runId];
    for (const item of listed) {
      if (known[item.name] && known[item.name].base64) continue;
      if (known[item.name] && known[item.name].pending) continue;
      known[item.name] = { name: item.name, pending: true };
      try {
        known[item.name] = await invoke("readArtifact", { runId: runId, name: item.name });
      } catch (err) {
        delete known[item.name];
      }
      renderLive();
    }
  }

  function pill(status) {
    const span = document.createElement("span");
    span.className = "pill " + status;
    span.textContent = status;
    return span;
  }

  function renderRuns() {
    const list = $("run-list");
    list.textContent = "";
    if (!state.runs.length) {
      const empty = document.createElement("p");
      empty.className = "note";
      empty.textContent = "No runs yet. Start one from the editor.";
      list.append(empty);
      return;
    }
    state.runs.forEach((run) => {
      const row = document.createElement("div");
      row.className = "run-row" + (run.id === state.activeRunId ? " selected" : "");
      row.dataset.id = run.id;
      const name = document.createElement("button");
      name.type = "button";
      name.className = "name";
      name.textContent = run.name;
      name.addEventListener("click", () => {
        state.activeRunId = run.id;
        ensureLog(run.id);
        renderRuns();
        renderLogs();
        refreshArtifacts(run.id).catch(() => {});
      });
      const stop = document.createElement("button");
      stop.type = "button";
      stop.textContent = "Stop";
      stop.disabled = run.status !== "running" && run.status !== "stopping";
      stop.addEventListener("click", () => act("stop", run.id));
      const kill = document.createElement("button");
      kill.type = "button";
      kill.textContent = "Kill";
      kill.disabled = run.status !== "running" && run.status !== "stopping" && run.status !== "queued";
      kill.addEventListener("click", () => act("kill", run.id));
      row.append(name, pill(run.status), stop, kill);
      list.append(row);
    });
  }

  async function act(method, runId) {
    try {
      const run = await invoke(method, { runId: runId });
      onStatus(run);
    } catch (err) {
      showError(err);
    }
  }

  function renderLibrary() {
    const list = $("lib-list");
    const filter = ($("lib-filter").value || "").trim().toLowerCase();
    list.textContent = "";
    const rows = state.scripts.filter((script) => !filter || script.name.toLowerCase().includes(filter));
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "note";
      empty.textContent = state.scripts.length ? "No scripts match that filter." : "The library is empty. Save the editor to add one.";
      list.append(empty);
      return;
    }
    rows.forEach((script) => {
      const row = document.createElement("div");
      row.className = "lib-row";
      row.dataset.id = script.id;
      row.dataset.name = script.name;
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = script.name;
      const open = button("Open", () => loadScript(script.id).catch(showError));
      const run = button("Run", () => runSaved(script.id).catch(showError));
      const rename = button("Rename", () => beginRename(row, script));
      const remove = button("Delete", () => removeScript(row, script, remove).catch(showError));
      row.append(name, open, run, rename, remove);
      list.append(row);
    });
  }

  function button(label, onClick) {
    const el = document.createElement("button");
    el.type = "button";
    el.textContent = label;
    el.addEventListener("click", onClick);
    return el;
  }

  function beginRename(row, script) {
    const input = document.createElement("input");
    input.value = script.name;
    input.setAttribute("aria-label", "New name");
    const name = row.querySelector(".name");
    name.replaceWith(input);
    input.focus();
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      invoke("renameScript", { id: script.id, name: input.value })
        .then(refreshScripts)
        .catch(showError);
    });
  }

  async function removeScript(row, script, buttonEl) {
    if (row.dataset.confirm !== "yes") {
      row.dataset.confirm = "yes";
      buttonEl.textContent = "Confirm";
      return;
    }
    await invoke("deleteScript", { id: script.id });
    if (state.editorId === script.id) fresh();
    await refreshScripts();
  }

  async function refreshScripts() {
    state.scripts = await invoke("listScripts");
    renderLibrary();
  }

  async function loadScript(id) {
    const script = await invoke("getScript", { id: id });
    state.editorId = script.id;
    state.originDir = null;
    setName(script.name);
    setEditorValue(script.source);
    show("editor");
  }

  async function runSaved(id) {
    const script = await invoke("getScript", { id: id });
    await startRun(script.name, script.source, script.id, null);
    show("output");
  }

  async function startRun(name, source, scriptId, originDir) {
    const run = await invoke("run", {
      name: name,
      source: source,
      scriptId: scriptId,
      originDir: originDir,
    });
    state.activeRunId = run.id;
    onStatus(run);
    ensureLog(run.id);
  }

  async function runEditor() {
    await startRun(state.name || "untitled.py", editor.getValue(), state.editorId, state.originDir);
    show("output");
  }

  async function save() {
    const saved = await invoke("saveScript", {
      id: state.editorId,
      name: $("script-name").value,
      source: editor.getValue(),
    });
    state.editorId = saved.id;
    state.originDir = null;
    setName(saved.name);
    state.dirty = false;
    showDirty();
    await refreshScripts();
  }

  function fresh() {
    state.editorId = null;
    state.originDir = null;
    setName("untitled.py");
    setEditorValue(DEFAULT_SOURCE);
    state.dirty = true;
    showDirty();
  }

  async function openFile() {
    const file = await invoke("openFile");
    if (!file || file.cancelled) return;
    state.editorId = null;
    state.originDir = file.originDir || null;
    setName(file.name || "opened.py");
    setEditorValue(file.content || "");
    state.dirty = true;
    showDirty();
    show("editor");
  }

  function renderAgent() {
    const root = $("agent");
    root.textContent = "";
    const title = document.createElement("h2");
    title.textContent = "Coding agent";
    const body = document.createElement("p");
    body.className = "note";
    const android = state.caps && state.caps.platform === "android";
    body.textContent = android
      ? "A later version will run a small model on this phone with llama.cpp. Qwen2.5-Coder 3B is the candidate, sized for a phone with 12 GB of RAM. This build does not download or run a model, and it does not call a cloud model."
      : "A later version will run a larger local model through llama.cpp, or through Ollama bound to 127.0.0.1. This build does not download or run a model, and it does not call a cloud model.";
    root.append(title, body);
  }

  function renderDevice() {
    const root = $("device");
    const caps = state.caps;
    root.textContent = "";
    if (!caps) return;
    root.append(heading("This device"));
    root.append(note(
      caps.platform + " · Python " + caps.python + " · " + caps.concurrencyMode +
      " · " + caps.runnerSlots + " slots · v" + caps.appVersion
    ));
    const table = document.createElement("table");
    table.className = "feature-table";
    FEATURES.forEach((pair) => {
      const on = Boolean(caps.features && caps.features[pair[0]]);
      const row = document.createElement("tr");
      const label = document.createElement("td");
      label.textContent = pair[1];
      const value = document.createElement("td");
      value.className = on ? "yes" : "no";
      value.textContent = on ? "yes" : "no";
      row.append(label, value);
      table.append(row);
    });
    root.append(table);
    (caps.notes || []).forEach((text) => root.append(note(text)));

    root.append(heading("Packages"));
    const pkgs = document.createElement("table");
    pkgs.className = "pkg-table";
    (caps.packages || []).forEach((pkg) => {
      const row = document.createElement("tr");
      const name = document.createElement("td");
      name.textContent = pkg.name;
      const version = document.createElement("td");
      version.textContent = pkg.installed === false || !pkg.version ? "not installed" : pkg.version;
      version.className = pkg.installed === false ? "no" : "yes";
      row.append(name, version);
      pkgs.append(row);
    });
    root.append(pkgs);

    if (caps.features && caps.features.pipRuntime) {
      const form = document.createElement("form");
      form.className = "pip-form";
      const input = document.createElement("input");
      input.placeholder = "package==1.2.3";
      input.setAttribute("aria-label", "Package to install from PyPI");
      input.spellcheck = false;
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.textContent = "Install";
      form.append(input, submit);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        installPackage(input.value).catch(showError);
      });
      root.append(form);
      const output = document.createElement("pre");
      output.id = "pip-output";
      root.append(output);
    }

    root.append(heading("Parallel runs"));
    root.append(note("Starts two scripts, kills the one that ignores interrupts, and checks that the other finishes."));
    const probe = document.createElement("button");
    probe.type = "button";
    probe.textContent = "Test parallel kill";
    probe.addEventListener("click", () => {
      invoke("concurrencyProbe").then((result) => {
        if (result && result.started === false) banner(result.detail || "Probe already running", "error");
        else banner("Probe running…", "info");
      }).catch(showError);
    });
    root.append(probe);
    if (state.probe) {
      root.append(note((state.probe.ok ? "Last result: passed. " : "Last result: failed. ") + (state.probe.detail || "")));
    }

    if (caps.platform === "android") {
      root.append(heading("Runner mode"));
      root.append(note("Process mode kills a stuck script. Thread mode is the fallback and shares one interpreter."));
      const row = document.createElement("div");
      row.className = "toolbar";
      row.append(
        button("Use process runners", () => setMode("process").catch(showError)),
        button("Use shared interpreter", () => setMode("thread").catch(showError))
      );
      root.append(row);
      if (caps.features && caps.features.foregroundService) {
        const battery = document.createElement("button");
        battery.type = "button";
        battery.textContent = "Allow unrestricted battery use";
        battery.addEventListener("click", () => {
          invoke("requestBatteryExemption").catch(showError);
        });
        root.append(battery);
        root.append(note("Android can still stop a long scrape unless battery optimization is off for PyRunner."));
      }
    }
  }

  function heading(text) {
    const el = document.createElement("h2");
    el.textContent = text;
    return el;
  }

  function note(text) {
    const el = document.createElement("p");
    el.className = "note";
    el.textContent = text;
    return el;
  }

  async function installPackage(spec) {
    const output = $("pip-output");
    if (output) output.textContent = "Installing…";
    const result = await invoke("pipInstall", { spec: spec });
    if (output) output.textContent = result.output || "Installed " + result.spec;
    state.caps = await invoke("capabilities");
    renderDevice();
    const freshOutput = $("pip-output");
    if (freshOutput) freshOutput.textContent = result.output || "Installed " + result.spec;
  }

  async function setMode(mode) {
    await invoke("setRunnerMode", { mode: mode });
    state.caps = await invoke("capabilities");
    renderDevice();
    banner("Runner mode is now " + state.caps.concurrencyMode + ".", "info");
  }

  function mountEditor() {
    const parent = $("editor");
    editor = window.PyRunnerEditor.mount(parent, DEFAULT_SOURCE, () => markDirty());
  }

  async function boot() {
    await waitForHost();
    if (!hostReady()) {
      banner("Open this page inside the PyRunner app.", "error");
      return;
    }
    if (!window.PyRunnerEditor) {
      banner("The editor bundle is missing.", "error");
      return;
    }
    try {
      state.caps = await invoke("capabilities");
      mountEditor();
      if (state.caps.lastProbe) state.probe = state.caps.lastProbe;
      renderAgent();
      state.scripts = await invoke("listScripts");
      state.runs = await invoke("listRuns");
      updateNav();
      if (state.scripts.length) await loadScript(state.scripts[0].id);
      else fresh();
      for (const run of state.runs) {
        if (run.status === "running" || run.status === "queued" || run.status === "stopping") {
          state.activeRunId = state.activeRunId || run.id;
          ensureLog(run.id);
        }
      }
      renderRuns();
      renderLogs();
    } catch (err) {
      showError(err);
    }
  }

  document.querySelectorAll("#nav button").forEach((button) => {
    button.addEventListener("click", () => show(button.dataset.view));
  });
  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => show("editor"));
  });
  $("script-name").addEventListener("input", () => {
    state.name = $("script-name").value;
    markDirty();
  });
  $("btn-new").addEventListener("click", fresh);
  $("btn-open").addEventListener("click", () => openFile().catch(showError));
  $("btn-save").addEventListener("click", () => save().catch(showError));
  $("btn-run").addEventListener("click", () => runEditor().catch(showError));
  $("btn-stop").addEventListener("click", () => {
    if (state.activeRunId) act("stop", state.activeRunId);
  });
  $("btn-kill").addEventListener("click", () => {
    if (state.activeRunId) act("kill", state.activeRunId);
  });
  $("lib-filter").addEventListener("input", renderLibrary);
  document.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    if (!(event.ctrlKey || event.metaKey)) return;
    if (key === "s") {
      event.preventDefault();
      save().catch(showError);
    } else if (key === "enter") {
      event.preventDefault();
      runEditor().catch(showError);
    }
  });

  setInterval(() => {
    const run = state.runs.find((item) => item.id === state.activeRunId);
    if (!run) return;
    if (run.status === "running" || run.status === "queued" || run.status === "stopping") {
      refreshArtifacts(run.id).catch(() => {});
    }
  }, 400);

  boot();
})();
