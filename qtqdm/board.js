const byId = id => document.getElementById(id);
const consoleView = createConsoleView();
let currentFolder = null;
let detectedPython = null;
let jobId = null;
let frameUrl = null;
let busy = false;
let lastState = null;
let connected = false;

function message(text) { byId("message").textContent = text; }
function updateButtons() {
  byId("run").disabled = busy || !connected || lastState?.running;
  byId("restart-process").disabled = busy || !connected || lastState?.restart_pending;
  byId("stop-process").disabled = busy || !connected || !lastState?.running || lastState?.state === "stopping";
  byId("force-stop").disabled = busy || !connected || !lastState?.running;
  byId("quit").disabled = busy || !connected;
}

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

async function browse(path) {
  try {
    const data = await request(`/browse?path=${encodeURIComponent(path)}`);
    currentFolder = data;
    byId("directory").value = data.path;
    byId("files").replaceChildren();
    for (const entry of data.entries) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${entry.directory ? "[Directory]" : "[Python]"} ${entry.name}`;
      button.onclick = () => {
        if (entry.directory) browse(entry.path);
        else {
          byId("script").value = entry.path;
          byId("working-directory").value = data.path;
          if (detectedPython) byId("python").value = detectedPython;
          message(`Selected ${entry.name}`);
        }
      };
      item.append(button); byId("files").append(item);
    }
    byId("environments").replaceChildren();
    for (const path of data.python_environments) {
      const option = document.createElement("option");
      option.value = path; byId("environments").append(option);
    }
    detectedPython = data.python_environments[0] || null;
  } catch (error) { message(error.message); }
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

byId("browse-form").onsubmit = event => { event.preventDefault(); browse(byId("directory").value); };
byId("parent").onclick = () => { if (currentFolder) browse(currentFolder.parent); };
byId("autodetect").onclick = () => { if (detectedPython) byId("python").value = detectedPython; };
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
    byId("process-status").textContent = `Process ${data.job_id} | ${data.state} | PID: ${data.pid ?? "—"} | Exit code: ${data.exit_code ?? "—"}` + (data.error ? ` | ${data.error}` : "");
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
    await browse(data.directory);
  } catch (error) { message(error.message); }
  refresh();
})();
