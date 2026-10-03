// Each chart owns its settings. Changing a chart never sends training commands.
function createChart(containerId, historyKind, settingsContainerId = null) {
  const container = document.getElementById(containerId);
  container.innerHTML = `
    <form class="chart-settings">
      <div class="axis-row">
        <label>X Axis <select name="x"><option value="2">Step</option><option value="0">Elapsed Time</option><option value="3">Update Index</option></select></label>
        <label>Min <input name="xmin" type="number" step="any" placeholder="Auto"></label>
        <label>Max <input name="xmax" type="number" step="any" placeholder="Auto"></label>
      </div>
      <div class="axis-row">
        <label>Y Axis <select name="y" aria-label="Y Metric"></select></label>
        <label>Min <input name="ymin" type="number" step="any" placeholder="Auto"></label>
        <label>Max <input name="ymax" type="number" step="any" placeholder="Auto"></label>
      </div>
      <div class="axis-row"><button type="submit">Apply Axes</button><button type="button" class="chart-reset">Reset Axes</button></div>
      <p class="chart-error" role="status"></p>
    </form>
    <canvas class="chart-canvas" role="img"></canvas>
    <p class="chart-caption hint" role="status"></p>`;

  const form = container.querySelector("form");
  if (settingsContainerId) document.getElementById(settingsContainerId).replaceChildren(form);
  const field = name => form.elements.namedItem(name);
  const canvas = container.querySelector("canvas");
  const error = form.querySelector(".chart-error");
  const caption = container.querySelector(".chart-caption");
  let histories = {};
  let settings = {x: 2, y: null, xmin: null, xmax: null, ymin: null, ymax: null};

  function applySettings() {
    const next = {x: Number(field("x").value), y: field("y").value};
    for (const name of ["xmin", "xmax", "ymin", "ymax"]) {
      next[name] = field(name).value.trim() === "" ? null : Number(field(name).value);
      if (next[name] != null && !Number.isFinite(next[name])) {
        error.textContent = "Bounds must be finite numbers, or empty for autoscaling.";
        return;
      }
    }
    for (const axis of ["x", "y"]) {
      if (next[axis + "min"] != null && next[axis + "max"] != null && next[axis + "min"] >= next[axis + "max"]) {
        error.textContent = `${axis.toUpperCase()} Axis Min must be less than Max.`;
        return;
      }
    }
    settings = next;
    error.textContent = "";
    draw();
  }

  form.onsubmit = event => { event.preventDefault(); applySettings(); };
  field("x").onchange = () => {
    field("xmin").value = field("xmax").value = "";
    applySettings();
  };
  field("y").onchange = () => {
    field("ymin").value = field("ymax").value = "";
    applySettings();
  };
  form.querySelector(".chart-reset").onclick = () => {
    field("x").value = "2";
    field("y").value = histories.loss ? "loss" : Object.keys(histories)[0] || "";
    for (const name of ["xmin", "xmax", "ymin", "ymax"]) field(name).value = "";
    applySettings();
  };

  function numberLabel(value, interval = 1) {
    if (value === 0) return "0";
    // Precision follows the tick spacing, not the magnitude of the value.
    const digits = Math.min(12, Math.max(0, 2 - Math.floor(Math.log10(Math.abs(interval) || 1))));
    if (Math.abs(value) < 0.0001 || Math.abs(value) >= 1e9) {
      const precision = Math.min(14, Math.max(2, Math.ceil(Math.log10(Math.abs(value / interval))) + 2));
      return value.toExponential(precision).replace(/(\.\d*?[1-9])0+e|\.0+e/, "$1e");
    }
    return new Intl.NumberFormat("en-US", {maximumFractionDigits: digits}).format(value);
  }

  function bounds(values, min, max) {
    let low = min ?? values.reduce((low, value) => Math.min(low, value), Infinity);
    let high = max ?? values.reduce((high, value) => Math.max(high, value), -Infinity);
    if (low >= high) {
      const padding = Math.max(Math.abs(low), Math.abs(high)) * 0.05 || 0.001;
      if (min == null && max == null) { low -= padding; high += padding; }
      else if (min == null) low = high - padding;
      else if (max == null) high = low + padding;
    }
    return [low, high];
  }

  function draw() {
    // Draw in CSS pixels, with a backing bitmap sized for the actual display.
    // A hidden Advanced section has no size; redraw when it becomes visible.
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const pixelRatio = window.devicePixelRatio || 1;
    const bitmapWidth = Math.round(width * pixelRatio), bitmapHeight = Math.round(height * pixelRatio);
    if (canvas.width !== bitmapWidth || canvas.height !== bitmapHeight) {
      canvas.width = bitmapWidth;
      canvas.height = bitmapHeight;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const points = histories[settings.y]?.[historyKind] || [];
    const xName = {0: "Elapsed Time (s)", 2: "Step", 3: "Update Index"}[settings.x];
    canvas.setAttribute("aria-label", `${settings.y || "Metric"} chart; X Axis: ${xName}`);
    if (!points.length) { caption.textContent = "Waiting for numeric metrics."; return; }

    const [xmin, xmax] = bounds(points.map(p => p[settings.x]), settings.xmin, settings.xmax);
    const visible = points.filter(p => p[settings.x] >= xmin && p[settings.x] <= xmax);
    const yPoints = visible.length ? visible : points;
    const [ymin, ymax] = bounds(yPoints.map(p => p[1]), settings.ymin, settings.ymax);
    // Normalized coordinates are easier to inspect than a hidden chart-library configuration.
    const tickCount = width < 500 ? 2 : 4;
    const xInterval = (xmax - xmin) / tickCount, yInterval = (ymax - ymin) / 4;
    ctx.font = "13px system-ui";
    const yLabels = Array.from({length: 5}, (_, tick) => numberLabel(ymin + yInterval * tick, yInterval));
    const left = Math.min(width * 0.4, Math.max(64, ...yLabels.map(label => ctx.measureText(label).width + 16)));
    const right = width - 20, top = 32, bottom = height - 60;
    const x = p => left + (right - left) * ((p[settings.x] - xmin) / (xmax - xmin));
    const y = p => bottom - (bottom - top) * ((p[1] - ymin) / (ymax - ymin));

    ctx.lineWidth = 1;
    ctx.strokeStyle = "#e5eaf0";
    let xTicks = Array.from({length: tickCount + 1}, (_, tick) => xmin + xInterval * tick);
    if (settings.x !== 0) {
      const integerTicks = [...new Set(xTicks.map(Math.round))].filter(value => value >= xmin && value <= xmax);
      if (integerTicks.length) xTicks = integerTicks;
    }
    for (const [tick, value] of xTicks.entries()) {
      const px = left + (right - left) * ((value - xmin) / (xmax - xmin));
      ctx.beginPath(); ctx.moveTo(px, top); ctx.lineTo(px, bottom); ctx.stroke();
      ctx.fillStyle = "#59636e";
      ctx.textAlign = tick === xTicks.length - 1 ? "right" : tick === 0 ? "left" : "center";
      ctx.fillText(numberLabel(value, xInterval), px, bottom + 22);
    }
    for (let tick = 0; tick <= 4; tick++) {
      const ratio = tick / 4;
      const py = bottom - (bottom - top) * ratio;
      ctx.beginPath(); ctx.moveTo(left, py); ctx.lineTo(right, py); ctx.stroke();
      ctx.fillStyle = "#59636e";
      ctx.textAlign = "right";
      ctx.fillText(yLabels[tick], left - 10, py + 4);
    }
    ctx.textAlign = "left";
    ctx.fillText(settings.y, left, 18);
    ctx.textAlign = "center";
    ctx.fillText(xName, (left + right) / 2, height - 12);

    // Clip the line at manually chosen bounds; out-of-range values remain in the history.
    ctx.save();
    ctx.beginPath(); ctx.rect(left, top, right - left, bottom - top); ctx.clip();
    ctx.strokeStyle = "#1769e0"; ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index === 0) ctx.moveTo(x(point), y(point));
      else ctx.lineTo(x(point), y(point));
    });
    ctx.stroke();
    if (points.length === 1) {
      ctx.beginPath(); ctx.arc(x(points[0]), y(points[0]), 3, 0, Math.PI * 2);
      ctx.fillStyle = "#1769e0"; ctx.fill();
    }
    ctx.restore();
    const sampleMin = points.reduce((low, point) => Math.min(low, point[settings.x]), Infinity);
    const sampleMax = points.reduce((high, point) => Math.max(high, point[settings.x]), -Infinity);
    caption.textContent = `X: ${numberLabel(xmin, xInterval)} – ${numberLabel(xmax, xInterval)}; Y: ${numberLabel(ymin, yInterval)} – ${numberLabel(ymax, yInterval)}` +
      (visible.length ? "" : "; No samples in this X range.") +
      (historyKind === "overview" ? " | Downsampled training history." : " | Full metric history; no rolling window.") +
      ` Samples: ${numberLabel(sampleMin, xInterval)} – ${numberLabel(sampleMax, xInterval)} (${points.length} points).`;
  }

  const resizeObserver = new ResizeObserver(draw);
  resizeObserver.observe(canvas);
  return {
    destroy() { resizeObserver.disconnect(); },
    setStatus(message) { caption.textContent = message; },
    update(data) {
      histories = data;
      for (const name of Object.keys(histories)) {
        if (![...field("y").options].some(option => option.value === name)) {
          const option = document.createElement("option");
          option.value = name; option.textContent = name; field("y").append(option);
        }
      }
      if (settings.y == null && field("y").options.length) {
        settings.y = histories.loss ? "loss" : field("y").options[0].value;
        field("y").value = settings.y;
      }
      draw();
    },
  };
}
