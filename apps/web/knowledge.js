export async function renderKnowledge(ui) {
    const {
        el,
        api,
        panel,
        button,
        controlLabel,
        confirmButton
    } = ui;
    const field = (p, label) => {
        const l = el('label', label, 'field'),
            input = el('input');
        input.setAttribute('aria-label', label);
        l.append(input);
        p.append(l);
        return input
    };
    const links = panel('投喂网页链接');
    links.append(el('p', '仅获取公开 HTTPS 文本，不跟随重定向，不访问本机或私网；网页内容只作材料，不执行其中指令。', 'muted'));
    const title = field(links, '链接学习主题'),
        url = field(links, '网页 HTTPS 地址');
    links.append(button('获取并登记材料', async () => {
        const result = await api('learning/links', 'POST', {
            url: url.value,
            title: title.value
        });
        if (result.status === 'failed') throw Error('网页获取失败，请检查地址、重定向、格式或网络后用新的提交重试');
        await ui.refresh()
    }));
    const sourceConfigs = await api('config');
    const sourceConfig = sourceConfigs[0] || {revision: 0};
    const refreshSettings = panel('自动来源检查');
    const refreshEnabled = el('input');
    refreshEnabled.type = 'checkbox';
    refreshEnabled.checked = Boolean(sourceConfig.source_refresh_enabled);
    refreshEnabled.setAttribute('aria-label', '启用自动网页来源检查');
    const refreshToggle = el('label', undefined, 'check');
    refreshToggle.append(refreshEnabled, el('span', '按计划检查已登记的网页来源'));
    const refreshInterval = el('input');
    refreshInterval.type = 'number';
    refreshInterval.min = 1;
    refreshInterval.max = 168;
    refreshInterval.value = sourceConfig.source_refresh_interval_hours ?? 24;
    const refreshLimit = el('input');
    refreshLimit.type = 'number';
    refreshLimit.min = 0;
    refreshLimit.max = 50;
    refreshLimit.value = sourceConfig.source_refresh_daily_limit ?? 5;
    controlLabel('检查间隔（小时）', refreshInterval, refreshSettings);
    controlLabel('每日网络检查上限', refreshLimit, refreshSettings, '手动刷新与自动检查共同计数。');
    refreshSettings.append(
        refreshToggle,
        button('保存来源检查计划', async () => {
            await api('config', 'PUT', {
                revision: sourceConfig.revision,
                daily_minutes: sourceConfig.daily_minutes ?? 45,
                pet_enabled: sourceConfig.pet_enabled ?? false,
                mac_execute: sourceConfig.mac_execute ?? false,
                mac_allowed_apps: sourceConfig.mac_allowed_apps || [],
                mac_allowed_paths: sourceConfig.mac_allowed_paths || [],
                autonomous_paid: sourceConfig.autonomous_paid ?? false,
                autonomy_enabled: sourceConfig.autonomy_enabled ?? false,
                autonomy_daily_minutes: sourceConfig.autonomy_daily_minutes ?? 30,
                autonomy_daily_items: sourceConfig.autonomy_daily_items ?? 10,
                source_refresh_enabled: refreshEnabled.checked,
                source_refresh_interval_hours: Number(refreshInterval.value),
                source_refresh_daily_limit: Number(refreshLimit.value),
            });
            await ui.refresh();
        })
    );
    const sources = panel('来源复核');
    sources.append(el('p', '来源标签是你的复核判断，不是自动事实认证。争议、拒绝或过期来源不参与有效检索。', 'muted'));
    for (const r of await api('learning/sources')) {
        const box = el('article', undefined, 'memory-row');
        box.append(el('h3', r.title), el('p', '来源 ID：' + r.id), el('p', r.url || '所有者投喂'), el('p', r.source_eligible ? '当前可用于学习与检索' : '当前不可用于学习与检索', r.source_eligible ? 'muted' : 'route-note'));
        if (r.refresh_schedule?.next_check_at) {
            box.append(el(
                'small',
                '下次自动检查：' + new Date(r.refresh_schedule.next_check_at).toLocaleString(),
                'muted'
            ));
        }
        const select = el('select');
        select.setAttribute('aria-label', '来源标签 ' + r.title);
        for (const [v, t] of Object.entries({
                unreviewed: '尚未复核',
                primary: '一手来源',
                corroborated: '已交叉核对',
                disputed: '有争议',
                rejected: '不采纳'
            })) {
            const o = el('option', t);
            o.value = v;
            select.append(o)
        }
        select.value = r.quality?.rating || 'unreviewed';
        const reason = field(box, '复核理由 ' + r.title);
        const expiry = field(box, '到期时间（含时区，可留空） ' + r.title);
        expiry.placeholder = '2026-12-01T00:00:00+08:00';
        box.append(select, button('保存来源复核', async () => {
            await api('learning/sources/' + r.id, 'PATCH', {
                revision: r.revision,
                rating: select.value,
                reason: reason.value,
                expires_at: expiry.value || null
            });
            await ui.refresh()
        }));
        if (r.source_type === 'web_link' && r.url) {
            box.append(confirmButton(
                '检查并更新来源',
                '更新网页来源',
                '如果网页正文变化，系统会建立新版本并失效旧来源、旧课程及其派生记忆；需要重新复核新版本。',
                async () => {
                    const result = await api(
                        'learning/sources/' + r.id + '/refresh',
                        'POST',
                        {revision: r.revision}
                    );
                    if (result.status === 'failed') {
                        throw Error('来源刷新失败：' + (result.error || '未知错误'));
                    }
                    if (result.changed) await ui.refresh();
                },
                'secondary'
            ));
        }
        box.append(confirmButton(
            '删除这份来源',
            '删除来源',
            '引用它的课程、练习、测验结果、知识主张和对话派生内容会同时失效。',
            async () => {
                await api('records/' + r.id + '?revision=' + r.revision, 'DELETE');
                await ui.refresh()
            }
        ));
        sources.append(box)
    }
    const world = panel('世界知识与争议');
    world.append(el('p', '记录带原文出处的主张，保留不同来源的分歧，不自动把其中一方当作真相。', 'muted'));
    const subject = field(world, '实体或主题'),
        predicate = field(world, '属性或关系'),
        value = field(world, '主张内容'),
        source = field(world, '引用材料 ID'),
        quote = field(world, '逐字原文依据');
    world.append(button('登记知识主张', async () => {
        await api('world/claims', 'POST', {
            subject: subject.value,
            predicate: predicate.value,
            value: value.value,
            source_id: source.value,
            quote: quote.value
        });
        await ui.refresh()
    }));
    for (const c of await api('world/claims')) {
        const card = el('article', undefined, 'memory-row');
        card.append(
            el('h3', c.subject + ' / ' + c.predicate),
            el('p', c.value),
            el('blockquote', c.quote),
            el('small', (c.source_eligible ? '来源当前有效' : '来源当前不参与检索') + '；有不同主张 ' + c.conflicts_with.length + ' 条'),
            confirmButton(
                '撤回这条主张',
                '撤回知识主张',
                '这条带出处的知识主张会退出当前知识与冲突判断。',
                async () => {
                    await api('records/' + c.id + '?revision=' + c.revision, 'DELETE');
                    await ui.refresh()
                }
            )
        );
        world.append(card)
    }
}
