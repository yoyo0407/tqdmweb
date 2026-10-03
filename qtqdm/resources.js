function createResourceView() {
  const element = id => document.getElementById(id);
  const number = value => value == null ? "unavailable" : Number(value).toFixed(1);
  return {
    update(data) {
      if (!data) return;
      element("resource-cpu").textContent = `CPU Utilization: ${number(data.cpu_percent)}${data.cpu_percent == null ? "" : "%"}`;
      const used = data.ram_used_bytes == null ? null : data.ram_used_bytes / 1024 ** 3;
      const total = data.ram_total_bytes == null ? null : data.ram_total_bytes / 1024 ** 3;
      element("resource-ram").textContent = `RAM: ${number(used)} / ${number(total)} GiB`;
      const container = element("resource-gpus");
      container.replaceChildren();
      for (const gpu of data.gpus) {
        const line = document.createElement("p");
        line.textContent = `GPU ${gpu.index} (${gpu.name}) | Utilization: ${number(gpu.utilization_percent)}${gpu.utilization_percent == null ? "" : "%"} | VRAM: ${number(gpu.memory_used_mib)} / ${number(gpu.memory_total_mib)} MiB`;
        container.append(line);
      }
      const age = data.sampled_at == null ? null : Math.max(0, Date.now() / 1000 - data.sampled_at);
      element("resource-status").textContent = [age == null ? "Waiting for first sample..." : `Sample age: ${age.toFixed(1)} s${age > 3 ? " (stale)" : ""}`, ...data.errors].join(" | ");
    }
  };
}
