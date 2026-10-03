// Shared rendering behavior; each page owns its markup and layout.
function createTrainingView({prefix = "", send, settingsContainer = null, readHistory}) {
  const byId = id => document.getElementById(prefix + id);
  const seconds = value => value == null ? "—" : `${Math.round(value)} s`;
  let generation = 0;
  let errorShown = false;
  let controlState = null;
  let commandBusy = false;
  let connected = false;
  let rateInitialized = false;
  let pendingCommand = null;
  let overviewChart;
  let recentChart;
  let fullHistories = {};
  let historyCursor = 0;
  let historyBusy = false;

  async function loadHistory(target) {
    if (!readHistory || historyBusy || historyCursor >= target) return;
    const requestGeneration = generation;
    historyBusy = true;
    try {
      while (historyCursor < target) {
        const page = await readHistory(historyCursor);
        if (requestGeneration !== generation) return;
        if (page.next_update <= historyCursor) break;
        for (const [name, points] of Object.entries(page.charts)) {
          fullHistories[name] ??= {full: []};
          fullHistories[name].full.push(...points);
        }
        historyCursor = page.next_update;
        recentChart.update(fullHistories);
      }
    } catch (error) {
      if (requestGeneration === generation) recentChart.setStatus(`History loading interrupted: ${error.message}. Retrying...`);
    } finally {
      if (requestGeneration === generation) historyBusy = false;
    }
  }

  function updateControls() {
    const ended = !connected || !controlState || controlState.finished || controlState.stop_requested;
    byId("pause").disabled = ended || commandBusy;
    byId("stop").disabled = ended || commandBusy;
    byId("lr-apply").disabled = ended || commandBusy;
    byId("lr-input").disabled = ended;
    byId("save").hidden = !controlState?.capabilities.save_checkpoint;
    byId("save").disabled = ended || commandBusy || controlState?.save_requested || controlState?.saving;
    byId("save-form").hidden = !controlState?.capabilities.save_checkpoint;
    byId("save-step").disabled = ended;
    byId("save-schedule").disabled = ended || commandBusy;
    byId("save-cancel").hidden = controlState?.save_at_step == null;
    byId("save-cancel").disabled = ended || commandBusy;
    byId("pause").textContent = controlState?.pause_requested ? "Resume" : "Pause";
  }

  async function sendControl(action, value) {
    const requestGeneration = generation;
    commandBusy = true;
    updateControls();
    try {
      const result = await send(action, value);
      if (requestGeneration !== generation) return;
      pendingCommand = {action, value, saveRequestId: result?.save_request_id};
      byId("control-message").textContent = "Command accepted; pending step boundary.";
    } catch (error) {
      if (requestGeneration === generation) byId("control-message").textContent = error.message;
    } finally {
      if (requestGeneration === generation) { commandBusy = false; updateControls(); }
    }
  }

  byId("pause").onclick = () => sendControl(controlState.pause_requested ? "resume" : "pause");
  byId("save").onclick = () => sendControl("save");
  byId("save-cancel").onclick = () => sendControl("cancel_save");
  byId("save-form").onsubmit = event => {
    event.preventDefault();
    const step = Number(byId("save-step").value);
    if (!Number.isInteger(step) || step <= controlState.completed ||
        (controlState.total != null && step > controlState.total)) {
      byId("control-message").textContent = "Checkpoint step must be a future integer within the training target.";
      return;
    }
    sendControl("schedule_save", step);
  };
  byId("stop").onclick = () => {
    if (confirm("Stop this run? CSV records are retained. Resume training requires a new run.")) sendControl("stop");
  };
  byId("lr-form").onsubmit = event => {
    event.preventDefault();
    const value = Number(byId("lr-input").value);
    if (!Number.isFinite(value) || value <= 0) {
      byId("control-message").textContent = "Learning rate must be finite and greater than zero.";
      return;
    }
    sendControl("learning_rate", value);
  };
  updateControls();

  function update(data, online, historyError = null, archived = false) {
    connected = online;
    if (!data) { updateControls(); return; }
    controlState = data.control;
    updateControls();
    if (pendingCommand) {
      const done = controlState.finished ||
        (pendingCommand.action === "pause" && controlState.paused) ||
        (pendingCommand.action === "resume" && !controlState.pause_requested && !controlState.paused) ||
        (pendingCommand.action === "learning_rate" && controlState.pending_learning_rate == null && (controlState.learning_rate === pendingCommand.value || controlState.learning_rate_error)) ||
        (pendingCommand.action === "save" && pendingCommand.saveRequestId != null && controlState.save_completed_id >= pendingCommand.saveRequestId) ||
        (pendingCommand.action === "schedule_save" && (controlState.save_at_step === pendingCommand.value || controlState.completed >= pendingCommand.value)) ||
        (pendingCommand.action === "cancel_save" && controlState.save_at_step == null);
      if (done) {
        const messages = {pause: "Paused.", resume: "Resumed.", stop: "Stopped.", learning_rate: controlState.learning_rate_error ? `Learning rate failed: ${controlState.learning_rate_error}` : "Learning rate applied.", save: controlState.save_error ? "Checkpoint failed." : "Checkpoint saved.", schedule_save: "Checkpoint scheduled.", cancel_save: "Checkpoint schedule canceled."};
        const saveCompleted = pendingCommand.saveRequestId != null && controlState.save_completed_id >= pendingCommand.saveRequestId;
        byId("control-message").textContent = pendingCommand.action === "save" ?
          (saveCompleted ? messages.save : "Run ended before checkpoint completed.") : controlState.finished ? "Run ended." : messages[pendingCommand.action];
        pendingCommand = null;
      }
    }
    byId("description").textContent = data.description || "Progress";
    const states = {waiting: "Pending", running: "Running", pause_requested: "Pause pending", paused: "Paused", saving: "Saving checkpoint", stop_requested: "Stop pending", stopped: "Stopped", finished: "Completed", failed: "Failed"};
    byId("state").textContent = states[data.state] || data.state;
    const caps = data.control.capabilities;
    byId("capabilities").textContent = Object.entries(caps).map(([name, enabled]) => `${name}: ${enabled ? "available" : "unavailable"}`).join(" | ");
    byId("lr-form").hidden = !controlState.capabilities.learning_rate;
    if (data.control.learning_rate != null) {
      if (!rateInitialized) {
        byId("lr-input").value = data.control.learning_rate;
        rateInitialized = true;
      }
      byId("lr-current").textContent = `Current: ${data.control.learning_rate}` +
        (data.control.pending_learning_rate == null ? "" : `; Pending: ${data.control.pending_learning_rate}`) +
        (data.control.learning_rate_error ? `; Error: ${data.control.learning_rate_error}` : "");
    }
    byId("state").classList.toggle("failed", data.state === "failed");
    byId("save-status").textContent = data.control.saving ? "Writing checkpoint..." :
      data.control.save_requested ? "Checkpoint pending step boundary." :
      data.control.save_error ? `Checkpoint failed: ${data.control.save_error}` :
      data.control.last_checkpoint ? `Checkpoint saved: ${data.control.last_checkpoint}` : "";
    byId("save-schedule-status").textContent = data.control.save_at_step == null ? "" : `Checkpoint scheduled after step ${data.control.save_at_step}.`;
    byId("started").textContent = data.total == null
      ? `${data.started} / unknown`
      : `${data.started} / ${data.total}`;
    byId("completed").textContent = data.completed;
    byId("rate").textContent = data.rate ? `${data.rate.toFixed(1)} items/s` : "—";
    byId("elapsed").textContent = seconds(data.elapsed);
    byId("remaining").textContent = data.state === "paused" ? "Paused" : seconds(data.remaining);
    const bar = byId("bar");
    if (data.total == null) bar.removeAttribute("value");
    else { bar.max = Math.max(data.total, 1); bar.value = data.started; }
    const metrics = byId("metrics");
    metrics.replaceChildren();
    for (const [name, value] of Object.entries(data.metrics)) {
      const box = document.createElement("div");
      const label = document.createElement("dt");
      const number = document.createElement("dd");
      label.textContent = name;
      number.textContent = value;
      box.append(label, number);
      metrics.append(box);
    }
    byId("metrics-section").hidden = Object.keys(data.metrics).length === 0;
    byId("loss-section").hidden = Object.keys(data.charts).length === 0;
    overviewChart.update(data.charts);
    recentChart.update(fullHistories);
    loadHistory(data.history_updates || 0);
    if (historyError) recentChart.setStatus(`History temporarily unavailable: ${historyError}. Retrying...`);
    if (data.state === "failed" && !errorShown && !archived) {
      errorShown = true;
      alert(data.error || "The task failed.");
    }
  }
  function reset() {
    generation++;
    commandBusy = false;
    errorShown = rateInitialized = false;
    controlState = pendingCommand = null;
    connected = false;
    fullHistories = {};
    historyCursor = 0;
    historyBusy = false;
    for (const id of ["control-message", "lr-current", "save-status", "save-schedule-status"]) byId(id).textContent = "";
    byId("lr-input").value = byId("save-step").value = "";
    overviewChart?.destroy();
    recentChart?.destroy();
    overviewChart = createChart(prefix + "chart-overview", "overview", settingsContainer);
    recentChart = createChart(prefix + "chart-recent", "full");
    updateControls();
  }
  reset();
  return {update, reset};
}
