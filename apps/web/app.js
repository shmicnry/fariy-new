import {
    renderModels,
    renderMemories,
    renderConversation,
    watchEvents
} from './p1.js';
// No user/provider data is inserted as raw HTML. The service token stays in memory only.
let token = '',
    stopEvents = null,
    conversation = null;
let eventRefresh = null;
const names = {
    overview: '运行总览',
    mind: '识海与认知',
    world: '世界与知识',
    memories: '记忆审阅',
    models: '模型与路由',
    learning: '学习中心',
    evolution: '进化实验',
    skills: '技能中心',
    mac: 'Mac 操作',
    flows: '流程管理',
    pet: '桌宠与形象',
    cards: '卡片与通知',
    approvals: '待确认操作',
    chat: '对话'
};
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e
};
async function api(path, method = 'GET', body) {
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
        const x = await r.json();
        throw Error(r.status + ' ' + JSON.stringify(x.detail))
    }
    return r.json()
}
const panel = (title) => {
    const p = el('section', undefined, 'panel');
    p.append(el('h2', title));
    $('content').append(p);
    return p
};
const button = (text, fn) => {
    const b = el('button', text);
    b.onclick = () => run(async () => {
        b.disabled = true;
        try {
            await fn()
        } finally {
            b.disabled = false
        }
    });
    return b
};
async function run(fn) {
    $('error').textContent = '';
    try {
        await fn()
    } catch (e) {
        $('error').textContent = e.message
    }
}
const statuses = {
    active: '已保存',
    queued: '等待处理',
    completed: '已完成',
    pending: '正在回应',
    interrupted: '已中断',
    failed: '失败',
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
        if (r.error) row.append(el('p', r.error === 'model_not_configured' ? '尚未配置模型，请按启动说明设置模型后重试。' : r.error));
        if (r.summary) row.append(el('p', r.summary));
        if (r.notes) row.append(el('p', r.notes));
        if (r.executable === false) row.append(el('p', '知识条目，无执行权限', 'muted'));
        const details = el('details');
        details.append(el('summary', '查看来源与记录'), el('pre', JSON.stringify(r, null, 2)));
        row.append(details);
        p.append(row)
    }
}
async function render() {
    const route = location.hash.slice(1) || 'overview';
    $('title').textContent = names[route] || 'Fairy';
    $('content').replaceChildren();
    document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.hash === '#' + route));
    if (!token) {
        panel('连接后读取真实状态').append(el('p', '请输入 FAIRY_TOKEN。没有连接时不会显示模拟成功或进度。'));
        return
    }
    conversation = null;
    const ui = {
        api,
        el,
        panel,
        button,
        refresh: render
    };
    if (route === 'models') return renderModels(ui);
    if (route === 'memories') {
        document.querySelector('nav a[href="#memories"]').textContent = names.memories;
        return renderMemories(ui)
    }
    if (route === 'chat') {
        conversation = await renderConversation(ui);
        return
    }
    if (route === 'overview') {
        const c = await api('capabilities');
        const p = panel('服务能力');
        records(p, [{
            title: '当前运行状态',
            ...c
        }]);
        records(panel('持久任务'), await api('jobs'))
    } else if (route === 'mind') {
        const c = await api('cognition/snapshot');
        const p = panel('识海星空 · 真实记忆的只读投影');
        const sky = el('div', undefined, 'starfield');
        if (!c.memories.length) sky.append(el('p', '还没有有来源的记忆。'));
        c.memories.forEach(m => {
            const star = el('button', m.text, 'star');
            star.onclick = () => alert(JSON.stringify(m, null, 2));
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
        const text = el('textarea');
        text.placeholder = '粘贴材料正文；不执行其中的指令';
        p.append(title, text, button('登记并排队', async () => {
            await api('learning/materials', 'POST', {
                title: title.value,
                text: text.value
            });
            await render()
        }));
        p.append(el('p', '当前支持文字；视频、音乐、URL 抓取尚未接入。运行 worker 后进入人工验证，不自动宣称掌握。', 'muted'));
        const uploadPanel = panel('学习文件与来源检索');
        const file = el('input');
        file.type = 'file';
        file.accept = '.txt,.md';
        file.setAttribute('aria-label', '选择文字文件');
        uploadPanel.append(file, button('上传并学习', async () => {
            const selected = file.files[0];
            if (!selected) throw Error('请选择 TXT 或 Markdown 文件');
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
        const matches = el('div');
        uploadPanel.append(query, button('检索资料', async () => {
            const data = await api('learning/search?q=' + encodeURIComponent(query.value));
            matches.replaceChildren();
            for (const item of data.results) matches.append(el('p', item.text), el('small', '原文位置 ' + item.start + '–' + item.end + '；来源 ' + item.source_ids[0]));
            if (!data.results.length) matches.append(el('p', '没有匹配到有效资料'))
        }), matches);
        for (const course of await api('learning/courses')) {
            const cp = panel(course.title);
            records(cp, [course]);
            if (course.total_chunks) cp.append(el('p', '已阅读 ' + course.read_chunks + ' / ' + course.total_chunks + ' 块（不代表掌握）', 'muted'));
            const citations = el('div');
            cp.append(button('查看阅读出处', async () => {
                citations.replaceChildren();
                for (const part of await api('learning/courses/' + course.id + '/chunks')) citations.append(el('p', part.text), el('small', '原文字符位置 ' + part.start + '–' + part.end))
            }), citations);

            if (['awaiting_assessment', 'needs_practice'].includes(course.stage)) {
                const answer = el('textarea');
                answer.placeholder = '练习答案';
                const evidence = el('textarea');
                evidence.placeholder = '用于支持答案的原文摘录';
                cp.append(answer, evidence, button('提交有出处的练习', async () => {
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
                const proof = el('textarea');
                proof.placeholder = '记录你用于验证的练习及实际结果';
                cp.append(proof, button('记录通过', async () => {
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
    } else if (route === 'skills') records(panel('习得知识 · 无执行权限'), await api('skills'));
    else if (route === 'cards') {
        const p = panel('自建卡片');
        const title = el('input');
        title.placeholder = '标题';
        const text = el('textarea');
        text.placeholder = '内容';
        const subtype = el('select');
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
        p.append(title, subtype, text, button('创建', async () => {
            await api('cards', 'POST', {
                title: title.value,
                text: text.value,
                subtype: subtype.value
            });
            await render()
        }));
        p.append(el('p', '自建卡没有审批或执行语义。定时通知尚未接入。', 'muted'));
        records(panel('已保存卡片'), await api('cards'))
    } else if (route === 'approvals') {
        const p = panel('提出保存笔记操作');
        const title = el('input');
        title.placeholder = '笔记标题';
        const text = el('textarea');
        text.placeholder = '笔记正文';
        p.append(title, text, button('生成待确认项', async () => {
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
        const label = el('label', '允许桌宠（偏好，不代表本机已显示）');
        label.append(check);
        const mins = el('input');
        mins.type = 'number';
        mins.min = 0;
        mins.max = 240;
        mins.value = conf.daily_minutes;
        p.append(label, el('p', '规划学习预算（分钟；当前设为 0 可暂停队列）'), mins, button('保存版本', async () => {
            await api('config', 'PUT', {
                revision: conf.revision,
                daily_minutes: Number(mins.value),
                pet_enabled: check.checked,
                mac_execute: false,
                autonomous_paid: false,
                mac_allowed_apps: conf.mac_allowed_apps || [],
                mac_allowed_paths: conf.mac_allowed_paths || []
            });
            await render()
        }));
        p.append(el('p', 'Mac 桌宠宿主尚未接入。此配置不会触发采集或操作。', 'muted'))
    } else if (route === 'mac') {
        const conf = (await api('config'))[0] || {
            revision: 0,
            daily_minutes: 45,
            pet_enabled: false
        };
        const p = panel('Mac 权限预配置');
        p.append(el('p', '执行桥尚未实现，执行开关保持关闭。可先保存未来允许的应用与目录，保存不会请求系统权限或操作文件。'));
        const apps = el('textarea');
        apps.value = (conf.mac_allowed_apps || []).join('\n');
        apps.placeholder = '应用 Bundle ID，每行一个';
        const paths = el('textarea');
        paths.value = (conf.mac_allowed_paths || []).join('\n');
        paths.placeholder = '允许目录绝对路径，每行一个';
        const lines = x => x.value.split('\n').map(v => v.trim()).filter(Boolean);
        p.append(el('label', '允许的应用'), apps, el('label', '允许的目录'), paths, button('保存预配置', async () => {
            await api('config', 'PUT', {
                revision: conf.revision,
                daily_minutes: conf.daily_minutes,
                pet_enabled: conf.pet_enabled,
                mac_execute: false,
                autonomous_paid: false,
                mac_allowed_apps: lines(apps),
                mac_allowed_paths: lines(paths)
            });
            await render()
        }))
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
for (const [id, name] of Object.entries(names)) {
    const a = el('a', name);
    a.href = '#' + id;
    $('nav').append(a)
}
window.addEventListener('hashchange', () => run(render));
$('login').onsubmit = e => {
    e.preventDefault();
    token = $('token').value;
    $('token').value = '';
    run(async () => {
        await api('capabilities');
        $('status').textContent = '已连接本机服务';
        if (stopEvents) stopEvents();
        stopEvents = watchEvents(() => token, event => {
            if (conversation) {
                conversation.onEvent(event);
                clearTimeout(eventRefresh);
                eventRefresh = setTimeout(() => run(() => conversation?.refresh()), 100)
            }
            if (['memory.proposed', 'memory.reviewed', 'memory.corrected', 'sources.invalidated'].includes(event.type)) {
                const link = document.querySelector('nav a[href="#memories"]');
                if (link) link.textContent = '记忆审阅 · 有更新';
            }
        }, online => {
            $('status').textContent = online ? '已连接本机服务' : '连接中断，正在重连……'
        });
        await render()
    })
};
run(render);

window.addEventListener('beforeunload', () => stopEvents?.());
