// Read-only record viewer. It never changes the live monitor or sends process commands.
function createRecordView(request) {
  const byId = id => document.getElementById("record-" + id);
  const consoleView = createConsoleView({prefix: "record-"});
  let generation = 0;
  let listSignature = null;
  let overviewChart = null;
  let fullChart = null;
  let displayedId = null;
  let historyCursor = 0;
  let histories = {};
  let refreshing = false;
  let listGeneration = 0;
  let displayedVersion = null;

  const recordVersion = record => JSON.stringify([record.id, record.state, record.ended, record.exit_code,
    record.training_state ?? record.training?.data?.state ?? null]);

  function renderValues(element, values) {
    element.replaceChildren();
    for (const [name, value] of Object.entries(values)) {
      const box = document.createElement("div");
      const label = document.createElement("dt"), text = document.createElement("dd");
      label.textContent = name; text.textContent = value ?? "—";
      box.append(label, text); element.append(box);
    }
  }

  async function refreshRecords(refreshDisplayed = false) {
    const currentList = ++listGeneration;
    try {
      const records = await request("/records");
      if (currentList !== listGeneration) {
        if (refreshDisplayed && displayedId) await viewRecord(displayedId);
        return;
      }
      const signature = JSON.stringify(records.map(record => [record.id, record.state, record.training_state, record.ended, record.exit_code]));
      if (signature !== listSignature) {
        listSignature = signature;
        const selected = byId("list").value;
        byId("list").replaceChildren(new Option("Select a run...", ""));
        for (const record of records) {
          const name = record.config.script.split(/[\\/]/).pop();
          byId("list").append(new Option(`${new Date(record.started * 1000).toLocaleString()} | ${name} | Training: ${record.training_state || "—"} | Process: ${record.state}`, record.id));
        }
        byId("list").value = selected;
      }
      const displayed = records.find(record => record.id === displayedId);
      if (displayedId && (refreshDisplayed || (displayedVersion && displayed && recordVersion(displayed) !== displayedVersion))) {
        await viewRecord(displayedId);
      }
    } catch (error) { byId("status").textContent = `Record list unavailable: ${error.message}`; }
  }

  async function viewRecord(id) {
    if (!id) return;
    const changed = displayedId !== id;
    displayedId = id;
    const current = ++generation;
    if (changed) byId("content").hidden = true;
    byId("status").textContent = "Loading recorded run. Current training continues in Monitor.";
    if (changed) {
      displayedVersion = null;
      overviewChart?.destroy(); fullChart?.destroy();
      overviewChart = createChart("record-chart-overview", "overview");
      fullChart = createChart("record-chart-full", "full");
      historyCursor = 0;
      histories = {};
      consoleView.reset();
    }
    try {
      const record = await request(`/record?id=${encodeURIComponent(id)}`);
      if (current !== generation) return;
      const data = record.training.data;
      displayedVersion = recordVersion(record);
      byId("config").textContent = `Python: ${record.config.python}\nScript: ${record.config.script}\nArguments: ${record.config.arguments}\nWorking Directory: ${record.config.working_directory}`;
      const exitCode = record.exit_code ?? (record.state === "running" ? "Pending (process running)" :
        record.state === "detached" ? "Pending (process detached)" : "Unknown (exit not recorded)");
      renderValues(byId("summary"), {"Process State": record.state, "Exit Code": exitCode,
        "Started": new Date(record.started * 1000).toLocaleString(),
        "Ended": record.ended ? new Date(record.ended * 1000).toLocaleString() : "No exit recorded",
        "Training State (last captured)": data?.state, "Completed": data ? `${data.completed} / ${data.total ?? "unknown"}` : null,
        "Elapsed": data ? `${Math.round(data.elapsed)} s` : null,
        "Checkpoint": data?.control?.last_checkpoint});
      renderValues(byId("metrics"), data?.metrics || {});
      consoleView.update(record.console);
      overviewChart.update(data?.charts || {});
      byId("content").hidden = false;
      byId("status").textContent = "Recorded Run · Read-only. Current training continues in Monitor.";
      byId("chart-status").textContent = data ? "Loading saved metric history..." : "This run has no recorded Qtqdm metrics.";
      // Capture the record ID for this request. A later selection cannot redirect these pages.
      while (historyCursor < (data?.history_updates || 0)) {
        const page = await request(`/record-history?id=${encodeURIComponent(id)}&after=${historyCursor}`);
        if (current !== generation) return;
        if (page.next_update <= historyCursor) throw new Error("History cursor did not advance");
        for (const [name, points] of Object.entries(page.charts)) {
          histories[name] ??= {full: []};
          histories[name].full.push(...points);
        }
        historyCursor = page.next_update;
        fullChart.update(histories);
      }
      fullChart.update(histories);
      if (data) byId("chart-status").textContent = "Saved raw metrics; chart settings only affect this record view.";
    } catch (error) {
      if (current === generation) byId("status").textContent = `Record loading failed: ${error.message}. Select View Record to retry.`;
    }
  }

  document.getElementById("view-record").onclick = () => viewRecord(byId("list").value);
  document.getElementById("refresh-records").onclick = async () => {
    if (refreshing) return;
    refreshing = true;
    document.getElementById("refresh-records").disabled = true;
    try { await refreshRecords(true); }
    finally { refreshing = false; document.getElementById("refresh-records").disabled = false; }
  };
  return {refreshRecords};
}
