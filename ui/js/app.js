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
    if (view === "library") hydrateLibrary().catch(showError);
    if (view === "device") renderDevice();
    if (view === "runs") renderRuns();
    if (view === "agent") renderAgent().catch(showError);
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

  function runClock(run) {
    const start = run.startedAt || run.createdAt;
    if (!start) return "";
    const end = run.finishedAt || Date.now();
    const sec = Math.max(0, Math.round((end - start) / 1000));
    if (sec < 60) return sec + "s";
    return Math.floor(sec / 60) + "m " + (sec % 60) + "s";
  }

  function renderRuns() {
    const list = $("run-list");
    const signature = state.runs.map((run) => run.id + ":" + run.status + ":" + (run.id === state.activeRunId)).join("|");
    if (list.dataset.signature === signature) {
      state.runs.forEach((run) => {
        const clock = list.querySelector('[data-clock="' + run.id + '"]');
        if (clock) clock.textContent = runClock(run);
      });
      return;
    }
    list.dataset.signature = signature;
    list.textContent = "";
    if (!state.runs.length) {
      const empty = document.createElement("p");
      empty.className = "note";
      empty.textContent = "No runs yet. Press Run in the editor. The log for the one you select is shown beside this list.";
      list.append(empty);
      return;
    }
    state.runs.forEach((run) => {
      const card = document.createElement("article");
      card.className = "run-card" + (run.id === state.activeRunId ? " selected" : "");
      const top = document.createElement("div");
      top.className = "top";
      const name = document.createElement("button");
      name.type = "button";
      name.className = "name";
      name.textContent = run.name;
      name.addEventListener("click", () => selectRun(run.id));
      top.append(name, pill(run.status));
      const meta = document.createElement("div");
      meta.className = "run-time";
      meta.dataset.clock = run.id;
      meta.textContent = runClock(run);
      const actions = document.createElement("div");
      actions.className = "actions";
      const stop = button("Stop", () => act("stop", run.id));
      stop.disabled = run.status !== "running" && run.status !== "stopping";
      const kill = button("Kill", () => act("kill", run.id));
      kill.disabled = run.status !== "running" && run.status !== "stopping" && run.status !== "queued";
      const output = button("Output", () => {
        selectRun(run.id);
        show("output");
      });
      actions.append(stop, kill, output);
      card.append(top, meta, actions);
      list.append(card);
    });
  }

  function selectRun(runId) {
    state.activeRunId = runId;
    ensureLog(runId);
    renderRuns();
    renderLogs();
    refreshArtifacts(runId).catch(() => {});
  }

  async function act(method, runId) {
    try {
      const run = await invoke(method, { runId: runId });
      onStatus(run);
    } catch (err) {
      showError(err);
    }
  }

  async function hydrateLibrary() {
    for (const script of state.scripts) {
      if (script.source != null) continue;
      const full = await invoke("getScript", { id: script.id });
      script.source = full.source || "";
    }
    renderLibrary();
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
    const canInstall = Boolean(state.caps && state.caps.features && state.caps.features.pipRuntime);
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
      const pkgs = document.createElement("div");
      pkgs.className = "lib-pkgs";
      const needed = window.PyRunnerGuide ? window.PyRunnerGuide.scriptPackages(script.source || "") : [];
      if (!needed.length && script.source != null) {
        const none = document.createElement("span");
        none.className = "pkg-chip";
        none.textContent = "No extra packages";
        pkgs.append(none);
      }
      needed.forEach((pkg) => {
        const ready = packageReady(pkg);
        if (ready) {
          const chip = document.createElement("span");
          chip.className = "pkg-chip yes";
          chip.textContent = pkg + " ready";
          pkgs.append(chip);
        } else if (canInstall) {
          pkgs.append(button("Install " + pkg, () => installPackage(pkg).catch(showError)));
        } else {
          const chip = document.createElement("span");
          chip.className = "pkg-chip no";
          chip.textContent = pkg + " is not in this app";
          pkgs.append(chip);
        }
      });
      row.append(name, open, run, rename, remove, pkgs);
      list.append(row);
    });
  }

  function packageReady(name) {
    const rows = (state.caps && state.caps.packages) || [];
    return rows.some((pkg) => String(pkg.name || "").toLowerCase().replace(/_/g, "-") === name && pkg.installed !== false);
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
    const previous = {};
    state.scripts.forEach((script) => {
      if (script.source != null) previous[script.id] = script.source;
    });
    state.scripts = await invoke("listScripts");
    state.scripts.forEach((script) => {
      if (previous[script.id] != null) script.source = previous[script.id];
    });
    if (state.view === "library") await hydrateLibrary();
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
    const current = editor.getValue();
    state.scripts.forEach((script) => {
      if (script.id === saved.id) script.source = current;
    });
    if (state.view === "library") renderLibrary();
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

  async function renderAgent() {
    const root = $("agent");
    const guide = window.PyRunnerGuide;
    let remote = { ollama: false, selected: "builtin", installed: [], pulling: null };
    try {
      const status = await invoke("agentStatus");
      if (status && typeof status === "object") remote = status;
    } catch (err) {
      remote.error = err.message || String(err);
    }
    const selected = remote.selected || "builtin";
    state.agentModel = selected;
    root.textContent = "";
    root.append(heading("How to ask"));
    root.append(note("Type a question below. The built-in helper answers on this device. On Windows, download a model first if you want that model to answer. Switch models in the list. Delete removes a download from this PC."));
    root.append(heading("How to scrape"));
    root.append(note("Insert scraper, change the URL, then press Run. Output shows printed links and saved images while the script runs. requests and beautifulsoup4 are already included. Missing packages are listed in Library."));
    const insert = button("Insert scraper", () => {
      if (!editor || !guide) return;
      setEditorValue(guide.SCRAPE);
      setName("scrape.py");
      state.dirty = true;
      showDirty();
      show("editor");
    });
    root.append(insert);

    root.append(heading("Models"));
    const android = state.caps && state.caps.platform === "android";
    if (android) {
      root.append(note("This phone uses the built-in helper. Qwen2.5-Coder downloads in the Windows app, through Ollama on 127.0.0.1."));
    } else if (!remote.ollama) {
      root.append(note("Ollama is not running at 127.0.0.1:11434. Install it on this PC, start it, then come back to download a model. The built-in helper still works."));
    }
    (guide ? guide.MODELS : []).forEach((model) => {
      const card = document.createElement("article");
      card.className = "run-card" + (model.id === selected ? " selected" : "");
      const top = document.createElement("div");
      top.className = "top";
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = model.label + " · " + model.size;
      top.append(name);
      card.append(top, note(model.detail));
      const actions = document.createElement("div");
      actions.className = "actions";
      const use = button(model.id === selected ? "Selected" : "Use", () => chooseModel(model.id).catch(showError));
      use.disabled = model.id === selected || (android && model.id !== "builtin");
      actions.append(use);
      const installed = model.id === "builtin" || (remote.installed || []).indexOf(model.id) !== -1;
      if (model.id !== "builtin") {
        const download = button(installed ? "Downloaded" : "Download", () => pullModel(model.id).catch(showError));
        download.disabled = installed || android;
        const remove = button("Delete", () => deleteModel(model.id).catch(showError));
        remove.disabled = !installed || android;
        actions.append(download, remove);
      }
      card.append(actions);
      root.append(card);
    });
    if (remote.pulling && remote.pulling.status) {
      root.append(note("Download " + remote.pulling.id + ": " + remote.pulling.status + (remote.pulling.error ? " " + remote.pulling.error : "")));
    }

    root.append(heading("Ask"));
    const form = document.createElement("form");
    form.className = "pip-form";
    const input = document.createElement("input");
    input.id = "agent-prompt";
    input.placeholder = "How do I scrape the links on a page?";
    input.setAttribute("aria-label", "Question for the agent");
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "primary";
    submit.textContent = "Ask";
    form.append(input, submit);
    const reply = document.createElement("pre");
    reply.id = "agent-reply";
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      askAgent(input.value, reply).catch(showError);
    });
    root.append(form, reply);
    if (state.agentReply) reply.textContent = state.agentReply;
    if (remote.pulling && remote.pulling.status === "running") {
      setTimeout(() => {
        if (state.view === "agent") renderAgent().catch(() => {});
      }, 1000);
    }
  }

  async function chooseModel(id) {
    if (id === "builtin" || (state.caps && state.caps.platform === "android")) {
      state.agentModel = "builtin";
      if (state.caps && state.caps.platform !== "android") await invoke("agentSelect", { id: id });
      await renderAgent();
      return;
    }
    await invoke("agentSelect", { id: id });
    await renderAgent();
  }

  async function pullModel(id) {
    await invoke("agentPull", { id: id });
    await renderAgent();
  }

  async function deleteModel(id) {
    await invoke("agentDelete", { id: id });
    await renderAgent();
  }

  async function askAgent(prompt, reply) {
    const guide = window.PyRunnerGuide;
    const model = state.agentModel || "builtin";
    reply.textContent = "Asking…";
    let result;
    if (model === "builtin" || !guide) {
      result = guide.builtinReply(prompt);
    } else {
      const remote = await invoke("agentAsk", {
        id: model,
        prompt: prompt,
        script: editor ? editor.getValue() : "",
      });
      result = { text: remote.text || "", code: pythonBlock(remote.text || "") };
    }
    state.agentReply = result.text || "";
    reply.textContent = state.agentReply || "No reply.";
    $("agent").querySelectorAll(".use-code").forEach((el) => el.remove());
    if (result.code) {
      const use = button("Use this code", () => {
        setEditorValue(result.code);
        state.dirty = true;
        showDirty();
        show("editor");
      });
      use.className = "use-code";
      reply.insertAdjacentElement("afterend", use);
    }
  }

  function pythonBlock(text) {
    const match = /```python\n([\s\S]*?)```/.exec(text || "") || /```\n([\s\S]*?)```/.exec(text || "");
    return match ? match[1].replace(/\s+$/, "") + "\n" : "";
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
    const libraryOutput = $("lib-pip");
    if (output) output.textContent = "Installing…";
    if (libraryOutput) {
      libraryOutput.hidden = false;
      libraryOutput.textContent = "Installing " + spec + "…";
    }
    const result = await invoke("pipInstall", { spec: spec });
    if (output) output.textContent = result.output || "Installed " + result.spec;
    state.caps = await invoke("capabilities");
    renderDevice();
    const freshOutput = $("pip-output");
    if (freshOutput) freshOutput.textContent = result.output || "Installed " + result.spec;
    const libraryOutputDone = $("lib-pip");
    if (libraryOutputDone) {
      libraryOutputDone.hidden = false;
      libraryOutputDone.textContent = result.output || "Installed " + result.spec;
    }
    await hydrateLibrary();
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
    if (state.view === "runs") renderRuns();
    if (!run) return;
    if (run.status === "running" || run.status === "queued" || run.status === "stopping") {
      refreshArtifacts(run.id).catch(() => {});
    }
  }, 400);

  boot();
})();
