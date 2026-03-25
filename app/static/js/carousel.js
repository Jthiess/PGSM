// Simple horizontal scroll buttons for each carousel
document.addEventListener('DOMContentLoaded', function () {
  // Fullscreen panel functionality
  const panel = document.getElementById('fullscreen-panel');
  const closePanel = document.getElementById('close-panel');
  
  // Close panel when clicking the close button
  closePanel.addEventListener('click', () => {
    panel.classList.remove('active');
    document.body.style.overflow = 'auto';
  });

  // Handle escape key to close panel
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && panel.classList.contains('active')) {
      panel.classList.remove('active');
      document.body.style.overflow = 'auto';
    }
  });

  // Add click handlers to all carousel cards
  document.querySelectorAll('.carousel-card').forEach(card => {
    card.addEventListener('click', () => {
      // Get card data
      const modded = card.dataset.modded === 'true';
      const packName = card.dataset.packName || '';
      const serverName = card.dataset.serverName || '';
      // For modded servers, use pack name; otherwise use server name
      const title = modded && packName ? packName : serverName;
      const motd = card.querySelector('.card-motd').textContent;
      const description = card.querySelector('.card-text').textContent;
      const statusBadge = card.querySelector('.status-badge');
      const status = statusBadge.textContent.trim();
      const isOnline = statusBadge.classList.contains('status-online');
      const isArchived = statusBadge.classList.contains('status-archived');
      const serverIp = card.dataset.ip || '';
      const game = card.dataset.game || '';
      
      // Get info fields - different for active vs archived servers
      let field1Label = 'Players';
      let field1Value = '';
      let field2Label = 'Version';
      let field2Value = '';
      let field3Label = 'Status';
      let field3Value = status;
      
      const infoBlocks = card.querySelectorAll('.info-block');
      
      if (isArchived) {
        // For archived servers: File Size, Version, Archival Date
        field1Label = 'File Size';
        field3Label = 'Archival Date';
        
        infoBlocks.forEach(block => {
          const label = block.querySelector('h6').textContent.toLowerCase();
          if (label === 'file size') {
            field1Value = block.querySelector('p').textContent;
          } else if (label === 'version') {
            field2Value = block.querySelector('p').textContent;
          } else if (label === 'archival date:') {
            field3Value = block.querySelector('p').textContent;
          }
        });
      } else {
        // For active servers: Players, Version, Status
        infoBlocks.forEach(block => {
          const label = block.querySelector('h6').textContent.toLowerCase();
          if (label === 'players') {
            field1Value = block.querySelector('p').textContent;
          } else if (label === 'version') {
            field2Value = block.querySelector('p').textContent;
          }
        });
      }

      // Update panel content with header image based on game
      const headerImageName = game.toLowerCase().replace(/\s+/g, '-');
      document.getElementById('panel-image').src = `/static/images/headers/${headerImageName}.jpg`;
      document.getElementById('panel-title').textContent = title;
      document.getElementById('panel-motd').textContent = motd;
      document.getElementById('panel-description').textContent = description;
      
      // Update panel info blocks with appropriate labels and values
      const panelInfoBlocks = document.querySelectorAll('.panel-info-block');
      if (panelInfoBlocks.length >= 3) {
        panelInfoBlocks[0].querySelector('h6').textContent = field1Label;
        panelInfoBlocks[0].querySelector('p').textContent = field1Value || 'N/A';
        
        panelInfoBlocks[1].querySelector('h6').textContent = field2Label;
        panelInfoBlocks[1].querySelector('p').textContent = field2Value || 'N/A';
        
        panelInfoBlocks[2].querySelector('h6').textContent = field3Label;
        panelInfoBlocks[2].querySelector('p').textContent = field3Value || 'N/A';
      }
      
      // Handle IP copy button (only for active servers)
      const copyIpBtn = document.getElementById('copy-ip-btn');
      const ipText = document.getElementById('ip-text');
      
      if (isArchived) {
        // For archived servers, repurpose button as world download link
        const worldLink = card.dataset.worldLink || '';
        if (worldLink) {
          copyIpBtn.style.display = 'flex';
          copyIpBtn.onclick = (e) => {
            e.stopPropagation();
            window.open(worldLink, '_blank');
          };
          ipText.textContent = 'Download World';
          // Change icon to download icon
          const svgIcon = copyIpBtn.querySelector('svg');
          if (svgIcon) {
            svgIcon.innerHTML = '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
            svgIcon.setAttribute('viewBox', '0 0 24 24');
          }
        } else {
          copyIpBtn.style.display = 'none';
        }
      } else if (serverIp) {
        // For active servers, show IP copy button
        copyIpBtn.style.display = 'flex';
        ipText.textContent = serverIp;
        // Reset to copy functionality
        copyIpBtn.onclick = async (e) => {
          e.stopPropagation();
          try {
            await navigator.clipboard.writeText(serverIp);
            const originalText = copyIpBtn.innerHTML;
            copyIpBtn.classList.add('copied');
            copyIpBtn.innerHTML = '<span>Copied!</span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
            
            setTimeout(() => {
              copyIpBtn.classList.remove('copied');
              copyIpBtn.innerHTML = originalText;
            }, 2000);
          } catch (err) {
            console.error('Failed to copy IP:', err);
          }
        };
        // Reset icon to copy icon
        const svgIcon = copyIpBtn.querySelector('svg');
        if (svgIcon) {
          svgIcon.innerHTML = '<rect x="9" y="9" width="13" height="13" rx="2" stroke="currentColor" stroke-width="2"/><path d="M5 15H4C2.89543 15 2 14.1046 2 13V4C2 2.89543 2.89543 2 4 2H13C14.1046 2 15 2.89543 15 4V5" stroke="currentColor" stroke-width="2"/>';
          svgIcon.setAttribute('viewBox', '0 0 24 24');
        }
      } else {
        copyIpBtn.style.display = 'none';
      }
      
      // Update status badge
      const panelBadge = document.getElementById('panel-status-badge');
      panelBadge.textContent = status;
      panelBadge.className = 'status-badge';
      if (isOnline) {
        panelBadge.classList.add('status-online');
      } else if (isArchived) {
        panelBadge.classList.add('status-archived');
      } else {
        panelBadge.classList.add('status-offline');
      }

      // Modpack section logic
      const modpackSection = document.getElementById('modpack-section');
      // modded already declared at the start of the function
      
      if (modded) {
        modpackSection.style.display = '';
        const packNameForModSection = packName || 'title';
        const packDesc = card.dataset.packDesc || '';
        const packLink = card.dataset.packLink || '';
        const packImgId = card.dataset.packImgId || '';
        const packVersion = card.dataset.packVersion || '';
        
        // If pack-img-id exists, try to load the image, otherwise use emoji
        const modpackIconEl = document.getElementById('modpack-icon');
        if (packImgId) {
          modpackIconEl.innerHTML = `<img src="/static/images/packicons/${packImgId}" alt="${packNameForModSection}" style="width: 100%; height: 100%; object-fit: cover; border-radius: 16px;">`;
        } else {
          modpackIconEl.textContent = '🛠️';
        }
        
        // Set pack name without version
        document.getElementById('modpack-name').textContent = packNameForModSection;
        
        // Set pack version as separate element if it exists
        const versionEl = document.getElementById('modpack-version');
        if (packVersion) {
          versionEl.textContent = `Version ${packVersion}`;
          versionEl.style.display = '';
        } else {
          versionEl.style.display = 'none';
        }
        
        document.getElementById('modpack-description').textContent = packDesc;
        
        const linkEl = document.getElementById('modpack-link');
        if (packLink) {
          linkEl.href = packLink;
          linkEl.style.display = '';
        } else {
          linkEl.style.display = 'none';
        }
      } else {
        modpackSection.style.display = 'none';
      }
      
      // Show panel
      panel.classList.add('active');
      document.body.style.overflow = 'hidden';
    });
  });
  const buttons = document.querySelectorAll('.carousel-btn');
  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target') === 'middle' ? 'carousel-middle' : 'carousel-bottom';
      const dir = btn.getAttribute('data-dir');
      const container = document.getElementById(targetId);
      if (!container) return;
      const amount = Math.round(container.clientWidth * 0.8);
      container.scrollBy({ left: dir === 'left' ? -amount : amount, behavior: 'smooth' });
    });
  });

  // Enable mouse drag to scroll horizontally and handle wheel events
  const draggables = document.querySelectorAll('.carousel-row');
  draggables.forEach(drag => {
    let isDown = false;
    let startX, scrollLeft;

    // Prevent text selection while dragging
    drag.style.userSelect = 'none';
    drag.style.webkitUserSelect = 'none';
    drag.style.msUserSelect = 'none';

    // Prevent images inside the carousel from starting native drag operations
    // This avoids the browser drag ghost when the user is trying to drag-scroll the carousel.
    const imgs = drag.querySelectorAll('img');
    imgs.forEach(img => {
      try { img.draggable = false; } catch (err) { /* ignore */ }
      img.addEventListener('dragstart', (ev) => ev.preventDefault());
    });
    drag.addEventListener('mousedown', (e) => {
      isDown = true;
      drag.classList.add('dragging');
      startX = e.pageX - drag.offsetLeft;
      scrollLeft = drag.scrollLeft;
    });

    window.addEventListener('mouseup', () => {
      isDown = false;
      drag.classList.remove('dragging');
    });

    drag.addEventListener('mousemove', (e) => {
      if (!isDown) return;
      e.preventDefault();
      const x = e.pageX - drag.offsetLeft;
      const walk = (x - startX) * 1; // scroll-fast multiplier
      drag.scrollLeft = scrollLeft - walk;
    });

    // Handle wheel events for horizontal scrolling
    drag.addEventListener('wheel', (e) => {
      e.preventDefault(); // Prevent vertical scrolling
      drag.scrollBy({
        left: e.deltaY * 3, // Increased multiplier for faster scrolling
        behavior: 'smooth'
      });
    });
  });
});
