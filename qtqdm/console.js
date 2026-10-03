function createConsoleView() {
  const output = document.getElementById("console-output");
  const follow = document.getElementById("console-follow");
  const status = document.getElementById("console-status");
  let version = -1;

  follow.onchange = () => {
    if (follow.checked) output.scrollTop = output.scrollHeight;
  };
  document.getElementById("console-copy").onclick = async () => {
    try {
      await navigator.clipboard.writeText(output.textContent);
      document.getElementById("console-copy-status").textContent = "Copied visible output.";
    } catch (error) {
      document.getElementById("console-copy-status").textContent = `Copy failed: ${error.message}`;
    }
  };

  return {
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
