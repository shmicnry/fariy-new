export async function renderSkills(ui) {
    const {el, api, panel, button, controlLabel, confirmButton} = ui;
    const acquired = panel('习得知识');
    const learned = await api('skills');
    if (!learned.length) acquired.append(el('p', '还没有完成验证的习得知识。', 'muted'));
    for (const skill of learned) {
        const row = el('article', undefined, 'memory-row');
        row.append(el('h3', skill.title), el('p', skill.summary || '已获得有来源的知识条目', 'muted'), el('small', '知识型条目 · 无执行权限'));
        acquired.append(row);
    }

    const registry = panel('可执行技能');
    const lifecycle = el('div', undefined, 'lifecycle-legend');
    for (const [index, label] of ['安装', '授权', '启用', '执行'].entries()) {
        const step = el('span', label);
        step.dataset.step = String(index + 1);
        lifecycle.append(step);
    }
    registry.append(lifecycle);
    for (const skill of await api('skills/registry')) {
        const row = el('article', undefined, 'memory-row skill-card');
        const stage = !skill.installed ? 1 : !skill.enabled ? 2 : 4;
        const state = !skill.installed ? '未安装' : !skill.enabled ? '待授权' : '可执行';
        row.append(
            el('h3', skill.name),
            el('p', skill.purpose),
            el('span', state, 'tag skill-state'),
            el('small', skill.version + ' · ' + skill.permissions.join('、'), 'skill-meta')
        );
        row.dataset.stage = String(stage);
        if (!skill.installed) {
            row.append(button('安装并检查', async () => {
                await api('skills/registry/' + skill.id + '/install', 'POST', {});
                await ui.refresh()
            }));
        } else if (!skill.enabled) {
            const expiry = el('input');
            expiry.type = 'number';
            expiry.min = 1;
            expiry.max = 1440;
            expiry.value = 60;
            row.append(el('p', '已安装，尚未授权。', 'route-note'));
            controlLabel('授权分钟数', expiry, row, '授权到期后自动失效。');
            row.append(
                button('确认授权并启用', async () => {
                    await api('skills/registry/' + skill.id + '/grant', 'POST', {
                        revision: skill.revision,
                        permissions: skill.permissions,
                        expires_minutes: Number(expiry.value),
                    });
                    await ui.refresh()
                })
            );
        } else {
            const input = el('input');
            input.placeholder = skill.implementation === 'learning_search'
                ? '输入检索词'
                : skill.implementation === 'mac_ax_tree'
                    ? '应用 Bundle ID；留空读取前台应用'
                : skill.implementation === 'mac_open_app'
                    ? '输入允许列表中的准确应用名称'
                    : '此技能无需输入';
            input.setAttribute('aria-label', '技能调用参数');
            const output = el('pre', '', 'skill-output');
            const needsInput = ['learning_search', 'mac_open_app', 'mac_ax_tree'].includes(skill.implementation);
            row.append(
                el('p', '已启用，授权到期后自动失效。', 'muted')
            );
            if (needsInput) {
                const inputLabel = skill.implementation === 'mac_ax_tree'
                    ? '应用 Bundle ID（可留空读取前台应用）'
                    : skill.implementation === 'mac_open_app'
                        ? '允许应用'
                        : '检索关键词';
                controlLabel(
                    inputLabel,
                    input,
                    row
                );
            }
            row.append(
                button(skill.implementation === 'mac_open_app' ? '执行允许应用启动' : '只读执行一次', async () => {
                    const result = await api('skills/registry/' + skill.id + '/invoke', 'POST', {
                        query: input.value,
                        path: null,
                    });
                    output.textContent = JSON.stringify(result.result, null, 2);
                }),
                confirmButton(
                    '停用并撤销授权',
                    '停用技能',
                    '该技能当前的限时授权会立即撤销。',
                    async () => {
                        await api('skills/registry/' + skill.id + '/disable', 'POST', {});
                        await ui.refresh()
                    }
                ),
                output
            );
        }
        registry.append(row);
    }
}

export async function renderMac(ui) {
    const {el, api, panel, button, controlLabel} = ui;
    const status = await api('mac/status');
    const permission = value => value === true ? '已授权' : value === false ? '未授权' : '尚未探测';
    const statusPanel = panel('这台 Mac · 只读状态');
    statusPanel.append(
        el('h3', status.platform + ' ' + (status.macos_version || '')),
        el('p', '当前模式：' + status.executor_mode, status.executor_mode === 'observe_only' ? 'route-note' : ''),
        el('p', '辅助功能：' + permission(status.accessibility_permission) + ' · 屏幕录制：' + permission(status.screen_recording_permission), 'muted'),
        el('p', status.arbitrary_shell || status.input_injection || status.screen_capture ? '高风险执行面已开启' : '任意 shell、输入注入和屏幕采集均未启用', 'route-note')
    );
    if (status.helper_version) {
        statusPanel.append(el('p', '只读权限 helper ' + status.helper_version + ' 已连接', 'muted'));
    }
    const apps = await api('mac/apps');
    const appPanel = panel('应用目录');
    appPanel.append(el('p', '只读取应用名称和路径；不会启动应用。', 'muted'));
    const appDetails = el('details');
    appDetails.append(el('summary', '查看 ' + apps.applications.length + ' 个应用的本地目录'));
    for (const app of apps.applications.slice(0, 30)) {
        appDetails.append(el('p', app.name + (app.allowed ? ' · 已列入允许范围' : '')));
    }
    if (!apps.applications.length) appDetails.append(el('p', '没有读取到应用目录。', 'muted'));
    appPanel.append(appDetails);

    const filePanel = panel('允许目录浏览');
    const pathInput = el('input');
    const fileOutput = el('div');
    filePanel.append(el('p', '只能浏览配置中的允许目录；符号链接越界会拒绝。', 'muted'));
    controlLabel('允许目录的绝对路径', pathInput, filePanel);
    filePanel.append(button('读取目录', async () => {
        const result = await api('mac/files?path=' + encodeURIComponent(pathInput.value));
        fileOutput.replaceChildren(el('p', result.path, 'muted'));
        for (const item of result.entries) {
            fileOutput.append(el('p', item.kind + ' · ' + item.name + (item.symlink ? ' · 符号链接' : '')));
        }
    }), fileOutput);

    const configs = await api('config');
    const config = configs[0] || {
        revision: 0, daily_minutes: 45, pet_enabled: false,
        mac_allowed_apps: [], mac_allowed_paths: [],
        autonomy_enabled: false, autonomy_daily_minutes: 30, autonomy_daily_items: 10
    };
    const scope = panel('设备范围预配置');
    const appInput = el('textarea');
    appInput.value = (config.mac_allowed_apps || []).join('\n');
    const pathConfig = el('textarea');
    pathConfig.value = (config.mac_allowed_paths || []).join('\n');
    const execute = el('input');
    execute.type = 'checkbox';
    execute.checked = Boolean(config.mac_execute);
    execute.setAttribute('aria-label', '允许启动允许列表应用');
    const lines = input => input.value.split('\n').map(value => value.trim()).filter(Boolean);
    controlLabel('允许应用', appInput, scope, '应用 Bundle ID 或应用名称，每行一个。');
    controlLabel('允许目录', pathConfig, scope, '允许读取的目录绝对路径，每行一个。');
    const executeLabel = el('label', undefined, 'check');
    executeLabel.append(execute, el('span', '允许技能启动允许列表中的应用'));
    scope.append(
        executeLabel,
        el('p', '这里只允许精确应用名启动；不开放任意 shell、输入注入、屏幕捕获或文件写入。', 'muted'),
        button('保存设备范围', async () => {
        await api('config', 'PUT', {
            revision: config.revision,
            daily_minutes: config.daily_minutes,
            pet_enabled: config.pet_enabled,
            mac_allowed_apps: lines(appInput),
            mac_allowed_paths: lines(pathConfig),
            mac_execute: execute.checked,
            autonomous_paid: false,
            autonomy_enabled: Boolean(config.autonomy_enabled),
            autonomy_daily_minutes: config.autonomy_daily_minutes ?? 30,
            autonomy_daily_items: config.autonomy_daily_items ?? 10,
            source_refresh_enabled: Boolean(config.source_refresh_enabled),
            source_refresh_interval_hours: config.source_refresh_interval_hours ?? 24,
            source_refresh_daily_limit: config.source_refresh_daily_limit ?? 5,
        });
        await ui.refresh();
        })
    );
}
