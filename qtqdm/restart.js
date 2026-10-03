function createRestartControls(sendControl) {
  const section = document.getElementById("restart-section");
  const fields = document.getElementById("restart-fields");
  const button = document.getElementById("restart");
  let runId = null;
  let lastState = null;

  document.getElementById("restart-form").onsubmit = event => {
    event.preventDefault();
    const parameters = {};
    for (const input of fields.querySelectorAll("input")) {
      parameters[input.name] = Number(input.value);
    }
    if (confirm("Restart from step 0 with these hyperparameters? Model weights and optimizer state will be reset. Existing run files are retained.")) {
      sendControl("restart", parameters);
    }
  };

  return {
    update(data, connected, busy) {
      if (data) lastState = data;
      const restart = lastState?.restart;
      section.hidden = !restart?.enabled;
      button.hidden = !restart?.enabled;
      button.disabled = !connected || busy || !restart?.enabled || restart?.pending;
      if (restart && runId !== lastState.run_id) {
        fields.replaceChildren();
        for (const [name, value] of Object.entries(restart.parameters)) {
          const label = document.createElement("label");
          label.textContent = name;
          const input = document.createElement("input");
          input.name = name; input.type = "number"; input.required = true;
          input.step = name === "target_steps" ? "1" : "any";
          input.min = name === "target_steps" ? "1" : "0";
          input.value = value;
          label.append(input); fields.append(label);
        }
        runId = lastState.run_id;
      }
      for (const input of fields.querySelectorAll("input")) input.disabled = button.disabled;
      document.getElementById("run-id").textContent = restart ? `Run ${lastState.run_id}` : "";
    },
  };
}
