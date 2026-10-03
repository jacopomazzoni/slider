(() => {
  const panel = document.querySelector('.software-updates');
  if (!panel) return;
  const status = panel.querySelector('.update-status');
  const detail = panel.querySelector('.update-detail');
  const check = panel.querySelector('.update-check');
  const install = panel.querySelector('.update-install');
  let sha = '';
  let controller;
  let busy = false;
  async function request(url, options = {}) {
    controller?.abort();
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal, cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Update check failed.');
      return data;
    } finally { clearTimeout(timeout); }
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    check.disabled = true;
    install.hidden = true;
    try {
      const data = await request(panel.dataset.checkUrl);
      sha = data.latest;
      const running = data.job?.state === 'running';
      status.textContent = running ? data.job.message : data.available ? 'A software update is available.' : 'Software is up to date.';
      detail.textContent = [data.repository, `Installed: ${data.current.slice(0, 8)}`, `Latest: ${sha.slice(0, 8)}`, data.reason,
        data.job?.state === 'failed' ? data.job.message : ''].filter(Boolean).join(' · ');
      install.hidden = !data.can_install || running;
    } catch (error) { status.textContent = error.message; detail.textContent = ''; }
    finally { check.disabled = false; busy = false; }
  }
  check.addEventListener('click', refresh);
  panel.querySelector('form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !sha || !confirm('Install this update? The display will briefly lose its connection while the server restarts.')) return;
    busy = true;
    install.disabled = true;
    check.disabled = true;
    try {
      const body = new URLSearchParams({ sha, csrfmiddlewaretoken: panel.querySelector('[name=csrfmiddlewaretoken]').value });
      const data = await request(panel.dataset.installUrl, { method: 'POST', body });
      status.textContent = data.message;
      detail.textContent = 'Refresh this page after the server restarts. If it stays offline, inspect the server update log.';
      install.hidden = true;
    } catch (error) { status.textContent = error.message; }
    finally { busy = false; install.disabled = false; check.disabled = false; }
  });
  window.addEventListener('pagehide', () => controller?.abort(), { once: true });
  refresh();
})();
