const byId = id => document.getElementById(id);
const consoleView = createConsoleView();
const resourceView = createResourceView();
let detectedPython = null;
let jobId = null;
const trainingView = createTrainingView({prefix: "training-", settingsContainer: "training-overview-settings",
  readHistory: after => request(`/training-history?job_id=${jobId}&after=${after}`),
  send: (action, value) => request("/training-control", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({job_id: jobId, action, value})})});
const recordView = createRecordView(request);
let busy = false;
let lastState = null;
let connected = false;

function message(text) { byId("message").textContent = text; }
function updateButtons() {
  byId("run").disabled = busy || !connected || lastState?.running || !byId("script").value.trim();
  byId("restart-process").disabled = busy || !connected || lastState?.restart_pending;
  byId("stop-process").disabled = busy || !connected || !lastState?.running || lastState?.state === "stopping";
  byId("force-stop").disabled = busy || !connected || !lastState?.running;
  byId("quit").disabled = !connected;
  for (const id of ["choose-script", "choose-python", "choose-directory"]) byId(id).disabled = busy || !connected;
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

function updateEnvironments(paths) {
  byId("environments").replaceChildren();
  for (const path of paths) {
    const option = document.createElement("option");
    option.value = path; byId("environments").append(option);
  }
  detectedPython = paths[0] || null;
}

async function selectPath(kind) {
  busy = true; updateButtons();
  message("Select a path in the Windows dialog.");
  const target = {script: "script", python: "python", directory: "working-directory"}[kind];
  try {
    const data = await request("/select-path", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({kind, initial: byId(target).value || byId("working-directory").value})});
    if (data.path) {
      byId(target).value = data.path;
      if (kind === "script") {
        byId("working-directory").value = data.working_directory;
        updateEnvironments(data.python_environments);
        if (detectedPython) byId("python").value = detectedPython;
      }
      message(`Selected ${data.path}`);
    } else message("Selection canceled.");
  } catch (error) { message(error.message); }
  finally { busy = false; updateButtons(); }
}

function launchConfig() {
  return {script: byId("script").value, python: byId("python").value,
          working_directory: byId("working-directory").value, arguments: byId("arguments").value};
}

async function action(route, data = {}) {
  busy = true; updateButtons();
  try {
    await request(route, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
    if (route === "/run" || route === "/restart") showTab("tab-monitor");
    message("Request accepted.");
  } catch (error) { message(error.message); }
  finally { busy = false; updateButtons(); }
}

byId("choose-script").onclick = () => selectPath("script");
byId("choose-python").onclick = () => selectPath("python");
byId("choose-directory").onclick = () => selectPath("directory");
byId("autodetect").onclick = () => { if (detectedPython) byId("python").value = detectedPython; };
for (const id of ["python", "working-directory"]) {
  byId(id).addEventListener("invalid", () => { showTab("tab-run"); });
}
byId("launch-form").onsubmit = event => { event.preventDefault(); action("/run", launchConfig()); };
byId("restart-process").onclick = () => {
  if (byId("launch-form").reportValidity() && confirm("Restart the Python process with these launcher settings? Existing logs and files are retained.")) action("/restart", launchConfig());
};
byId("stop-process").onclick = () => action("/stop");
byId("force-stop").onclick = () => {
  if (confirm("Force terminate the Python process? A new checkpoint is not guaranteed.")) action("/force-stop");
};
byId("quit").onclick = () => { if (confirm("Close tqdmboard and stop its current process?")) action("/shutdown"); };

function renderRun(data) {
  consoleView.update(data.console);
  byId("current-script").textContent = `Current Script: ${data.config?.script || "—"}`;
  byId("process-status").textContent = `Process ${data.job_id}: ${data.state}` + (data.error ? ` | ${data.error}` : "");
  byId("process-details").textContent = `PID: ${data.pid ?? "—"} | Exit code: ${data.exit_code ?? "—"}`;
  byId("training-section").hidden = !data.training.data;
  byId("training-settings").hidden = !data.training.data;
  byId("monitor-empty").hidden = !!data.training.data;
  trainingView.update(data.training.data, data.training.connected, data.training.history_error);
  if (data.training.data && data.running && !data.training.connected) {
    byId("training-state").textContent = "Training disconnected; showing last received state.";
  }
}

// Tabs only change visibility. They never navigate, reset views, or send control commands.
function showTab(id, focus = false) {
  const selected = byId(id);
  for (const tab of selected.parentElement.querySelectorAll('[role="tab"]')) {
    const active = tab === selected;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    byId(tab.getAttribute("aria-controls")).hidden = !active;
  }
  if (focus) selected.focus();
}
for (const listId of ["main-tabs", "history-tabs"]) {
  const tabs = [...byId(listId).querySelectorAll('[role="tab"]')];
  tabs.forEach((tab, index) => {
    tab.onclick = () => showTab(tab.id);
    tab.onkeydown = event => {
      let next;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault(); showTab(tabs[next].id, true);
    };
  });
}

// pagehide handles ordinary tab closure; leases cover a crashed browser.
const viewerId = crypto.randomUUID();
let viewerSequence = 0;
let viewerLeaving = false;
function viewerHeartbeat() {
  if (viewerLeaving) return;
  request("/viewer", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({id: viewerId, sequence: ++viewerSequence})}).catch(() => {});
}
function viewerClosed() {
  if (viewerLeaving) return;
  viewerLeaving = true;
  navigator.sendBeacon("/viewer", new Blob([JSON.stringify({id: viewerId, closed: true, sequence: ++viewerSequence})], {type: "application/json"}));
}
window.addEventListener("pagehide", viewerClosed);
window.addEventListener("beforeunload", viewerClosed);
window.addEventListener("pageshow", () => { viewerLeaving = false; viewerHeartbeat(); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) viewerHeartbeat(); });
viewerHeartbeat();
setInterval(viewerHeartbeat, 1000);
setInterval(recordView.refreshRecords, 5000);

async function refresh() {
  try {
    const data = await request("/state");
    connected = true; lastState = data;
    if (jobId !== data.job_id) { jobId = data.job_id; consoleView.reset(); trainingView.reset(); }
    resourceView.update(data.resources);
    renderRun(data);
  } catch (error) {
    connected = false;
    trainingView.update(null, false);
    byId("process-status").textContent = "App disconnected. Reopen tqdmboard to continue.";
  } finally {
    updateButtons();
    setTimeout(refresh, 250);
  }
}

(async () => {
  try {
    const data = await request("/config");
    const config = data.config;
    byId("script").value = config.script;
    byId("python").value = config.python;
    byId("working-directory").value = config.working_directory;
    byId("arguments").value = config.arguments;
    updateEnvironments(data.python_environments);
  } catch (error) { message(error.message); }
  recordView.refreshRecords();
  refresh();
})();
