/* SSE consumer du flux /api/scans/{id}/stream.
   Met à jour la progress bar, les compteurs, et prepend les cartes de
   tentatives au fur et à mesure. */

(function () {
  const scanId = window.SCAN_ID;
  if (!scanId) return;

  const feedEl = document.getElementById('attempt-feed');
  const placeholder = document.getElementById('feed-placeholder');
  const progressBar = document.getElementById('progress-bar');
  const progressText = document.getElementById('progress-text');
  const statusBadge = document.getElementById('status-badge');
  const successCounter = document.getElementById('success-counter');
  const scoreEstimate = document.getElementById('score-estimate');
  const currentCategory = document.getElementById('current-category');
  const finishedActions = document.getElementById('finished-actions');
  const reportLink = document.getElementById('report-link');
  const abortBtn = document.getElementById('abort-btn');
  const finalScore = document.getElementById('final-score');
  const finalDuration = document.getElementById('final-duration');

  const catNodes = {};
  document.querySelectorAll('li[data-cat]').forEach((li) => {
    catNodes[li.dataset.cat] = {
      success: li.querySelector('.cat-success'),
      total: li.querySelector('.cat-total'),
    };
  });

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const verdictColor = {
    success: 'border-red-500 bg-red-50',
    failure: 'border-green-500 bg-white',
    partial: 'border-orange-500 bg-orange-50',
    error: 'border-gray-400 bg-gray-50',
  };
  const verdictBadge = {
    success: 'bg-red-100 text-red-800',
    failure: 'bg-green-100 text-green-800',
    partial: 'bg-orange-100 text-orange-800',
    error: 'bg-gray-200 text-gray-700',
  };
  const severityBadge = {
    low: 'bg-gray-100 text-gray-700',
    medium: 'bg-yellow-100 text-yellow-800',
    high: 'bg-orange-100 text-orange-800',
    critical: 'bg-red-200 text-red-900 pulse-critical',
  };

  function setStatus(text, cls) {
    statusBadge.textContent = text;
    statusBadge.className = 'px-3 py-1 rounded-full text-xs font-semibold ' + cls;
  }

  function bumpCat(cat, verdict) {
    const nodes = catNodes[cat];
    if (!nodes) return;
    nodes.total.textContent = Number(nodes.total.textContent) + 1;
    if (verdict === 'success') {
      nodes.success.textContent = Number(nodes.success.textContent) + 1;
    }
  }

  function renderCard(p) {
    const div = document.createElement('div');
    div.className = 'attempt-card rounded-xl border-l-4 shadow-sm p-4 ' + (verdictColor[p.judgment] || 'border-gray-300 bg-white');
    div.innerHTML = `
      <div class="flex items-start justify-between gap-3 mb-2 flex-wrap">
        <div class="flex flex-wrap gap-1.5 items-center">
          <span class="text-xs font-mono px-2 py-0.5 rounded bg-midnight text-white">#${p.attempt_index}/${p.total_planned}</span>
          <span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700 font-medium">${esc(p.category)}</span>
          <span class="text-xs px-2 py-0.5 rounded font-medium ${verdictBadge[p.judgment] || ''}">${esc(p.judgment)}</span>
          <span class="text-xs px-2 py-0.5 rounded font-medium ${severityBadge[p.severity] || ''}">${esc(p.severity || '-')}</span>
          <span class="text-xs font-mono text-gray-500">${esc(p.strategy_name)}</span>
        </div>
        <span class="text-xs text-gray-400 font-mono">${p.latency_ms != null ? p.latency_ms + 'ms' : ''}</span>
      </div>
      <p class="text-sm text-gray-700 mb-2">${esc(p.judgment_reasoning || '')}</p>
      <details class="text-xs text-gray-600">
        <summary class="cursor-pointer hover:text-gray-900">Voir le prompt et la réponse</summary>
        <div class="mt-2 space-y-2">
          <div><strong>Prompt envoyé :</strong><pre>${esc(p.attack_prompt_preview)}</pre></div>
          <div><strong>Réponse cible :</strong><pre>${esc(p.target_response_preview)}</pre></div>
        </div>
      </details>`;
    return div;
  }

  function prepend(card) {
    if (placeholder) placeholder.remove();
    feedEl.insertBefore(card, feedEl.firstChild);
  }

  const evtSource = new EventSource(`/api/scans/${scanId}/stream`);

  evtSource.addEventListener('scan_started', () => setStatus('running', 'bg-blue-100 text-blue-800'));

  evtSource.addEventListener('attempt_started', (e) => {
    const { payload } = JSON.parse(e.data);
    currentCategory.textContent = payload.category;
  });

  evtSource.addEventListener('attempt_completed', (e) => {
    const { payload } = JSON.parse(e.data);
    prepend(renderCard(payload));
    bumpCat(payload.category, payload.judgment);
  });

  evtSource.addEventListener('scan_progress', (e) => {
    const { payload } = JSON.parse(e.data);
    progressBar.style.width = (payload.percent || 0) + '%';
    progressText.textContent = `${payload.done} / ${payload.total}`;
    successCounter.textContent = payload.successful_so_far;
    if (payload.total > 0) {
      const asr = payload.successful_so_far / payload.total;
      scoreEstimate.textContent = (100 * (1 - asr)).toFixed(1);
    }
  });

  evtSource.addEventListener('scan_completed', (e) => {
    const { payload } = JSON.parse(e.data);
    setStatus('terminé', 'bg-green-100 text-green-800');
    finishedActions.classList.remove('hidden');
    finalScore.textContent = payload.robustness_score != null ? payload.robustness_score : '—';
    finalDuration.textContent = payload.duration_seconds + ' s';
    reportLink.href = `/scans/${scanId}/report`;
    abortBtn.style.display = 'none';
    evtSource.close();
  });

  evtSource.addEventListener('scan_failed', (e) => {
    const { payload } = JSON.parse(e.data);
    setStatus('échec', 'bg-red-100 text-red-800');
    abortBtn.style.display = 'none';
    console.error('Scan failed:', payload.error_message);
    evtSource.close();
  });

  evtSource.onerror = (e) => {
    console.warn('SSE connection error — browser will retry automatically.', e);
  };

  abortBtn.addEventListener('click', async () => {
    if (!confirm("Interrompre le scan en cours ?")) return;
    abortBtn.disabled = true;
    await fetch(`/api/scans/${scanId}/abort`, { method: 'POST' });
  });
})();
