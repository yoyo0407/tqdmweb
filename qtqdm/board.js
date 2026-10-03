const byId = id => document.getElementById(id);
const consoleView = createConsoleView();
const resourceView = createResourceView();
let detectedPython = null;
let jobId = null;
let frameUrl = null;
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

async function refresh() {
  try {
    const data = await request("/state");
    connected = true; lastState = data;
    if (jobId !== data.job_id) { jobId = data.job_id; consoleView.reset(); }
    consoleView.update(data.console);
    resourceView.update(data.resources);
    byId("process-status").textContent = `Process ${data.job_id}: ${data.state}` + (data.error ? ` | ${data.error}` : "");
    byId("process-details").textContent = `PID: ${data.pid ?? "—"} | Exit code: ${data.exit_code ?? "—"}`;
    const url = data.running ? data.dashboard_url : null;
    byId("training-section").hidden = !url;
    if (url !== frameUrl) {
      frameUrl = url;
      byId("training-frame").src = url || "about:blank";
      byId("dashboard-link").href = url || "#";
    }
  } catch (error) {
    connected = false;
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
  refresh();
})();
