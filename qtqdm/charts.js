// Each chart owns its settings. Changing a chart never sends training commands.
function createChart(containerId, historyKind) {
  const container = document.getElementById(containerId);
  container.innerHTML = `
    <form class="chart-settings">
      <div class="axis-row">
        <label>X 軸 <select name="x"><option value="2">步數</option><option value="0">經過秒數</option><option value="3">更新次數</option></select></label>
        <label>下限 <input name="xmin" type="number" step="any" placeholder="自動"></label>
        <label>上限 <input name="xmax" type="number" step="any" placeholder="自動"></label>
      </div>
      <div class="axis-row">
        <label>Y 軸 <select name="y" aria-label="Y 軸指標"></select></label>
        <label>下限 <input name="ymin" type="number" step="any" placeholder="自動"></label>
        <label>上限 <input name="ymax" type="number" step="any" placeholder="自動"></label>
      </div>
      <div class="axis-row"><button type="submit">套用座標軸</button><button type="button" class="chart-reset">恢復預設</button></div>
      <p class="chart-error" role="status"></p>
    </form>
    <canvas width="640" height="280" role="img"></canvas>
    <p class="chart-caption hint" role="status"></p>`;

  const form = container.querySelector("form");
  const field = name => form.elements.namedItem(name);
  const canvas = container.querySelector("canvas");
  const error = container.querySelector(".chart-error");
  const caption = container.querySelector(".chart-caption");
  let histories = {};
  let settings = {x: 2, y: null, xmin: null, xmax: null, ymin: null, ymax: null};

  function applySettings() {
    const next = {x: Number(field("x").value), y: field("y").value};
    for (const name of ["xmin", "xmax", "ymin", "ymax"]) {
      next[name] = field(name).value.trim() === "" ? null : Number(field(name).value);
      if (next[name] != null && !Number.isFinite(next[name])) {
        error.textContent = "上下限必須是有限數值，或留空使用自動縮放。";
        return;
      }
    }
    for (const axis of ["x", "y"]) {
      if (next[axis + "min"] != null && next[axis + "max"] != null && next[axis + "min"] >= next[axis + "max"]) {
        error.textContent = `${axis.toUpperCase()} 軸下限必須小於上限。`;
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
  container.querySelector(".chart-reset").onclick = () => {
    field("x").value = "2";
    field("y").value = histories.loss ? "loss" : Object.keys(histories)[0] || "";
    for (const name of ["xmin", "xmax", "ymin", "ymax"]) field(name).value = "";
    applySettings();
  };

  function numberLabel(value) {
    if (value === 0) return "0";
    if (Math.abs(value) < 0.001 || Math.abs(value) >= 100000) return value.toExponential(2);
    return String(Number(value.toPrecision(4)));
  }

  function bounds(values, min, max) {
    let low = min ?? Math.min(...values);
    let high = max ?? Math.max(...values);
    if (low >= high) {
      const padding = Math.max(Math.abs(low), Math.abs(high)) * 0.05 || 0.001;
      if (min == null && max == null) { low -= padding; high += padding; }
      else if (min == null) low = high - padding;
      else if (max == null) high = low + padding;
    }
    return [low, high];
  }

  function draw() {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const points = histories[settings.y]?.[historyKind] || [];
    const xName = {0: "經過秒數 (s)", 2: "步數", 3: "更新次數"}[settings.x];
    canvas.setAttribute("aria-label", `${settings.y || "指標"} 曲線，X 軸：${xName}`);
    if (!points.length) { caption.textContent = "等待數值資料。"; return; }

    const [xmin, xmax] = bounds(points.map(p => p[settings.x]), settings.xmin, settings.xmax);
    const visible = points.filter(p => p[settings.x] >= xmin && p[settings.x] <= xmax);
    const yPoints = visible.length ? visible : points;
    const [ymin, ymax] = bounds(yPoints.map(p => p[1]), settings.ymin, settings.ymax);
    // Normalized coordinates are easier to inspect than a hidden chart-library configuration.
    const left = 80, right = 620, top = 34, bottom = 224;
    const x = p => left + (right - left) * ((p[settings.x] - xmin) / (xmax - xmin));
    const y = p => bottom - (bottom - top) * ((p[1] - ymin) / (ymax - ymin));

    ctx.font = "12px system-ui";
    ctx.lineWidth = 1;
    for (let tick = 0; tick <= 4; tick++) {
      const ratio = tick / 4;
      const px = left + (right - left) * ratio;
      const py = bottom - (bottom - top) * ratio;
      ctx.strokeStyle = "#e5eaf0";
      ctx.beginPath(); ctx.moveTo(px, top); ctx.lineTo(px, bottom);
      ctx.moveTo(left, py); ctx.lineTo(right, py); ctx.stroke();
      ctx.fillStyle = "#59636e";
      ctx.textAlign = tick === 4 ? "right" : tick === 0 ? "left" : "center";
      ctx.fillText(numberLabel(xmin + (xmax - xmin) * ratio), px, bottom + 20);
      ctx.textAlign = "right";
      ctx.fillText(numberLabel(ymin + (ymax - ymin) * ratio), left - 10, py + 4);
    }
    ctx.textAlign = "left";
    ctx.fillText(settings.y, left, 18);
    ctx.textAlign = "center";
    ctx.fillText(xName, (left + right) / 2, 269);

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
    caption.textContent = `X：${numberLabel(xmin)} ～ ${numberLabel(xmax)}；Y：${numberLabel(ymin)} ～ ${numberLabel(ymax)}` +
      (visible.length ? "" : "；此 X 範圍內沒有取樣點。") +
      (historyKind === "overview" ? "　總覽保留取樣趨勢。" : "　最近 300 次此指標更新。");
  }

  return {
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
