const evolutionSample = {
    name: '回答约束实验',
    baseline: 'baseline',
    cases: [
        {input: '水的颜色', required_terms: ['无色', '适用条件'], forbidden_terms: ['百分之百']},
        {input: '未知信息', required_terms: ['不确定'], forbidden_terms: ['已确认']},
    ],
    candidates: [
        {name: 'baseline', outputs: ['水通常无色。', '我不确定。']},
        {name: 'candidate', outputs: ['水通常无色，并注明适用条件。', '目前不确定。']},
    ],
};

export async function renderAutonomy(ui) {
    const {el, api, panel, button, controlLabel, confirmButton} = ui;
    const configs = await api('config');
    const config = configs[0] || {
        revision: 0, daily_minutes: 45, pet_enabled: false,
        mac_allowed_apps: [], mac_allowed_paths: [],
        autonomy_enabled: false, autonomy_daily_minutes: 30,
        autonomy_daily_items: 10,
    };
    const autonomy = panel('自主预算');
    autonomy.append(el('p', '自主候选只从学习缺口和知识冲突中产生。后台默认关闭，接受候选时会占用独立预算。', 'muted'));
    const enabled = el('input');
    enabled.type = 'checkbox';
    enabled.checked = Boolean(config.autonomy_enabled);
    enabled.setAttribute('aria-label', '启用自主候选');
    const minutes = el('input');
    minutes.type = 'number';
    minutes.min = 0;
    minutes.max = 240;
    minutes.value = config.autonomy_daily_minutes;
    minutes.setAttribute('aria-label', '每日自主分钟');
    const items = el('input');
    items.type = 'number';
    items.min = 0;
    items.max = 100;
    items.value = config.autonomy_daily_items;
    items.setAttribute('aria-label', '每日自主候选数');
    const metrics = el('div', undefined, 'metric-grid');
    const minuteMetric = el('article', undefined, 'metric');
    const minuteValue = el('strong', '0 / 0');
    const minuteProgress = el('progress');
    minuteMetric.append(el('span', '今日时长', 'metric-label'), minuteValue, minuteProgress);
    const itemMetric = el('article', undefined, 'metric');
    const itemValue = el('strong', '0 / 0');
    const itemProgress = el('progress');
    itemMetric.append(el('span', '自主候选', 'metric-label'), itemValue, itemProgress);
    metrics.append(minuteMetric, itemMetric);
    const animateValue = (element, target, suffix) => {
        const from = Number(element.dataset.value || 0);
        element.dataset.value = String(target);
        if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
            element.textContent = target + suffix;
            return;
        }
        const started = performance.now();
        const duration = 260;
        const frame = now => {
            const progress = Math.min(1, (now - started) / duration);
            const eased = 1 - (1 - progress) ** 3;
            element.textContent = Math.round(from + (target - from) * eased) + suffix;
            if (progress < 1) requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
    };
    const refreshBudget = async () => {
        const budget = await api('autonomy/budget');
        animateValue(minuteValue, budget.used_minutes, ' / ' + budget.daily_minutes);
        animateValue(itemValue, budget.used_items, ' / ' + budget.daily_items);
        minuteProgress.max = Math.max(1, budget.daily_minutes);
        minuteProgress.value = budget.used_minutes;
        itemProgress.max = Math.max(1, budget.daily_items);
        itemProgress.value = budget.used_items;
    };
    const enabledLabel = el('label', undefined, 'check');
    enabledLabel.append(enabled, el('span', '启用受预算约束的自主候选'));
    autonomy.append(enabledLabel);
    controlLabel('每日自主时长（分钟）', minutes, autonomy);
    controlLabel('每日候选数量', items, autonomy);
    autonomy.append(
        button('保存自主预算', async () => {
            await api('config', 'PUT', {
                revision: config.revision,
                daily_minutes: config.daily_minutes,
                pet_enabled: config.pet_enabled,
                mac_execute: Boolean(config.mac_execute),
                autonomous_paid: false,
                mac_allowed_apps: config.mac_allowed_apps || [],
                mac_allowed_paths: config.mac_allowed_paths || [],
                autonomy_enabled: enabled.checked,
                autonomy_daily_minutes: Number(minutes.value),
                autonomy_daily_items: Number(items.value),
            });
            await ui.refresh();
        }),
        metrics
    );
    await refreshBudget();

    const queue = panel('学习与冲突候选');
    queue.append(
        button('从当前缺口刷新候选', async () => {
            await api('autonomy/refresh', 'POST', {});
            await ui.refresh();
        })
    );
    for (const candidate of await api('autonomy/candidates')) {
        if (candidate.status !== 'proposed') continue;
        const row = el('article', undefined, 'memory-row autonomy-card');
        row.append(
            el('h3', candidate.title),
            el('p', candidate.reason),
            el('p', candidate.question),
            el('small', candidate.estimated_minutes + ' 分钟 · ' + candidate.origin),
            button('接受并加入目标', async () => {
                await api('autonomy/candidates/' + candidate.id + '/accept', 'POST', {
                    revision: candidate.revision,
                });
                await ui.refresh();
            }),
            button('暂不处理', async () => {
                await api('autonomy/candidates/' + candidate.id + '/dismiss', 'POST', {
                    revision: candidate.revision,
                });
                await ui.refresh();
            })
        );
        queue.append(row);
    }

    const goalsPanel = panel('自主执行账本');
    goalsPanel.append(el(
        'p',
        '启动后才计入实际执行时间；完成时结算实际时长并释放未使用预留。',
        'muted'
    ));
    const goals = await api('autonomy/goals');
    const goalState = {
        planned: '待启动',
        active: '执行中',
        paused: '已暂停',
        completed: '已完成',
        cancelled: '已取消',
    };
    if (!goals.length) {
        goalsPanel.append(el('p', '接受一个候选后会在这里生成可启动的目标。', 'muted'));
    }
    for (const goal of goals) {
        const row = el('article', undefined, 'memory-row autonomy-card');
        const reservedMinutes = goal.reserved_minutes ?? goal.estimated_minutes;
        const progress = el('progress');
        progress.max = Math.max(1, reservedMinutes * 60);
        progress.value = Math.min(goal.spent_seconds || 0, reservedMinutes * 60);
        row.append(
            el('h3', goal.title),
            el('p', goal.reason),
            el('small', `预留 ${reservedMinutes} 分钟 · 已执行 ${goal.actual_minutes || 0} 分钟 · ${goalState[goal.status] || goal.status}`),
            progress
        );
        if (goal.pause_reason) {
            row.append(el(
                'p',
                goal.pause_reason === 'budget_exhausted' ? '已达到预留预算并自动暂停。' : '已由你暂停。',
                'route-note'
            ));
        }
        if (goal.summary) row.append(el('p', goal.summary));

        if (goal.status === 'planned') {
            row.append(button('开始执行', async () => {
                await api('autonomy/goals/' + goal.id + '/start', 'POST', {
                    revision: goal.revision,
                });
                await ui.refresh();
            }));
        } else if (goal.status === 'active') {
            row.append(button('暂停并保留进度', async () => {
                await api('autonomy/goals/' + goal.id + '/pause', 'POST', {
                    revision: goal.revision,
                });
                await ui.refresh();
            }));
        } else if (goal.status === 'paused') {
            row.append(button('继续执行', async () => {
                await api('autonomy/goals/' + goal.id + '/start', 'POST', {
                    revision: goal.revision,
                });
                await ui.refresh();
            }));
        }
        if (['active', 'paused'].includes(goal.status)) {
            const summary = el('textarea');
            controlLabel('完成结果与验证依据', summary, row);
            row.append(button('完成并结算', async () => {
                await api('autonomy/goals/' + goal.id + '/complete', 'POST', {
                    revision: goal.revision,
                    summary: summary.value,
                });
                await ui.refresh();
            }));
        }
        if (['planned', 'active', 'paused'].includes(goal.status)) {
            row.append(confirmButton(
                '取消目标并释放预留',
                '取消自主目标',
                '已执行时间仍会保留在当日账本，剩余预留会释放。',
                async () => {
                    await api('autonomy/goals/' + goal.id + '/cancel', 'POST', {
                        revision: goal.revision,
                    });
                    await ui.refresh();
                },
                'secondary'
            ));
        }
        goalsPanel.append(row);
    }

    const lab = panel('隔离进化实验');
    lab.append(el('p', '固定用例由所有者提供，候选输出只在记录中比较。评分器不可被候选修改，实验通过也不会自动部署运行版本。', 'muted'));
    const experimentInput = el('textarea');
    experimentInput.value = JSON.stringify(evolutionSample, null, 2);
    controlLabel('实验用例与候选输出（JSON）', experimentInput, lab, '固定输入只用于隔离比较，不会自动改动运行版本。');
    lab.append(button('运行隔离评测', async () => {
        let body;
        try {
            body = JSON.parse(experimentInput.value);
        } catch {
            throw Error('实验 JSON 格式不正确');
        }
        await api('evolution/experiments', 'POST', body);
        await ui.refresh();
    }));
    for (const experiment of (await api('evolution/experiments')).reverse()) {
        const row = el('article', undefined, 'memory-row evolution-card');
        row.append(
            el('h3', experiment.name),
            el('p', '基准 ' + experiment.baseline + '：' + experiment.baseline_score.toFixed(2)),
            el('p', '推荐 ' + experiment.winner + '：' + experiment.winner_score.toFixed(2)),
            el('small', experiment.recommendation + ' · 运行版本未改变'),
        );
        if (experiment.status === 'evaluated' && experiment.recommendation === 'review_candidate') {
            row.append(button('记录为待人工评审', async () => {
                await api('evolution/experiments/' + experiment.id + '/approve', 'POST', {
                    candidate: experiment.winner,
                });
                await ui.refresh();
            }));
        }
        if (experiment.status !== 'rolled_back') {
            row.append(confirmButton(
                '回退实验记录',
                '回退进化实验',
                '实验记录会标记为已回退；运行版本不会发生改变。',
                async () => {
                    await api('evolution/experiments/' + experiment.id + '/rollback', 'POST', {});
                    await ui.refresh();
                },
                'secondary'
            ));
        }
        lab.append(row);
    }
}
