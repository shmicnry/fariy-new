import {
    renderAssessments
} from './assessments.js';
import {
    renderKnowledge
} from './knowledge.js';
import {
    renderMac,
    renderSkills
} from './p3.js';
import {
    renderAutonomy
} from './p5.js';
import {
    renderModels,
    renderMemories,
    renderConversation,
    explain,
    watchEvents
} from './p1.js';
// No user/provider data is inserted as raw HTML. The service token stays in memory only.
let token = '',
    stopEvents = null,
    conversation = null;
let eventRefresh = null;
let routeDirty = false;
let pendingUpdates = 0;
let routeLoadingToken = 0;
let routeLoadingTimer = null;
let renderedUnread = null;
const reminderTimers = new Map();
const names = {
    overview: '运行总览',
    mind: '识海与认知',
    world: '世界与知识',
    memories: '记忆审阅',
    models: '模型与路由',
    learning: '学习中心',
    assessments: '学习测验',
    evolution: '自主与进化',
    skills: '技能中心',
    mac: 'Mac 操作',
    flows: '流程管理',
    pet: '桌宠与形象',
    cards: '卡片与通知',
    approvals: '待确认操作',
    chat: '对话',
    more: '更多'
};
const navGroups = [
    ['工作台', ['overview', 'chat']],
    ['认知', ['mind', 'world', 'memories', 'learning', 'assessments']],
    ['自主能力', ['evolution', 'flows', 'skills', 'mac']],
    ['个人空间', ['pet', 'cards', 'approvals']]
];
const systemNavGroup = ['系统', ['models']];
const mobilePrimaryRoutes = new Set(['overview', 'chat', 'memories', 'learning']);
const iconPaths = {
    overview: ['M4 10.5 12 4l8 6.5V20h-6v-6h-4v6H4z'],
    chat: ['M5 5.5h14v10H9l-4 3z'],
    mind: ['m12 3 1.4 4.1L17.5 8l-3.4 2.6 1.2 4.2-3.3-2.4-3.3 2.4 1.2-4.2L6.5 8l4.1-.9z'],
    world: ['M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM3.5 12h17M12 3.5c2 2.2 3 5 3 8.5s-1 6.3-3 8.5c-2-2.2-3-5-3-8.5s1-6.3 3-8.5z'],
    memories: ['M6 5.5h11v14l-5.5-3.2L6 19.5z'],
    learning: ['M4.5 5.5h6a2 2 0 0 1 2 2v11a2 2 0 0 0-2-2h-6zM19.5 5.5h-4a2 2 0 0 0-2 2v11a2 2 0 0 1 2-2h4z'],
    assessments: ['M6 4.5h12v15H6zM9 9h6M9 13h6M9 17h3'],
    evolution: ['M5 17c3.4 0 3.4-10 7-10 2.2 0 2.7 5.5 7 5.5M15 9l4 3.5-4 3.5'],
    flows: ['M6 6h5v5H6zM13 13h5v5h-5zM11 8.5h2M11 15.5h2M8.5 11v2.5M15.5 11v2'],
    skills: ['M8 4.5h8v3l2.5 2.5-2.5 2.5v7H8v-7L5.5 10 8 7.5z'],
    mac: ['M4 5.5h16v10H4zM9 19h6M12 15.5V19'],
    pet: ['M8 12.5c-1.8-3.4-4.5-2-3.7.9.5 1.7 2 2.7 3.7 3.2M16 12.5c1.8-3.4 4.5-2 3.7.9-.5 1.7-2 2.7-3.7 3.2M8 14.5c0-2 1.8-3.5 4-3.5s4 1.5 4 3.5c0 2.3-1.7 4-4 4s-4-1.7-4-4z'],
    cards: ['M5 6.5h14v11H5zM5 9.5h14'],
    approvals: ['M12 3.8 19 6v6c0 4.1-2.6 6.9-7 8.2-4.4-1.3-7-4.1-7-8.2V6zM9 12l2 2 4-4'],
    models: ['M4 7h10M18 7h2M4 17h2M10 17h10M16 4.5v5M8 14.5v5']
};
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e
};
const icon = name => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.classList.add('nav-icon');
    for (const pathData of iconPaths[name] || []) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathData);
        svg.append(path);
    }
    return svg;
};
const clearRouteSkeleton = () => {
    routeLoadingToken += 1;
    if (routeLoadingTimer) {
        clearTimeout(routeLoadingTimer);
        routeLoadingTimer = null;
    }
    document.querySelector('.route-skeleton')?.remove();
};
const beginRouteLoading = route => {
    clearRouteSkeleton();
    const marker = routeLoadingToken;
    routeLoadingTimer = setTimeout(() => {
        if (marker !== routeLoadingToken || $('content').childElementCount) return;
        const skeleton = el('section', undefined, 'route-skeleton');
        skeleton.setAttribute('role', 'status');
        skeleton.setAttribute('aria-live', 'polite');
        skeleton.setAttribute('aria-busy', 'true');
        skeleton.setAttribute('aria-label', '正在读取' + (names[route] || 'Fairy') + '状态');
        for (let i = 0; i < 3; i += 1) {
            const card = el('div', undefined, 'skeleton-card');
            card.append(
                el('span', undefined, i === 0 ? 'skeleton-line skeleton-title' : 'skeleton-line'),
                el('span', undefined, 'skeleton-line skeleton-copy'),
                el('span', undefined, 'skeleton-line skeleton-copy skeleton-copy-short')
            );
            skeleton.append(card);
        }
        skeleton.append(el('span', '正在读取真实状态…', 'visually-hidden'));
        $('content').append(skeleton);
    }, 180);
};
async function apiResponse(path, method = 'GET', body) {
    const headers = {
        Authorization: 'Bearer ' + token
    };
    if (body) {
        headers['Content-Type'] = 'application/json';
        headers['Idempotency-Key'] = crypto.randomUUID()
    }
    const r = await fetch('/v2/' + path, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined
    });
    if (!r.ok) {
        let detail;
        try {
            detail = (await r.json()).detail;
        } catch {
            detail = r.statusText;
        }
        throw Error(r.status + ' ' + JSON.stringify(detail))
    }
    return r
}
async function api(path, method = 'GET', body) {
    const response = await apiResponse(path, method, body);
    return response.json()
}
const panel = (title) => {
    clearRouteSkeleton();
    const p = el('section', undefined, 'panel continuous-surface');
    const heading = el('h2');
    const value = String(title);
    const dot = value.lastIndexOf('.');
    if (dot > 0 && value.length > 42) {
        const extension = value.slice(dot);
        const stemBudget = Math.max(12, 39 - extension.length);
        heading.textContent = value.slice(0, stemBudget).trimEnd() + '…' + extension;
        heading.title = value;
    } else {
        heading.textContent = value;
    }
    p.append(heading);
    $('content').append(p);
    return p
};
const button = (text, fn, variant) => {
    let kind = variant;
    if (!kind) {
        if (/(删除|遗忘|撤回|拒绝|停用|撤销|清除|回退)/.test(text)) kind = 'danger';
        else if (/(查看|检索|读取|刷新|检测|取消|中断|停止|暂不|加入题目|开卷|闭卷|不记住|需要练习|选择)/.test(text)) kind = 'secondary';
        else kind = 'primary';
    }
    const b = el('button', text, 'button button-' + kind);
    b.type = 'button';
    b.onclick = () => run(async () => {
        const original = b.textContent;
        const width = Math.ceil(b.getBoundingClientRect().width);
        if (width) b.style.minWidth = width + 'px';
        b.disabled = true;
        b.classList.add('is-loading');
        b.setAttribute('aria-busy', 'true');
        b.replaceChildren(
            el('span', undefined, 'button-spinner'),
            el('span', original)
        );
        try {
            await fn();
            if (!/(查看|检索|读取|检测|查询|刷新|打开|选择|停止|中断)/.test(text)) {
                showToast(text + '已完成');
            }
        } finally {
            b.disabled = false;
            b.classList.remove('is-loading');
            b.removeAttribute('aria-busy');
            b.style.removeProperty('min-width');
            if (b.isConnected) b.textContent = original;
        }
    });
    return b
};
const controlLabel = (title, control, parent, help) => {
    const label = el('label', undefined, 'field');
    label.append(el('span', title, 'field-label'), control);
    if (help) label.append(el('small', help, 'field-help'));
    parent.append(label);
    control.classList.add('control');
    if (!control.getAttribute('aria-label')) control.setAttribute('aria-label', title);
    return control;
};
const openDialog = (title, content, options = {}) => {
    const dialog = $('detailDialog');
    const variant = options.variant || 'modal';
    dialog.dataset.variant = variant;
    dialog.dataset.backdropDismiss = options.dismissOnBackdrop === false ? 'false' : 'true';
    dialog.classList.toggle('detail-drawer', variant === 'drawer');
    dialog.classList.toggle('confirm-dialog', variant === 'confirm');
    $('dialogTitle').textContent = title;
    $('dialogBody').replaceChildren(content);
    if (!dialog.open) dialog.showModal();
};
const closeDialog = () => {
    const dialog = $('detailDialog');
    if (dialog.open) dialog.close();
};
const showToast = (message, tone = 'success') => {
    const toast = el('div', message, `toast toast-${tone}`);
    toast.setAttribute('role', tone === 'error' ? 'alert' : 'status');
    $('toastRegion').append(toast);
    requestAnimationFrame(() => toast.classList.add('visible'));
    setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 180);
    }, 2300);
};
const confirmButton = (label, title, message, fn, variant = 'danger') => {
    const trigger = el('button', label, `button button-${variant}`);
    trigger.type = 'button';
    trigger.onclick = () => {
        const body = el('div', undefined, 'confirm-content');
        body.append(el('p', message));
        const actions = el('div', undefined, 'button-row dialog-actions');
        const cancel = el('button', '取消', 'button button-secondary');
        cancel.type = 'button';
        cancel.onclick = () => $('detailDialog').close();
        const confirm = button(label, async () => {
            await fn();
            $('detailDialog').close();
        }, variant);
        actions.append(cancel, confirm);
        body.append(actions);
        openDialog(title, body, {variant: 'confirm', dismissOnBackdrop: false});
        cancel.focus();
    };
    return trigger;
};
const notificationStorageKey = 'fairy.notifications.v1';
const eventCursorKey = 'fairy.event-cursor.v1';
const notificationRoutes = [
    [/^learning\.chunk_read$/, null, ['learning'], false],
    [/^memory\.|^sources\./, '记忆与来源已更新', ['mind', 'memories', 'chat']],
    [/^learning\./, '学习进度已更新', ['overview', 'mind', 'learning', 'assessments', 'evolution']],
    [/^skill\./, '技能状态已更新', ['skills', 'mac', 'overview']],
    [/^autonomy\./, '自主学习候选已更新', ['evolution', 'flows', 'overview']],
    [/^evolution\./, '进化实验已更新', ['evolution', 'flows']],
    [/^approval\.|^note\./, '待确认操作已更新', ['approvals', 'cards', 'overview']],
    [/^card\./, '卡片已更新', ['cards']],
    [/^model\.recovered/, '模型请求状态已恢复', ['chat', 'models', 'overview']]
];
function loadNotifications() {
    try {
        const data = JSON.parse(localStorage.getItem(notificationStorageKey) || '[]');
        return Array.isArray(data) ? data.filter(item => item && item.id && item.text) : [];
    } catch {
        return [];
    }
}
let notifications = loadNotifications();
function eventMeta(event) {
    const match = notificationRoutes.find(([pattern]) => pattern.test(event.type || ''));
    if (!match) return null;
    return {text: match[1], routes: match[2], notify: match[3] !== false && Boolean(match[1])};
}
function saveNotifications() {
    notifications = notifications.slice(0, 30);
    localStorage.setItem(notificationStorageKey, JSON.stringify(notifications));
    const badge = $('notificationBadge');
    const unread = notifications.filter(item => !item.read).length;
    badge.textContent = unread > 9 ? '9+' : String(unread);
    badge.hidden = unread === 0;
    if (renderedUnread !== null && unread > renderedUnread && unread > 0) {
        badge.classList.remove('badge-pop');
        void badge.offsetWidth;
        badge.classList.add('badge-pop');
    }
    renderedUnread = unread;
}
function addNotification(event, meta) {
    const id = String(event.seq || event.id || crypto.randomUUID());
    if (notifications.some(item => item.id === id)) return;
    notifications.unshift({
        id,
        text: meta.text,
        detail: event.type,
        routes: meta.routes,
        createdAt: event.created_at || new Date().toISOString(),
        read: false
    });
    saveNotifications();
    showSystemNotification(meta);
}
async function showSystemNotification(meta) {
    if (!('Notification' in window) || Notification.permission !== 'granted' || !document.hidden) return;
    const options = {body: meta.text, tag: 'fairy-' + meta.text, silent: false};
    try {
        if ('serviceWorker' in navigator) {
            const registration = await navigator.serviceWorker.ready;
            await registration.showNotification('Fairy', options);
        } else {
            new Notification('Fairy', options);
        }
    } catch {
        // The in-app notification center remains available when system notifications fail.
    }
}
function showNotificationCenter() {
    const body = el('div', undefined, 'notification-center');
    const actions = el('div', undefined, 'button-row');
    if ('Notification' in window) {
        const permission = Notification.permission;
        body.append(el(
            'p',
            permission === 'granted'
                ? '系统通知已授权。页面在后台时，Fairy 会发送简短提醒。'
                : permission === 'denied'
                    ? '系统通知已被浏览器拒绝，请在网站设置中重新允许。'
                    : '系统通知尚未授权；站内通知中心不受影响。',
            'muted'
        ));
        if (permission === 'default') {
            actions.append(button('启用系统通知', async () => {
                await Notification.requestPermission();
                showNotificationCenter();
            }, 'secondary'));
        }
    } else {
        body.append(el('p', '当前浏览器不支持系统通知；站内通知中心仍可使用。', 'muted'));
    }
    if (notifications.length) {
        actions.append(button('全部标为已读', async () => {
            notifications = notifications.map(item => ({...item, read: true}));
            saveNotifications();
            showNotificationCenter();
        }, 'secondary'), button('清空通知', async () => {
            notifications = [];
            saveNotifications();
            showNotificationCenter();
        }, 'danger'));
    }
    body.append(actions);
    if (!notifications.length) {
        body.append(el('p', '还没有后台更新。', 'muted'));
    }
    for (const item of notifications) {
        const row = el('button', undefined, 'notification-row');
        row.type = 'button';
        row.append(
            el('strong', item.text),
            el('small', new Date(item.createdAt).toLocaleString() + ' · ' + item.detail),
            el('span', item.read ? '已读' : '未读', item.read ? 'tag' : 'tag tag-unread')
        );
        row.onclick = () => {
            item.read = true;
            saveNotifications();
            $('detailDialog').close();
            if (item.routes?.[0]) location.hash = item.routes[0];
        };
        body.append(row);
    }
    openDialog('通知中心', body, {variant: 'drawer'});
}
function showSyncNotice(event, meta) {
    pendingUpdates += 1;
    const text = meta.text || '当前页面数据已更新';
    $('syncNoticeText').textContent = `${text}${pendingUpdates > 1 ? `（${pendingUpdates} 项）` : ''}`;
    $('syncNotice').hidden = false;
}
function scheduleReminders(cards) {
    const active = new Set();
    for (const card of cards) {
        if (!card.remind_at) continue;
        const at = Date.parse(card.remind_at);
        if (!Number.isFinite(at) || at <= Date.now()) continue;
        const key = `${card.id}:${card.revision}:${card.remind_at}`;
        active.add(key);
        if (reminderTimers.has(key)) continue;
        const delay = Math.min(at - Date.now(), 2_147_000_000);
        const timer = setTimeout(() => {
            reminderTimers.delete(key);
            const meta = {text: `提醒：${card.title}`, routes: ['cards'], notify: true};
            addNotification(
                {id: `reminder:${key}`, type: 'card.reminder_due', created_at: new Date().toISOString()},
                meta
            );
        }, delay);
        reminderTimers.set(key, timer);
    }
    for (const [key, timer] of reminderTimers) {
        if (!active.has(key)) {
            clearTimeout(timer);
            reminderTimers.delete(key);
        }
    }
}
async function run(fn) {
    $('error').textContent = '';
    try {
        await fn()
    } catch (e) {
        const message = String(e?.message || '操作失败');
        const code = message.match(/"([a-z][a-z0-9_]+)"/)?.[1]
            || message.match(/^([a-z][a-z0-9_]+)$/)?.[1];
        $('error').textContent = explain(code || message)
    }
}
async function renderPreservingScroll() {
    const previous = window.scrollY;
    await render();
    requestAnimationFrame(() => window.scrollTo({top: previous, behavior: 'instant'}));
}
const statuses = {
    active: '已保存',
    queued: '等待处理',
    completed: '已完成',
    pending: '正在回应',
    interrupted: '已中断',
    failed: '失败',
    running: '运行中',
    degraded: '降级运行',
    missing: '未启动',
    awaiting_assessment: '待人工验证',
    needs_practice: '需要练习'
};

function records(p, rows) {
    if (!rows.length) p.append(el('p', '暂无记录。', 'muted'));
    for (const r of rows) {
        const row = el('div', undefined, 'row');
        row.append(el('strong', r.title || r.text || r.id));
        const state = r.stage || r.status;
        if (state) row.append(el('p', (statuses[state] || state) + (r.steps_total ? ' · 已核验 ' + r.steps_verified + ' / ' + r.steps_total : ''), 'muted'));
        if (r.reply) row.append(el('p', r.reply));
        if (r.error) row.append(el('p', explain(r.error)));
        if (r.summary) row.append(el('p', r.summary));
        if (r.notes) row.append(el('p', r.notes));
        if (r.remind_at) row.append(el('p', '提醒时间：' + new Date(r.remind_at).toLocaleString(), 'muted'));
        if (r.executable === false) row.append(el('p', '知识条目，无执行权限', 'muted'));
        const details = el('details', undefined, 'record-disclosure');
        const summary = el('summary');
        summary.append(
            el('span', '来源、状态与原始记录'),
            el('span', Object.keys(r).length + ' 个字段', 'disclosure-meta')
        );
        details.append(summary, el('pre', JSON.stringify(r, null, 2)));
        row.append(details);
        p.append(row)
    }
}
async function render() {
    const route = location.hash.slice(1) || 'overview';
    routeDirty = false;
    pendingUpdates = 0;
    $('syncNotice').hidden = true;
    document.querySelector('main').dataset.route = route;
    $('title').textContent = names[route] || 'Fairy';
    $('content').replaceChildren();
    document.querySelectorAll('nav a').forEach(a => {
        const selected = a.hash === '#' + route;
        const overflowSelected = a.dataset.overflow !== undefined
            && !mobilePrimaryRoutes.has(route);
        a.classList.toggle('active', selected || overflowSelected);
        if (selected || overflowSelected) a.setAttribute('aria-current', 'page');
        else a.removeAttribute('aria-current');
    });
    if (!token) {
        panel('连接后读取真实状态').append(el('p', '请输入 FAIRY_TOKEN。没有连接时不会显示模拟成功或进度。'));
        return
    }
    conversation = null;
    const ui = {
        api,
        apiResponse,
        el,
        panel,
        button,
        confirmButton,
        controlLabel,
        openDialog,
        closeDialog,
        refresh: renderPreservingScroll
    };
    beginRouteLoading(route);
    try {
        await renderRoute(route, ui);
    } finally {
        clearRouteSkeleton();
    }
}

async function renderRoute(route, ui) {
    if (route === 'more') {
        const p = panel('更多');
        p.append(ui.el('p', '更多入口按工作、认知、能力与系统分组。', 'muted'));
        const primary = new Set(['overview', 'chat', 'memories', 'learning']);
        for (const [title, routes] of [...navGroups, systemNavGroup]) {
            const available = routes.filter(id => !primary.has(id));
            if (!available.length) continue;
            const group = ui.el('section', undefined, 'more-group');
            group.append(ui.el('h3', title));
            const links = ui.el('div', undefined, 'more-grid');
            for (const id of available) {
                const link = ui.el('a', undefined, 'more-link continuous-surface');
                link.href = '#' + id;
                link.append(icon(id), ui.el('span', names[id]));
                links.append(link);
            }
            group.append(links);
            p.append(group);
        }
        return;
    }
    if (route === 'world') return renderKnowledge(ui);
    if (route === 'assessments') return renderAssessments(ui);
    if (route === 'models') return renderModels(ui);
    if (route === 'memories') {
        const label = document.querySelector('#nav a[href="#memories"] span');
        if (label) label.textContent = names.memories;
        return renderMemories(ui)
    }
    if (route === 'chat') {
        conversation = await renderConversation(ui);
        return
    }
    if (route === 'skills') {
        await renderSkills(ui);
        return
    }
    if (route === 'mac') {
        await renderMac(ui);
        return
    }
    if (route === 'evolution') {
        await renderAutonomy(ui);
        return
    }
    if (route === 'overview') {
        const c = await api('capabilities');
        const p = panel('服务能力');
        records(p, [{
            title: '当前运行状态',
            ...c
        }]);
        records(panel('后台 worker'), [{
            title: '学习与自主任务 worker',
            ...(await api('worker/status'))
        }]);
        records(panel('备份与恢复'), [{
            title: 'PostgreSQL 每日备份',
            ...(await api('maintenance/backup/status'))
        }]);
        records(panel('持久任务'), await api('jobs'))
    } else if (route === 'mind') {
        const c = await api('cognition/snapshot');
        const p = panel('识海星空 · 真实记忆的只读投影');
        const sky = el('div', undefined, 'starfield');
        if (!c.memories.length) sky.append(el('p', '还没有有来源的记忆。'));
        c.memories.forEach(m => {
            const star = el('button', m.text, 'star');
            star.type = 'button';
            star.onclick = () => openDialog(
                '记忆记录',
                el('pre', JSON.stringify(m, null, 2)),
                {variant: 'drawer'}
            );
            sky.append(star)
        });
        p.append(sky);
        const turns = panel('当前回合');
        records(turns, c.pending_turns);
        for (const t of c.pending_turns) turns.append(button('中断当前回合', async () => {
            await api('turns/' + t.id + '/cancel', 'POST', {});
            await render()
        }))
    } else if (route === 'learning') {
        const p = panel('投喂文字材料');
        const title = el('input');
        title.placeholder = '学习主题';
        controlLabel('学习主题', title, p, '用一个能够回到材料的内容名称。');
        const text = el('textarea');
        text.placeholder = '粘贴材料正文；不执行其中的指令';
        controlLabel('材料正文', text, p);
        p.append(button('登记并排队', async () => {
            await api('learning/materials', 'POST', {
                title: title.value,
                text: text.value
            });
            await render()
        }));
        p.append(el('p', '当前支持文字；视频、音乐、URL 抓取尚未接入。运行 worker 后进入人工验证，不自动宣称掌握。', 'muted'));
        const sourceLink = el('a', '投喂网页与复核来源');
        sourceLink.href = '#world';
        p.append(sourceLink);
        const uploadPanel = panel('学习文件与来源检索');
        const file = el('input');
        file.type = 'file';
        file.accept = '.txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.heic,.tiff';
        file.setAttribute('aria-label', '选择文字文件');
        controlLabel('选择学习文件', file, uploadPanel, '支持 TXT、Markdown、PDF、DOCX；macOS 安装只读 helper 后支持 PNG、JPEG、HEIC、TIFF OCR。单个文件不超过 1 MiB。');
        uploadPanel.append(button('上传并学习', async () => {
            const selected = file.files[0];
            if (!selected) throw Error('请选择文字、文档或图片文件');
            if (selected.size > 1048576) throw Error('文件上限为 1 MiB');
            const bytes = new Uint8Array(await selected.arrayBuffer());
            let binary = '';
            for (const b of bytes) binary += String.fromCharCode(b);
            await api('learning/files', 'POST', {
                filename: selected.name,
                content_base64: btoa(binary)
            });
            await render();
        }));
        const query = el('input');
        query.placeholder = '检索学习资料关键词';
        controlLabel('检索关键词', query, uploadPanel);
        const matches = el('div');
        uploadPanel.append(button('检索资料', async () => {
            const data = await api('learning/search?q=' + encodeURIComponent(query.value));
            matches.replaceChildren();
            for (const item of data.results) matches.append(el('p', item.text), el('small', '原文位置 ' + item.start + '–' + item.end + '；来源 ' + item.source_ids[0]));
            if (!data.results.length) matches.append(el('p', '没有匹配到有效资料'))
        }), matches);
        for (const course of await api('learning/courses')) {
            const cp = panel(course.title);
            records(cp, [course]);
            if (!course.source_eligible) cp.append(el('p', '来源已失效，课程不能继续确认或将学习结论归纳为知识。', 'route-note'));
            if (course.total_chunks) cp.append(el('p', '已阅读 ' + course.read_chunks + ' / ' + course.total_chunks + ' 块（不代表掌握）', 'muted'));
            const citations = el('div');
            cp.append(button('查看阅读出处', async () => {
                citations.replaceChildren();
                for (const part of await api('learning/courses/' + course.id + '/chunks')) citations.append(el('p', part.text), el('small', '原文字符位置 ' + part.start + '–' + part.end + (part.locations?.length ? '；' + part.locations.map(x => x.label).join('、') : '')))
            }), citations);

            if (['awaiting_assessment', 'needs_practice'].includes(course.stage)) {
                const answer = el('textarea');
                answer.placeholder = '练习答案';
                const evidence = el('textarea');
                evidence.placeholder = '用于支持答案的原文摘录';
                controlLabel('练习答案', answer, cp);
                controlLabel('原文依据', evidence, cp);
                cp.append(button('提交有出处的练习', async () => {
                    await api('learning/courses/' + course.id + '/practice', 'POST', {
                        revision: course.revision,
                        answer: answer.value,
                        evidence: evidence.value
                    });
                    await render()
                }));
                const practiceList = el('div');
                cp.append(button('查看练习记录', async () => {
                    practiceList.replaceChildren();
                    for (const item of await api('learning/courses/' + course.id + '/practice')) practiceList.append(el('p', item.answer), el('blockquote', item.evidence_quote), el('small', '未自动评分，需人工核对'))
                }), practiceList);
                const evaluation = el('div');
                cp.append(button('评定练习与查看效果', async () => {
                    evaluation.replaceChildren();
                    const report = await api('learning/courses/' + course.id + '/effect');
                    evaluation.append(el('p', '已提交 ' + report.attempts + ' 次，历史已复核 ' + report.reviewed_attempts + ' 次；' + (report.source_eligible ? '当前最近分数 ' + (report.latest_score ?? '暂无') + ' / 5' : '来源已失效，当前没有有效分数；历史最近分数 ' + (report.historical_latest_score ?? '暂无') + ' / 5') + '（人工量表，不代表通用能力）'));
                    if (report.model_assessment_runs) {
                        evaluation.append(el('p', '关联的本地模型固定题目测验已完成 ' + report.model_assessment_runs + ' 次；最近一次答对 ' + report.model_assessment_latest.correct_count + ' / ' + report.model_assessment_latest.total + '（' + report.model_assessment_latest.mode + '）。'));
                    }
                    for (const item of await api('learning/courses/' + course.id + '/practice')) {
                        const box = el('div', undefined, 'memory-row');
                        box.append(el('p', item.answer), el('blockquote', item.evidence_quote));
                        const score = el('input');
                        score.type = 'number';
                        score.min = 0;
                        score.max = 5;
                        score.value = item.score ?? 0;
                        score.setAttribute('aria-label', '练习评分');
                        const feedback = el('input');
                        feedback.placeholder = '评定理由与不足';
                        controlLabel('评分（0–5）', score, box);
                        controlLabel('评定理由', feedback, box);
                        box.append(button('保存练习评定', async () => {
                            await api('learning/practice/' + item.id, 'PATCH', {
                                revision: item.revision,
                                score: Number(score.value),
                                feedback: feedback.value
                            });
                            await render()
                        }));
                        evaluation.append(box)
                    }
                }), evaluation);
                const proof = el('textarea');
                proof.placeholder = '填写用于最终确认的逐字原文依据';
                controlLabel('最终确认依据', proof, cp);
                cp.append(button('记录通过', async () => {
                    await api('learning/courses/' + course.id + '/assess', 'POST', {
                        revision: course.revision,
                        passed: true,
                        evidence: proof.value
                    });
                    await render()
                }), button('需要练习', async () => {
                    await api('learning/courses/' + course.id + '/assess', 'POST', {
                        revision: course.revision,
                        passed: false,
                        evidence: proof.value
                    });
                    await render()
                }))
            }
            if (course.mastered) cp.append(button('归纳为习得知识', async () => {
                await api('skills/acquired?course_id=' + encodeURIComponent(course.id), 'POST', {});
                location.hash = 'skills'
            }))
        }
    } else if (route === 'cards') {
        const p = panel('自建卡片');
        const title = el('input');
        title.placeholder = '标题';
        controlLabel('标题', title, p);
        const text = el('textarea');
        text.placeholder = '内容';
        const subtype = el('select');
        const remindAt = el('input');
        remindAt.type = 'datetime-local';
        Object.entries({
            note: '便笺',
            todo: '待办',
            reminder: '提醒',
            anniversary: '纪念日'
        }).forEach(([x, label]) => {
            const o = el('option', label);
            o.value = x;
            subtype.append(o)
        });
        controlLabel('卡片类型', subtype, p);
        controlLabel('内容', text, p);
        controlLabel('提醒时间（可选）', remindAt, p, '页面打开或安装为 PWA 时，到点触发站内通知；完整后台推送仍需 APNs 或 Web Push。');
        p.append(button('创建卡片', async () => {
            await api('cards', 'POST', {
                title: title.value,
                text: text.value,
                subtype: subtype.value,
                remind_at: remindAt.value ? new Date(remindAt.value).toISOString() : null
            });
            await render()
        }));
        p.append(el('p', '自建卡没有审批或执行语义。到点提醒在页面打开或 PWA 活跃时生效。', 'muted'));
        const cards = await api('cards');
        scheduleReminders(cards);
        records(panel('已保存卡片'), cards)
    } else if (route === 'approvals') {
        const p = panel('提出保存笔记操作');
        const title = el('input');
        title.placeholder = '笔记标题';
        controlLabel('笔记标题', title, p);
        const text = el('textarea');
        text.placeholder = '笔记正文';
        controlLabel('笔记正文', text, p);
        p.append(button('生成待确认项', async () => {
            await api('approvals', 'POST', {
                title: title.value,
                text: text.value
            });
            await render()
        }));
        p.append(el('p', '此处仅支持保存站内笔记。批准不会授予 Mac 或其他工具权限。', 'muted'));
        for (const a of await api('approvals')) {
            const cp = panel(a.title);
            cp.append(el('p', a.text), el('p', a.decision || '等待确认', 'muted'));
            if (!a.decision && Date.parse(a.expires_at) > Date.now())
                for (const [label, choice] of [
                        ['批准一次', 'allow_once'],
                        ['拒绝', 'reject']
                    ]) cp.append(button(label, async () => {
                    await api('approvals/' + a.id + '/choices', 'POST', {
                        revision: a.revision,
                        action_digest: a.digest,
                        choice
                    });
                    await render()
                }))
        }
        records(panel('已执行的站内笔记'), await api('notes'))
    } else if (route === 'pet') {
        const configs = await api('config');
        const conf = configs[0] || {
            revision: 0,
            daily_minutes: 45,
            pet_enabled: false
        };
        const p = panel('服务配置');
        const check = el('input');
        check.type = 'checkbox';
        check.checked = conf.pet_enabled;
        check.setAttribute('aria-label', '允许桌宠');
        const label = el('label', undefined, 'check');
        label.append(check, el('span', '允许桌宠（偏好，不代表本机已显示）'));
        const mins = el('input');
        mins.type = 'number';
        mins.min = 0;
        mins.max = 240;
        mins.value = conf.daily_minutes;
        p.append(label);
        controlLabel('规划学习预算（分钟）', mins, p, '当前设为 0 可暂停队列。');
        p.append(button('保存版本', async () => {
            await api('config', 'PUT', {
                revision: conf.revision,
                daily_minutes: Number(mins.value),
                pet_enabled: check.checked,
                mac_execute: Boolean(conf.mac_execute),
                mac_file_write: Boolean(conf.mac_file_write),
                autonomous_paid: false,
                mac_allowed_apps: conf.mac_allowed_apps || [],
                mac_allowed_paths: conf.mac_allowed_paths || [],
                autonomy_enabled: Boolean(conf.autonomy_enabled),
                autonomy_daily_minutes: conf.autonomy_daily_minutes ?? 30,
                autonomy_daily_items: conf.autonomy_daily_items ?? 10,
                source_refresh_enabled: Boolean(conf.source_refresh_enabled),
                source_refresh_interval_hours: conf.source_refresh_interval_hours ?? 24,
                source_refresh_daily_limit: conf.source_refresh_daily_limit ?? 5,
                source_allowed_hosts: conf.source_allowed_hosts || []
            });
            await render()
        }));
        p.append(el('p', '桌宠在 macOS 原生 Fairy 中显示；此偏好同步到菜单栏和桌面悬浮面板。Web 管理端不渲染桌宠，也不会触发采集或操作。', 'muted'))
    } else if (route === 'flows') {
        const p = panel('真实事件轨迹');
        records(p, await api('events'));
        p.append(el('p', '设计流程见 docs/reference/diagrams；此处只显示已持久化事件。', 'muted'))
    } else if (route === 'world') {
        const add = panel('从材料保存可核对的记忆');
        const source = el('input');
        source.placeholder = '学习材料或对话证据 ID';
        const quote = el('textarea');
        quote.placeholder = '逐字摘录原文';
        add.append(source, quote, button('保存有来源记忆', async () => {
            await api('memories', 'POST', {
                text: quote.value,
                source_ids: [source.value.trim()]
            });
            await render()
        }));
        const p = panel('来源记忆检索');
        const q = el('input');
        q.placeholder = '关键词';
        const out = el('div');
        p.append(q, button('搜索', async () => {
            out.replaceChildren();
            const r = await api('memories?q=' + encodeURIComponent(q.value));
            out.append(el('p', r.reason));
            records(out, r.results)
        }), out)
    } else {
        panel(names[route] || route).append(el('p', '该模块已有设计契约，运行能力尚未实现。不会执行 Mac 动作、自动发布代码或模拟成功。'))
    }
}

for (const [title, routes] of [...navGroups, systemNavGroup]) {
    const group = el('div', undefined, 'nav-group');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', title);
    group.append(el('p', title, 'nav-group-title'));
    const target = title === systemNavGroup[0] ? $('systemNav') : $('nav');
    for (const id of routes) {
        const a = el('a');
        a.href = '#' + id;
        a.append(icon(id), el('span', names[id]));
        group.append(a);
    }
    target.append(group);
}
window.addEventListener('hashchange', () => run(render));
$('login').onsubmit = e => {
    e.preventDefault();
    token = $('token').value;
    $('token').value = '';
    run(async () => {
        await api('capabilities');
        $('status').textContent = '已连接本机服务';
        document.body.classList.add('connected');
        document.body.classList.remove('offline');
        if (stopEvents) stopEvents();
        const head = await api('events/head');
        const storedCursor = Number(localStorage.getItem(eventCursorKey) || '0');
        const initialCursor = Number.isFinite(storedCursor) && storedCursor > 0
            ? storedCursor
            : head.seq || 0;
        localStorage.setItem(eventCursorKey, String(initialCursor));
        stopEvents = watchEvents(() => token, event => {
            localStorage.setItem(eventCursorKey, String(event.seq || initialCursor));
            const meta = eventMeta(event);
            if (meta?.notify) addNotification(event, meta);
            if (conversation) {
                conversation.onEvent(event);
                clearTimeout(eventRefresh);
                eventRefresh = setTimeout(() => run(() => conversation?.refresh()), 100)
            }
            if (meta?.routes.includes('memories')) {
                const label = document.querySelector('#nav a[href="#memories"] span');
                if (label) label.textContent = '记忆审阅 · 有更新';
            }
            const currentRoute = location.hash.slice(1) || 'overview';
            if (meta?.routes.includes(currentRoute) && currentRoute !== 'chat') {
                clearTimeout(eventRefresh);
                if (routeDirty || document.activeElement?.closest('#content input, #content textarea, #content select')) {
                    showSyncNotice(event, meta);
                } else {
                    eventRefresh = setTimeout(() => {
                        if (
                            routeDirty
                            || document.activeElement?.closest('#content input, #content textarea, #content select')
                        ) {
                            showSyncNotice(event, meta);
                        } else {
                            run(renderPreservingScroll);
                        }
                    }, 180);
                }
            }
        }, online => {
            document.body.classList.toggle('offline', !online);
            $('status').textContent = online ? '已连接本机服务' : '连接中断，正在重连……'
        }, initialCursor);
        await render()
        scheduleReminders(await api('cards'))
    })
};
run(render);
saveNotifications();

window.addEventListener('beforeunload', () => stopEvents?.());

$('content').addEventListener('input', () => {
    routeDirty = true;
});
$('content').addEventListener('change', () => {
    routeDirty = true;
});
$('syncRefresh').onclick = () => run(renderPreservingScroll);
$('notificationButton').onclick = () => {
    showNotificationCenter();
};

const detailDialog = $('detailDialog');
detailDialog.addEventListener('click', event => {
    if (event.target.closest('[data-close-dialog]')) {
        detailDialog.close();
    } else if (event.target === detailDialog && detailDialog.dataset.backdropDismiss !== 'false') {
        detailDialog.close();
    }
});

const sidebarResizer = $('sidebarResizer');
const sidebarMinimum = 208;
const sidebarMaximum = 360;
const defaultSidebarWidth = 238;
let sidebarWidth = Math.min(
    sidebarMaximum,
    Math.max(
        sidebarMinimum,
        Number(localStorage.getItem('fairy.sidebar-width') || defaultSidebarWidth)
    )
);
const setSidebarWidth = (value, persist = false) => {
    sidebarWidth = Math.round(Math.min(sidebarMaximum, Math.max(sidebarMinimum, value)));
    document.documentElement.style.setProperty('--sidebar-width', sidebarWidth + 'px');
    sidebarResizer.setAttribute('aria-valuemin', String(sidebarMinimum));
    sidebarResizer.setAttribute('aria-valuemax', String(sidebarMaximum));
    sidebarResizer.setAttribute('aria-valuenow', String(sidebarWidth));
    if (persist) localStorage.setItem('fairy.sidebar-width', String(sidebarWidth));
};
setSidebarWidth(sidebarWidth);
sidebarResizer.addEventListener('pointerdown', event => {
    if (matchMedia('(max-width: 780px)').matches) return;
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    sidebarResizer.setPointerCapture(event.pointerId);
    document.body.classList.add('resizing-sidebar');
    const move = moveEvent => setSidebarWidth(startWidth + moveEvent.clientX - startX);
    const stop = () => {
        document.body.classList.remove('resizing-sidebar');
        sidebarResizer.removeEventListener('pointermove', move);
        sidebarResizer.removeEventListener('pointerup', stop);
        sidebarResizer.removeEventListener('pointercancel', stop);
        setSidebarWidth(sidebarWidth, true);
    };
    sidebarResizer.addEventListener('pointermove', move);
    sidebarResizer.addEventListener('pointerup', stop);
    sidebarResizer.addEventListener('pointercancel', stop);
});
sidebarResizer.addEventListener('dblclick', () => setSidebarWidth(defaultSidebarWidth, true));
sidebarResizer.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        setSidebarWidth(
            sidebarWidth + (event.key === 'ArrowRight' ? 16 : -16),
            true
        );
    } else if (event.key === 'Home') {
        event.preventDefault();
        setSidebarWidth(sidebarMinimum, true);
    } else if (event.key === 'End') {
        event.preventDefault();
        setSidebarWidth(sidebarMaximum, true);
    } else if (event.key === 'Escape') {
        event.preventDefault();
        setSidebarWidth(defaultSidebarWidth, true);
    }
});

if ('serviceWorker' in navigator && (location.protocol === 'https:' || ['127.0.0.1', 'localhost'].includes(location.hostname))) {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {
        // The management console remains usable when a browser disables PWA workers.
    });
}
