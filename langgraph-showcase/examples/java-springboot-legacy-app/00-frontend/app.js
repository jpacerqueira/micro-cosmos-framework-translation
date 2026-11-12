(function () {
  'use strict';

  const API_BASE = '/api/v1';
  let currentUser = null;
  let currentPortfolioId = null;

  // ── Auth helpers ──────────────────────────────────────────────────────────

  function getToken() { return localStorage.getItem('can_token'); }
  function setToken(t) { localStorage.setItem('can_token', t); }
  function clearToken() { localStorage.removeItem('can_token'); localStorage.removeItem('can_user'); }

  function authHeaders() {
    const h = { 'Content-Type': 'application/json' };
    const t = getToken();
    if (t) h['Authorization'] = 'Bearer ' + t;
    return h;
  }

  async function apiFetch(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign(authHeaders(), opts.headers || {});
    const res = await fetch(API_BASE + path, opts);
    if (res.status === 401) { logout(); return; }
    return res;
  }

  // ── Navigation ────────────────────────────────────────────────────────────

  function showScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
    document.getElementById(id).classList.remove('hidden');
  }

  function showView(viewId) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById('view-' + viewId).classList.add('active');
    document.querySelectorAll('.nav-item').forEach(n => {
      n.classList.toggle('active', n.dataset.view === viewId);
    });
  }

  function showModal(id) { document.getElementById(id).classList.remove('hidden'); }
  function hideModal(id) { document.getElementById(id).classList.add('hidden'); }

  function statusBadge(status) {
    const cls = 'badge-' + (status || 'pending').toLowerCase().replace(/_/g, '_');
    return '<span class="badge ' + cls + '">' + (status || 'PENDING') + '</span>';
  }

  // ── Login ─────────────────────────────────────────────────────────────────

  document.getElementById('login-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;
    const errEl = document.getElementById('login-error');
    errEl.classList.add('hidden');

    try {
      const res = await fetch(API_BASE + '/portfolios/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      if (!res.ok) {
        errEl.textContent = 'Invalid email or password.';
        errEl.classList.remove('hidden');
        return;
      }
      const data = await res.json();
      setToken(data.accessToken);
      currentUser = { id: data.userId, email: data.email, role: data.role, fullName: data.fullName };
      localStorage.setItem('can_user', JSON.stringify(currentUser));
      initApp();
    } catch (err) {
      errEl.textContent = 'Cannot connect to server. Is the BFF running?';
      errEl.classList.remove('hidden');
    }
  });

  // ── Logout ────────────────────────────────────────────────────────────────

  function logout() {
    clearToken();
    currentUser = null;
    showScreen('login-screen');
  }
  document.getElementById('logout-btn').addEventListener('click', logout);

  // ── App init ──────────────────────────────────────────────────────────────

  function initApp() {
    showScreen('app-screen');
    const u = currentUser || JSON.parse(localStorage.getItem('can_user') || 'null');
    if (u) {
      document.getElementById('user-display').textContent = u.fullName + ' (' + u.role + ')';
    }
    loadPortfolios();
    showView('portfolios');
    loadPortfoliosForUpload();
  }

  // ── Portfolios ────────────────────────────────────────────────────────────

  async function loadPortfolios() {
    const el = document.getElementById('portfolios-list');
    el.innerHTML = '<div class="loading">Loading portfolios...</div>';
    try {
      const res = await apiFetch('/portfolios');
      if (!res || !res.ok) { el.innerHTML = '<div class="empty-state"><span class="empty-icon">⚠️</span>Failed to load portfolios.</div>'; return; }
      const portfolios = await res.json();
      if (!portfolios.length) {
        el.innerHTML = '<div class="empty-state"><span class="empty-icon">📁</span>No portfolios found.</div>';
        return;
      }
      el.innerHTML = portfolios.map(function (p) {
        return '<div class="portfolio-card" data-id="' + p.id + '">' +
          '<h4>' + escHtml(p.name) + '</h4>' +
          '<p>' + escHtml(p.description || 'No description') + '</p>' +
          '<div class="card-meta">' + statusBadge(p.status) +
          (p.projectPhase ? '<span class="badge" style="background:#eee;color:#555">' + p.projectPhase + '</span>' : '') +
          '</div></div>';
      }).join('');
      el.querySelectorAll('.portfolio-card').forEach(function (card) {
        card.addEventListener('click', function () { loadPortfolioDetail(card.dataset.id); });
      });
    } catch (err) {
      el.innerHTML = '<div class="empty-state"><span class="empty-icon">⚠️</span>' + err.message + '</div>';
    }
  }

  async function loadPortfolioDetail(portfolioId) {
    currentPortfolioId = portfolioId;
    showView('portfolio-detail');
    document.getElementById('detail-portfolio-name').textContent = 'Loading...';
    document.getElementById('portfolio-detail-info').innerHTML = '<div class="loading">Loading...</div>';
    document.getElementById('properties-list').innerHTML = '';

    try {
      const [pRes, prRes] = await Promise.all([
        apiFetch('/portfolios/' + portfolioId),
        apiFetch('/portfolios/' + portfolioId + '/properties')
      ]);
      const portfolio = await pRes.json();
      const properties = prRes.ok ? await prRes.json() : [];

      document.getElementById('detail-portfolio-name').textContent = portfolio.name;
      document.getElementById('portfolio-detail-info').innerHTML =
        '<div class="detail-field"><label>Status</label><span>' + statusBadge(portfolio.status) + '</span></div>' +
        '<div class="detail-field"><label>Phase</label><span>' + (portfolio.projectPhase || '-') + '</span></div>' +
        '<div class="detail-field"><label>Cut-off Date</label><span>' + (portfolio.cutOffDate ? new Date(portfolio.cutOffDate).toLocaleDateString() : '-') + '</span></div>' +
        '<div class="detail-field"><label>Final Bid Date</label><span>' + (portfolio.finalBidDate ? new Date(portfolio.finalBidDate).toLocaleDateString() : '-') + '</span></div>' +
        '<div class="detail-field"><label>Description</label><span>' + escHtml(portfolio.description || '-') + '</span></div>';

      document.getElementById('properties-list').innerHTML = properties.length
        ? '<table class="data-table"><thead><tr><th>Name</th><th>Address</th><th>City</th><th>Type</th><th>Status</th></tr></thead><tbody>' +
          properties.map(function (p) {
            return '<tr><td>' + escHtml(p.name) + '</td><td>' + escHtml(p.address || '-') + '</td><td>' +
              escHtml(p.city || '-') + '</td><td>' + (p.propertyType || '-') + '</td><td>' + statusBadge(p.status) + '</td></tr>';
          }).join('') + '</tbody></table>'
        : '<div class="empty-state"><span class="empty-icon">🏠</span>No properties yet.</div>';
    } catch (err) {
      document.getElementById('portfolio-detail-info').innerHTML = '<div class="error-msg">' + err.message + '</div>';
    }
  }

  document.getElementById('back-to-portfolios').addEventListener('click', function () {
    showView('portfolios');
    loadPortfolios();
  });

  document.getElementById('close-portfolio-btn').addEventListener('click', async function () {
    if (!currentPortfolioId || !confirm('Close this portfolio?')) return;
    const res = await apiFetch('/portfolios/' + currentPortfolioId + '/close', { method: 'PUT' });
    if (res && res.ok) {
      alert('Portfolio closed.');
      loadPortfolioDetail(currentPortfolioId);
    } else {
      alert('Failed to close portfolio.');
    }
  });

  // ── Create Portfolio ──────────────────────────────────────────────────────

  document.getElementById('create-portfolio-btn').addEventListener('click', function () {
    showModal('modal-create-portfolio');
  });
  document.getElementById('cancel-create-portfolio').addEventListener('click', function () {
    hideModal('modal-create-portfolio');
  });
  document.querySelector('#modal-create-portfolio .modal-overlay').addEventListener('click', function () {
    hideModal('modal-create-portfolio');
  });

  document.getElementById('create-portfolio-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const body = {
      name: document.getElementById('new-portfolio-name').value,
      description: document.getElementById('new-portfolio-desc').value,
      projectPhase: document.getElementById('new-portfolio-phase').value,
      status: 'OPEN'
    };
    const res = await apiFetch('/portfolios', { method: 'POST', body: JSON.stringify(body) });
    if (res && res.ok) {
      hideModal('modal-create-portfolio');
      document.getElementById('create-portfolio-form').reset();
      loadPortfolios();
    } else {
      alert('Failed to create portfolio.');
    }
  });

  // ── Add Property ──────────────────────────────────────────────────────────

  document.getElementById('add-property-btn').addEventListener('click', function () {
    showModal('modal-add-property');
  });
  document.getElementById('cancel-add-property').addEventListener('click', function () {
    hideModal('modal-add-property');
  });
  document.querySelector('#modal-add-property .modal-overlay').addEventListener('click', function () {
    hideModal('modal-add-property');
  });

  document.getElementById('add-property-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const body = {
      name: document.getElementById('new-property-name').value,
      address: document.getElementById('new-property-address').value,
      city: document.getElementById('new-property-city').value,
      postcode: document.getElementById('new-property-postcode').value,
      propertyType: document.getElementById('new-property-type').value,
      status: 'PENDING'
    };
    const res = await apiFetch('/portfolios/' + currentPortfolioId + '/properties', { method: 'POST', body: JSON.stringify(body) });
    if (res && res.ok) {
      hideModal('modal-add-property');
      document.getElementById('add-property-form').reset();
      loadPortfolioDetail(currentPortfolioId);
    } else {
      alert('Failed to add property.');
    }
  });

  // ── Search ────────────────────────────────────────────────────────────────

  async function performSearch(q) {
    if (!q) return;
    showView('search');
    const el = document.getElementById('search-results');
    el.innerHTML = '<div class="loading">Searching...</div>';
    try {
      const res = await apiFetch('/search?q=' + encodeURIComponent(q));
      if (!res || !res.ok) { el.innerHTML = '<div class="error-msg">Search failed.</div>'; return; }
      const data = await res.json();
      let html = '';

      if (data.portfolios && data.portfolios.length) {
        html += '<div class="section-title">📁 Portfolios (' + data.portfolios.length + ')</div>';
        html += data.portfolios.map(function (p) {
          return '<div class="search-result-item"><div class="result-title">' + escHtml(p.name) + ' ' + statusBadge(p.status) + '</div>' +
            '<div class="result-meta">' + escHtml(p.description || '') + '</div></div>';
        }).join('');
      }
      if (data.properties && data.properties.length) {
        html += '<div class="section-title">🏠 Properties (' + data.properties.length + ')</div>';
        html += data.properties.map(function (p) {
          return '<div class="search-result-item"><div class="result-title">' + escHtml(p.name) + ' ' + statusBadge(p.status) + '</div>' +
            '<div class="result-meta">' + escHtml([p.address, p.city, p.postcode].filter(Boolean).join(', ')) + ' · ' + (p.property_type || '') + '</div></div>';
        }).join('');
      }
      if (data.documents && data.documents.length) {
        html += '<div class="section-title">📄 Documents (' + data.documents.length + ')</div>';
        html += data.documents.map(function (d) {
          return '<div class="search-result-item"><div class="result-title">📄 ' + escHtml(d.file_name) + '</div>' +
            '<div class="result-meta">' + (d.content_type || '') + ' · ' + (d.status || '') + '</div></div>';
        }).join('');
      }
      if (!html) html = '<div class="empty-state"><span class="empty-icon">🔍</span>No results found for "' + escHtml(q) + '".</div>';
      el.innerHTML = html;
    } catch (err) {
      el.innerHTML = '<div class="error-msg">' + err.message + '</div>';
    }
  }

  document.getElementById('search-btn').addEventListener('click', function () {
    performSearch(document.getElementById('search-input').value.trim());
  });
  document.getElementById('search-input').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') performSearch(this.value.trim());
  });

  // ── Documents ─────────────────────────────────────────────────────────────

  async function loadPortfoliosForUpload() {
    const sel = document.getElementById('upload-portfolio-id');
    try {
      const res = await apiFetch('/portfolios');
      if (!res || !res.ok) return;
      const portfolios = await res.json();
      portfolios.forEach(function (p) {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name;
        sel.appendChild(opt);
      });
    } catch (_) {}
  }

  document.getElementById('upload-form').addEventListener('submit', async function (e) {
    e.preventDefault();
    const errEl = document.getElementById('upload-error');
    const okEl = document.getElementById('upload-success');
    errEl.classList.add('hidden');
    okEl.classList.add('hidden');
    const portfolioId = document.getElementById('upload-portfolio-id').value;
    const file = document.getElementById('upload-file').files[0];
    if (!file) { errEl.textContent = 'Select a file.'; errEl.classList.remove('hidden'); return; }
    const fd = new FormData();
    fd.append('file', file);
    fd.append('portfolioId', portfolioId);
    fd.append('uploadedBy', currentUser ? currentUser.id : 'anonymous');
    try {
      const res = await fetch(API_BASE + '/documents/upload', {
        method: 'POST', headers: { 'Authorization': 'Bearer ' + getToken() }, body: fd
      });
      if (res.ok) {
        okEl.textContent = 'Document uploaded successfully.';
        okEl.classList.remove('hidden');
        document.getElementById('upload-form').reset();
      } else {
        errEl.textContent = 'Upload failed. Status: ' + res.status;
        errEl.classList.remove('hidden');
      }
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    }
  });

  // ── Sidebar nav ───────────────────────────────────────────────────────────

  document.querySelectorAll('.nav-item').forEach(function (item) {
    item.addEventListener('click', function () {
      showView(item.dataset.view);
      if (item.dataset.view === 'portfolios') loadPortfolios();
    });
  });

  // ── Utils ─────────────────────────────────────────────────────────────────

  function escHtml(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── Boot ──────────────────────────────────────────────────────────────────

  (function boot() {
    const token = getToken();
    const user = localStorage.getItem('can_user');
    if (token && user) {
      currentUser = JSON.parse(user);
      initApp();
    } else {
      showScreen('login-screen');
    }
  })();
})();
