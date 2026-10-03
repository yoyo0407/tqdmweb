function createConsoleView({prefix = ""} = {}) {
  const byId = id => document.getElementById(prefix + id);
  const output = byId("console-output");
  const follow = byId("console-follow");
  const status = byId("console-status");
  let version = -1;

  follow.onchange = () => {
    if (follow.checked) output.scrollTop = output.scrollHeight;
  };
  new ResizeObserver(() => {
    if (follow.checked) output.scrollTop = output.scrollHeight;
  }).observe(output);
  byId("console-copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText(output.textContent);
      byId("console-copy-status").textContent = "Copied visible output.";
    } catch (error) {
      byId("console-copy-status").textContent = `Copy failed: ${error.message}`;
    }
  };

  return {
    reset() {
      version = -1;
      byId("console-copy-status").textContent = "";
      output.textContent = "Waiting for stdout / stderr...";
      status.textContent = "";
    },
    update(data) {
      if (version === data.version) return;
      const top = output.scrollTop, left = output.scrollLeft;
      output.textContent = data.text || "Waiting for stdout / stderr...";
      version = data.version;
      output.scrollTop = follow.checked ? output.scrollHeight : top;
      output.scrollLeft = left;
      status.textContent = (data.trimmed_chars ? "Showing the latest 65,536 characters. " : "") +
        (data.error ? `Log write failed: ${data.error}` : data.path ? `Full log: ${data.path}` : "No log file configured.");
    },
  };
}
