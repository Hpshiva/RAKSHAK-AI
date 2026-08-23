(() => {
    const bell = document.querySelector('.fa-bell')?.closest('a, button');
    if (!bell) return;

    const style = document.createElement('style');
    style.textContent = `
        .notification-bell { position: relative; }
        .notification-badge { position:absolute; top:-2px; right:-2px; min-width:17px; height:17px; padding:0 4px; display:none; place-items:center; border:2px solid white; border-radius:99px; color:white; background:var(--color-error, #c64545); font-size:10px; font-weight:700; }
        .notification-panel { position:fixed; top:82px; right:82px; z-index:3000; width:min(380px,calc(100vw - 24px)); max-height:440px; overflow:hidden; display:none; border:1px solid var(--color-hairline, #e6dfd8); border-radius:var(--radius-xl, 16px); background:#ffffff; box-shadow:0 20px 55px rgba(20,20,19,.16); }
        .notification-panel.open { display:block; animation:notificationIn .18s ease-out; }
        @keyframes notificationIn { from { opacity:0; transform:translateY(-8px) scale(.98); } }
        .notification-header { display:flex; align-items:center; justify-content:space-between; padding:16px 18px; border-bottom:1px solid var(--color-hairline-soft, #ebe6df); }
        .notification-header strong { font-family:var(--font-display, serif); font-weight:400; font-size:1.1rem; color:var(--color-ink, #141413); }
        .notification-header button { border:0; color:var(--color-primary, #cc785c); background:transparent; cursor:pointer; font-weight:650; font-family:inherit; }
        .notification-list { max-height:365px; overflow:auto; }
        .notification-item { display:flex; gap:12px; padding:14px 18px; border-bottom:1px solid var(--color-hairline-soft, #ebe6df); }
        .notification-item:last-child { border-bottom:0; }
        .notification-item-icon { width:38px; height:38px; flex:0 0 38px; display:grid; place-items:center; border-radius:var(--radius-md, 8px); color:var(--color-error, #c64545); background:rgba(198,69,69,.12); }
        .notification-item-title { color:var(--color-ink, #141413); font-size:.88rem; font-weight:700; margin-bottom:3px; }
        .notification-item-meta { color:var(--color-muted-soft, #8e8b82); font-size:.76rem; }
        .notification-empty { padding:34px 18px; color:var(--color-muted-soft, #8e8b82); text-align:center; }
        @media(max-width:650px){ .notification-panel { top:76px; right:12px; } }
    `;
    document.head.appendChild(style);

    bell.classList.add('notification-bell');
    bell.setAttribute('aria-label', 'Notifications');
    bell.setAttribute('aria-expanded', 'false');
    const badge = document.createElement('span');
    badge.className = 'notification-badge';
    bell.appendChild(badge);

    const panel = document.createElement('section');
    panel.className = 'notification-panel';
    panel.innerHTML = `<div class="notification-header"><strong>Critical Notifications</strong><button type="button">Mark all read</button></div><div class="notification-list"><div class="notification-empty">Loading notifications...</div></div>`;
    document.body.appendChild(panel);
    const list = panel.querySelector('.notification-list');

    const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
    async function loadNotifications() {
        try {
            const response = await fetch('/api/analytics/logs?page=1&page_size=10&severity=CRITICAL');
            if (response.status === 401) return location.replace('/');
            if (!response.ok) throw new Error('Unable to load notifications');
            const data = await response.json();
            const logs = data.logs || [];
            list.innerHTML = logs.length ? logs.map(log => `<div class="notification-item"><div class="notification-item-icon"><i class="fa-solid fa-triangle-exclamation"></i></div><div><div class="notification-item-title">Violence Detected</div><div class="notification-item-meta">${escapeHtml(log.detected_at)}</div></div></div>`).join('') : '<div class="notification-empty">No critical notifications.</div>';
            const lastRead = Number(localStorage.getItem('rakshakNotificationsReadThrough') || 0);
            const unread = logs.filter(log => Number(log.id) > lastRead).length;
            badge.textContent = unread > 9 ? '9+' : String(unread);
            badge.style.display = unread ? 'grid' : 'none';
        } catch (error) {
            list.innerHTML = '<div class="notification-empty">Could not load notifications.</div>';
        }
    }

    bell.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        panel.classList.toggle('open');
        bell.setAttribute('aria-expanded', String(panel.classList.contains('open')));
        if (panel.classList.contains('open')) loadNotifications();
    });
    panel.querySelector('button').addEventListener('click', () => {
        const newestId = [...list.querySelectorAll('.notification-item')].length ? Date.now() : 0;
        fetch('/api/analytics/logs?page=1&page_size=10&severity=CRITICAL').then(response => response.json()).then(data => {
            const id = Number(data.logs?.[0]?.id || newestId);
            localStorage.setItem('rakshakNotificationsReadThrough', String(id));
            badge.style.display = 'none';
        });
    });
    document.addEventListener('click', event => {
        if (!panel.contains(event.target)) { panel.classList.remove('open'); bell.setAttribute('aria-expanded', 'false'); }
    });
    loadNotifications();
    setInterval(loadNotifications, 10000);
})();
