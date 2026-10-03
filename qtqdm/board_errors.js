function renderRunError(id, failure) {
  const container = document.getElementById(id);
  container.hidden = !failure;
  if (!failure) return;
  container.querySelector('[data-error-summary]').textContent = failure.summary;
  container.querySelector('[data-error-traceback]').textContent = failure.traceback || 'No Python traceback captured.';
  container.querySelector('[data-error-log]').textContent = failure.log_path ? `Full Log: ${failure.log_path}` : 'No log file recorded.';
}
