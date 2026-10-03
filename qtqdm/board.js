const byId = id => document.getElementById(id);
const consoleView = createConsoleView();
const resourceView = createResourceView();
let detectedPython = null;
let jobId = null;
let archiveId = null;
const trainingView = createTrainingView({prefix: "training-", settingsContainer: "training-overview-settings",
  readHistory: after => request(archiveId ? `/record-history?id=${archiveId}&after=${after}` : `/training-history?job_id=${jobId}&after=${after}`),
  send: (action, value) => {
    if (archiveId) throw new Error("Run records are read-only.");
    return request("/training-control", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({job_id: jobId, action, value})});
  }});
let busy = false;
let lastState = null;
let connected = false;

function message(text) { byId("message").textContent = text; }
function updateButtons() {
  byId("run").disabled = busy || !connected || !!archiveId || lastState?.running || !byId("script").value.trim();
  byId("restart-process").disabled = busy || !connected || !!archiveId || lastState?.restart_pending;
  byId("stop-process").disabled = busy || !connected || !!archiveId || !lastState?.running || lastState?.state === "stopping";
  byId("force-stop").disabled = busy || !connected || !!archiveId || !lastState?.running;
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
    message("Request accepted.");
  } catch (error) { message(error.message); }
  finally { busy = false; updateButtons(); }
}

byId("choose-script").onclick = () => selectPath("script");
byId("choose-python").onclick = () => selectPath("python");
byId("choose-directory").onclick = () => selectPath("directory");
byId("autodetect").onclick = () => { if (detectedPython) byId("python").value = detectedPython; };
for (const id of ["python", "working-directory"]) {
  byId(id).addEventListener("invalid", () => { byId("advanced-section").open = true; });
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

async function refreshRecords() {
  try {
    const records = await request("/records");
    const selected = byId("record-list").value;
    byId("record-list").replaceChildren(new Option("Select a run...", ""));
    for (const record of records) {
      const name = record.config.script.split(/[\\/]/).pop();
      byId("record-list").append(new Option(`${new Date(record.started * 1000).toLocaleString()} | ${name} | ${record.state}`, record.id));
    }
    byId("record-list").value = selected;
  } catch (error) { byId("record-status").textContent = error.message; }
}

function renderRun(data, archived = false) {
  consoleView.update(data.console);
  byId("process-status").textContent = archived ? `Recorded process: ${data.state} | Exit code: ${data.exit_code ?? "—"}` :
    `Process ${data.job_id}: ${data.state}` + (data.error ? ` | ${data.error}` : "");
  byId("process-details").textContent = `PID: ${data.pid ?? "—"} | Exit code: ${data.exit_code ?? "—"}`;
  byId("training-section").hidden = !data.training.data;
  byId("training-settings").hidden = !data.training.data;
  trainingView.update(data.training.data, !archived && data.training.connected, data.training.history_error, archived);
  if (!archived && data.training.data && data.running && !data.training.connected) {
    byId("training-state").textContent = "Training disconnected; showing last received state.";
  }
}

byId("refresh-records").onclick = refreshRecords;
byId("view-record").onclick = async () => {
  const id = byId("record-list").value;
  if (!id) return;
  archiveId = id;
  updateButtons();
  trainingView.reset(); consoleView.reset();
  try {
    const record = await request(`/record?id=${id}`);
    if (archiveId !== id) return;
    renderRun(record, true);
    byId("record-status").textContent = `Read-only record; last captured training result | Started: ${new Date(record.started * 1000).toLocaleString()} | Ended: ${record.ended ? new Date(record.ended * 1000).toLocaleString() : "No exit recorded"}`;
    byId("record-config").hidden = false;
    byId("record-config").textContent = `Python: ${record.config.python}\nScript: ${record.config.script}\nArguments: ${record.config.arguments}\nWorking Directory: ${record.config.working_directory}`;
  } catch (error) { byId("record-status").textContent = error.message; }
};
byId("live-view").onclick = () => {
  archiveId = null; jobId = null;
  trainingView.reset(); consoleView.reset();
  byId("record-status").textContent = "Live View";
  byId("record-config").hidden = true;
  updateButtons();
};

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
setInterval(refreshRecords, 5000);

async function refresh() {
  try {
    const data = await request("/state");
    connected = true; lastState = data;
    if (!archiveId && jobId !== data.job_id) { jobId = data.job_id; consoleView.reset(); trainingView.reset(); }
    resourceView.update(data.resources);
    if (!archiveId) renderRun(data);
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
  refreshRecords();
  refresh();
})();
