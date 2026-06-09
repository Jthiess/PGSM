// carousel.js — Server card click-to-detail and horizontal scroll logic
document.addEventListener('DOMContentLoaded', function () {

  // ── Detail panel elements ─────────────────────────────────────────────────
  const panel   = document.getElementById('fullscreen-panel');
  const closeBtn = document.getElementById('close-panel');
  const backdrop = document.getElementById('detail-panel-backdrop');

  let lastFocused = null;

  function openPanel() {
    panel.classList.add('active');
    document.body.style.overflow = 'hidden';
    // Move focus into the dialog (close button is reliably focusable).
    if (closeBtn) closeBtn.focus({ preventScroll: true });
  }

  function closePanel() {
    panel.classList.remove('active');
    document.body.style.overflow = '';
    // Restore focus to whatever opened the panel.
    if (lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus({ preventScroll: true });
    }
    lastFocused = null;
  }

  closeBtn.addEventListener('click', closePanel);
  if (backdrop) backdrop.addEventListener('click', closePanel);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && panel.classList.contains('active')) {
      closePanel();
    }
  });

  // Focus trap: keep Tab focus within the dialog while it is open.
  panel.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab' || !panel.classList.contains('active')) return;
    const focusables = Array.prototype.filter.call(
      panel.querySelectorAll('a[href], button, input, textarea, select, [tabindex]:not([tabindex="-1"])'),
      function (el) { return el.offsetParent !== null && !el.disabled; }
    );
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  });

  // ── Card click handlers ───────────────────────────────────────────────────
  document.querySelectorAll('.carousel-card').forEach(function (card) {
    // Support both click and keyboard activation (Enter / Space)
    card.addEventListener('click', () => activateCard(card));
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        activateCard(card);
      }
    });
  });

  function activateCard(card) {
    const modded       = card.dataset.modded === 'true';
    const packName     = card.dataset.packName  || '';
    const serverName   = card.dataset.serverName || '';
    const title        = modded && packName ? packName : serverName;
    const motd         = card.querySelector('.card-motd') ? card.querySelector('.card-motd').textContent : '';
    const descEl       = card.querySelector('.card-desc');
    const description  = descEl ? descEl.textContent : '';
    const statusBadge  = card.querySelector('.status-badge');
    const status       = statusBadge.textContent.trim();
    const isOnline     = statusBadge.classList.contains('status-online');
    const isArchived   = statusBadge.classList.contains('status-archived');
    const serverIp     = card.dataset.ip || '';
    const requiresLogin = card.dataset.requiresLogin === 'true';
    const loginUrl     = panel.dataset.loginUrl || '';
    const game         = card.dataset.game || '';

    // ── Determine info field labels / values ───────────────────────────────
    let field1Label = 'Players';
    let field1Value = '';
    let field2Label = 'Version';
    let field2Value = '';
    let field3Label = 'Status';
    let field3Value = status;

    if (isArchived) {
      field1Label = 'File Size';
      field3Label = 'Archived';

      const statsEl = card.querySelector('.card-stats');
      if (statsEl) {
        const statItems = statsEl.querySelectorAll('.stat-item');
        statItems.forEach(function (item) {
          const lbl = item.querySelector('.stat-label');
          const val = item.querySelector('.stat-value');
          if (!lbl || !val) return;
          const labelText = lbl.textContent.toLowerCase().trim();
          if (labelText === 'size')    field1Value = val.textContent;
          if (labelText === 'version') field2Value = val.textContent;
        });
      }
      const archiveDateEl = card.querySelector('.card-archive-date .stat-value');
      if (archiveDateEl) field3Value = archiveDateEl.textContent;
    } else {
      const statsEl = card.querySelector('.card-stats');
      if (statsEl) {
        statsEl.querySelectorAll('.stat-item').forEach(function (item) {
          const lbl = item.querySelector('.stat-label');
          const val = item.querySelector('.stat-value');
          if (!lbl || !val) return;
          const labelText = lbl.textContent.toLowerCase().trim();
          if (labelText === 'players') field1Value = val.textContent;
          if (labelText === 'version') field2Value = val.textContent;
        });
      }
    }

    // ── Populate panel content ─────────────────────────────────────────────
    document.getElementById('panel-image').src = card.dataset.headerImg || '';
    document.getElementById('panel-title').textContent       = title;
    document.getElementById('panel-motd').textContent        = motd;
    document.getElementById('panel-description').textContent = description;

    const panelInfoBlocks = document.querySelectorAll('.panel-info-block');
    if (panelInfoBlocks.length >= 3) {
      panelInfoBlocks[0].querySelector('.panel-info-label').textContent = field1Label;
      panelInfoBlocks[0].querySelector('.panel-info-value').textContent = field1Value || 'N/A';

      panelInfoBlocks[1].querySelector('.panel-info-label').textContent = field2Label;
      panelInfoBlocks[1].querySelector('.panel-info-value').textContent = field2Value || 'N/A';

      panelInfoBlocks[2].querySelector('.panel-info-label').textContent = field3Label;
      panelInfoBlocks[2].querySelector('.panel-info-value').textContent = field3Value || 'N/A';
    }

    // ── IP / world download button ─────────────────────────────────────────
    const copyIpBtn = document.getElementById('copy-ip-btn');
    const ipTextEl  = document.getElementById('ip-text');

    function _showLoginPrompt(label) {
      copyIpBtn.style.display = 'flex';
      ipTextEl.textContent = label;
      copyIpBtn.classList.remove('copied');
      copyIpBtn.onclick = function (e) {
        e.stopPropagation();
        if (loginUrl) window.location.href = loginUrl;
      };
      const svgIcon = copyIpBtn.querySelector('svg');
      if (svgIcon) {
        svgIcon.innerHTML = '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
        svgIcon.setAttribute('viewBox', '0 0 24 24');
      }
    }

    if (isArchived) {
      const worldLink = card.dataset.worldLink || '';
      if (worldLink) {
        copyIpBtn.style.display = 'flex';
        copyIpBtn.onclick = function (e) {
          e.stopPropagation();
          window.open(worldLink, '_blank', 'noopener');
        };
        ipTextEl.textContent = 'Download World';
        const svgIcon = copyIpBtn.querySelector('svg');
        if (svgIcon) {
          svgIcon.innerHTML = '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
          svgIcon.setAttribute('viewBox', '0 0 24 24');
        }
      } else if (requiresLogin) {
        _showLoginPrompt('Sign in to download world');
      } else {
        copyIpBtn.style.display = 'none';
      }
    } else if (serverIp) {
      copyIpBtn.style.display = 'flex';
      ipTextEl.textContent    = serverIp;
      copyIpBtn.onclick = async function (e) {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(serverIp);
          const origHTML = copyIpBtn.innerHTML;
          copyIpBtn.classList.add('copied');
          copyIpBtn.innerHTML = '<span>Copied!</span><svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
          setTimeout(function () {
            copyIpBtn.classList.remove('copied');
            copyIpBtn.innerHTML = origHTML;
          }, 2000);
        } catch (err) {
          console.error('Failed to copy IP:', err);
        }
      };
      const svgIcon = copyIpBtn.querySelector('svg');
      if (svgIcon) {
        svgIcon.innerHTML = '<rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="2"/><path d="M5 15H4C2.89543 15 2 14.1046 2 13V4C2 2.89543 2.89543 2 4 2H13C14.1046 2 15 2.89543 15 4V5" stroke="currentColor" stroke-width="2"/>';
        svgIcon.setAttribute('viewBox', '0 0 24 24');
      }
    } else if (requiresLogin) {
      _showLoginPrompt('Sign in to view server address');
    } else {
      copyIpBtn.style.display = 'none';
    }

    // ── Status badge ───────────────────────────────────────────────────────
    const panelBadge = document.getElementById('panel-status-badge');
    panelBadge.textContent = status;
    panelBadge.className   = 'status-badge';
    if (isOnline)        panelBadge.classList.add('status-online');
    else if (isArchived) panelBadge.classList.add('status-archived');
    else                 panelBadge.classList.add('status-offline');

    // ── Modpack sidebar ────────────────────────────────────────────────────
    const modpackSection = document.getElementById('modpack-section');
    if (modded) {
      modpackSection.style.display = '';

      const packDesc    = card.dataset.packDesc    || '';
      const packLink    = card.dataset.packLink    || '';
      const packImgId   = card.dataset.packImgId   || '';
      const packVersion = card.dataset.packVersion || '';
      const displayName = packName || serverName;

      const iconEl = document.getElementById('modpack-icon');
      if (packImgId) {
        // Build via DOM (not innerHTML) so admin-entered pack name / image id
        // cannot inject markup. encodeURIComponent keeps the id in the path.
        iconEl.textContent = '';
        const packImg = document.createElement('img');
        packImg.src = '/static/images/packicons/' + encodeURIComponent(packImgId);
        packImg.alt = displayName;
        packImg.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:12px;';
        iconEl.appendChild(packImg);
      } else {
        iconEl.textContent = '\uD83D\uDEE0\uFE0F'; // 🛠️
      }

      document.getElementById('modpack-name').textContent = displayName;

      const versionEl = document.getElementById('modpack-version');
      if (packVersion) {
        versionEl.textContent  = 'Version ' + packVersion;
        versionEl.style.display = '';
      } else {
        versionEl.style.display = 'none';
      }

      document.getElementById('modpack-description').textContent = packDesc;

      const linkEl = document.getElementById('modpack-link');
      if (packLink) {
        linkEl.href           = packLink;
        linkEl.style.display  = '';
      } else {
        linkEl.style.display  = 'none';
      }
    } else {
      modpackSection.style.display = 'none';
    }

    // Remember the trigger so focus can be restored on close.
    lastFocused = card;
    openPanel();
  }

  // ── Mouse-drag horizontal scroll ─────────────────────────────────────────
  document.querySelectorAll('.carousel-row').forEach(function (row) {
    let isDown    = false;
    let startX, scrollLeft;
    let didDrag   = false;

    row.style.userSelect       = 'none';
    row.style.webkitUserSelect = 'none';

    row.querySelectorAll('img').forEach(function (img) {
      img.draggable = false;
      img.addEventListener('dragstart', function (e) { e.preventDefault(); });
    });

    row.addEventListener('mousedown', function (e) {
      isDown     = true;
      didDrag    = false;
      startX     = e.pageX - row.offsetLeft;
      scrollLeft = row.scrollLeft;
      row.classList.add('dragging');
    });

    window.addEventListener('mouseup', function () {
      isDown = false;
      row.classList.remove('dragging');
    });

    row.addEventListener('mousemove', function (e) {
      if (!isDown) return;
      e.preventDefault();
      const x    = e.pageX - row.offsetLeft;
      const walk = x - startX;
      if (Math.abs(walk) > 4) didDrag = true;
      row.scrollLeft = scrollLeft - walk;
    });

    // Suppress card activation when the user was dragging
    row.addEventListener('click', function (e) {
      if (didDrag) {
        e.stopPropagation();
        didDrag = false;
      }
    }, true);

    // Horizontal scroll via mouse wheel (respect reduced-motion preference)
    row.addEventListener('wheel', function (e) {
      e.preventDefault();
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      row.scrollBy({ left: e.deltaY * 2.5, behavior: reduce ? 'auto' : 'smooth' });
    }, { passive: false });
  });
});
