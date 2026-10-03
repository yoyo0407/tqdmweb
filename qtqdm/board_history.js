// Read-only record viewer. It never changes the live monitor or sends process commands.
function createRecordView(request) {
  const byId = id => document.getElementById("record-" + id);
  const consoleView = createConsoleView({prefix: "record-"});
  let generation = 0;
  let listSignature = null;
  let overviewChart = null;
  let fullChart = null;

  function renderValues(element, values) {
    element.replaceChildren();
    for (const [name, value] of Object.entries(values)) {
      const box = document.createElement("div");
      const label = document.createElement("dt"), text = document.createElement("dd");
      label.textContent = name; text.textContent = value ?? "—";
      box.append(label, text); element.append(box);
    }
  }

  async function refreshRecords() {
    try {
      const records = await request("/records");
      const signature = JSON.stringify(records.map(record => [record.id, record.state]));
      if (signature === listSignature) return;
      listSignature = signature;
      const selected = byId("list").value;
      byId("list").replaceChildren(new Option("Select a run...", ""));
      for (const record of records) {
        const name = record.config.script.split(/[\\/]/).pop();
        byId("list").append(new Option(`${new Date(record.started * 1000).toLocaleString()} | ${name} | ${record.state}`, record.id));
      }
      byId("list").value = selected;
    } catch (error) { byId("status").textContent = `Record list unavailable: ${error.message}`; }
  }

  async function viewRecord(id) {
    if (!id) return;
    const current = ++generation;
    byId("content").hidden = true;
    byId("status").textContent = "Loading recorded run. Current training continues in Monitor.";
    overviewChart?.destroy(); fullChart?.destroy();
    consoleView.reset();
    try {
      const record = await request(`/record?id=${encodeURIComponent(id)}`);
      if (current !== generation) return;
      const data = record.training.data;
      byId("config").textContent = `Python: ${record.config.python}\nScript: ${record.config.script}\nArguments: ${record.config.arguments}\nWorking Directory: ${record.config.working_directory}`;
      renderValues(byId("summary"), {"Process State": record.state, "Exit Code": record.exit_code,
        "Started": new Date(record.started * 1000).toLocaleString(),
        "Ended": record.ended ? new Date(record.ended * 1000).toLocaleString() : "No exit recorded",
        "Training State": data?.state, "Completed": data ? `${data.completed} / ${data.total ?? "unknown"}` : null,
        "Elapsed": data ? `${Math.round(data.elapsed)} s` : null,
        "Checkpoint": data?.control?.last_checkpoint});
      renderValues(byId("metrics"), data?.metrics || {});
      consoleView.update(record.console);
      overviewChart = createChart("record-chart-overview", "overview");
      fullChart = createChart("record-chart-full", "full");
      overviewChart.update(data?.charts || {});
      byId("content").hidden = false;
      byId("status").textContent = "Recorded Run · Read-only. Current training continues in Monitor.";
      byId("chart-status").textContent = data ? "Loading saved metric history..." : "This run has no recorded Qtqdm metrics.";
      // Capture the record ID for this request. A later selection cannot redirect these pages.
      const histories = {};
      let cursor = 0;
      while (cursor < (data?.history_updates || 0)) {
        const page = await request(`/record-history?id=${encodeURIComponent(id)}&after=${cursor}`);
        if (current !== generation) return;
        if (page.next_update <= cursor) throw new Error("History cursor did not advance");
        for (const [name, points] of Object.entries(page.charts)) {
          histories[name] ??= {full: []};
          histories[name].full.push(...points);
        }
        cursor = page.next_update;
        fullChart.update(histories);
      }
      if (data) byId("chart-status").textContent = "Saved raw metrics; chart settings only affect this record view.";
    } catch (error) {
      if (current === generation) byId("status").textContent = `Record loading failed: ${error.message}. Select View Record to retry.`;
    }
  }

  document.getElementById("view-record").onclick = () => viewRecord(byId("list").value);
  document.getElementById("refresh-records").onclick = refreshRecords;
  return {refreshRecords};
}
