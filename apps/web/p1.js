// Model settings, reviewed memory and conversation use the same authenticated API.
const errors = {
    model_not_configured: '请先在「模型与路由」选择本地模型。',
    local_unavailable: 'Ollama 当前不可用，请确认本机服务已启动且模型已安装。',
    local_timeout: '本地模型超时。可以缩短问题、调整超时或选择其他本地模型。',
    invalid_response: '本地模型返回格式不完整，本次没有保存记忆。',
    local_input_too_large: '输入超出当前上下文窗口，请缩短内容或在模型页增大窗口。',
    local_invalid_response: '本地模型作答格式不完整，本次测验没有计分。',
    context_snapshot_invalidated: '回答期间记忆发生了变化，旧回答已停止提交，请重新提问。',
    cloud_disabled: '云副模型尚未启用。',
    cloud_not_configured: '请先补全云副模型的地址、模型名和密钥。',
    cloud_daily_limit_reached: '今天的云调用次数已达到设置上限。',
    cloud_daily_cost_limit_reached: '今天的云费用预留已达到设置上限。',
    cloud_timeout: '云请求超时，费用状态未知；系统没有自动重试。',
    cloud_http_error: '云服务拒绝了请求，请核对配置与服务商状态。',
    cloud_unavailable: '云服务暂时不可用。',
    cloud_invalid_response: '云模型返回内容不完整。',
    mac_file_write_not_enabled: '文件创建范围尚未启用。',
    mac_file_write_requires_allowed_paths: '启用文件创建前，请先配置允许目录。',
    file_content_required: '请填写新文件内容。',
    file_content_too_large: '文件内容超过 256 KiB 上限。',
    file_path_must_be_absolute: '新文件路径必须是绝对路径。',
    no_allowlisted_paths: '尚未配置可访问的允许目录。',
    parent_directory_not_found: '目标目录不存在。',
    path_outside_allowlist: '目标路径不在允许目录内。',
    file_already_exists: '目标文件已经存在；Fairy 不会覆盖已有文件。',
    parent_directory_not_writable: '目标目录不可写。',
    file_not_writable: '无法创建目标文件。',
    file_write_failed: '文件写入失败，未声称成功。',
    file_verification_failed: '文件回读校验失败，未声称成功。',
    local_only: '本轮仅在本机处理。',
    trigger_disabled: '当前升级原因没有在路由配置中开启。',
    cloud_input_too_large: '待发送内容超过云请求上限，本轮没有发出云请求。',
    model_config_changed: '模型配置已变化，请重新提问。',
    request_cancelled: '请求已中断。',
    source_not_eligible: '当前来源已过期、处于争议或已失效，不能继续生成学习结论。',
    source_invalidated: '学习来源已经失效，请重新阅读并验证。',
    reviewed_practice_required: '需要先提交练习并由你评定通过。',
    practice_not_currently_passed: '最近一次练习评定未通过，不能归纳为习得知识。',
    exact_source_quote_required: '请填写材料中的逐字原文依据。',
    course_not_ready: '材料尚未读完或当前阶段不能提交此操作。',
    invalid_quiz_draft: '本地模型生成的题目结构不完整，请重新生成。',
    quiz_draft_snapshot_invalidated: '生成题目期间来源发生变化，这份草稿已失效。',
    quiz_draft_already_changed: '草稿已被其他操作修改，请刷新后重试。',
    inference_outcome_unknown: '上次模型请求因进程中断而结果未知；系统没有自动重试。'
};
export const explain = code => errors[code] || code;
const fields = ['ollama_base_url', 'ollama_model', 'local_timeout_seconds', 'local_context_window', 'local_max_output_tokens', 'memory_mode', 'cloud_enabled', 'cloud_base_url', 'cloud_model', 'cloud_context', 'cloud_timeout_seconds', 'cloud_max_output_tokens', 'cloud_daily_request_limit', 'cloud_currency', 'cloud_input_cents_per_million', 'cloud_output_cents_per_million', 'cloud_daily_cost_limit_cents', 'fallback_on'];

function field(ui, parent, title, value = '', type = 'text') {
    const label = ui.el('label', title, 'field');
    const input = ui.el(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    input.value = value;
    input.setAttribute('aria-label', title);
    label.append(input);
    parent.append(label);
    return input;
}

function choice(ui, parent, title, values, value) {
    const label = ui.el('label', title, 'field');
    const select = ui.el('select');
    select.setAttribute('aria-label', title);
    for (const [v, text] of values) {
        const o = ui.el('option', text);
        o.value = v;
        select.append(o)
    }
    select.value = value;
    label.append(select);
    parent.append(label);
    return select;
}

function check(ui, parent, title, value) {
    const label = ui.el('label', undefined, 'check');
    const input = ui.el('input');
    input.type = 'checkbox';
    input.checked = value;
    input.setAttribute('aria-label', title);
    label.append(input, ui.el('span', title));
    parent.append(label);
    return input;
}
async function source(ui, id, parent) {
    const existing = parent.querySelector('[data-source="' + id + '"]');
    if (existing) {
        existing.remove();
        return
    }
    const r = await ui.api('sources/' + encodeURIComponent(id));
    const box = ui.el('blockquote', undefined, 'source');
    box.dataset.source = id;
    box.append(ui.el('p', r.text), ui.el('small', '原始记录时间：' + new Date(r.created_at).toLocaleString()));
    parent.append(box);
}

export async function renderModels(ui) {
    const cfg = await ui.api('models/config');
    const semantic = await ui.api('semantic/status').catch(() => null);
    const local = ui.panel('本地主模型');
    local.append(ui.el('p', '每轮先交给本机 Ollama。切换模型不会下载新模型。', 'muted'));
    const url = field(ui, local, 'Ollama 地址', cfg.ollama_base_url);
    const name = field(ui, local, '本地模型名称', cfg.ollama_model);
    const installed = ui.el('div');
    installed.className = 'model-list';
    local.append(ui.button('检测本机模型', async () => {
        const result = await ui.api('models/ollama');
        installed.replaceChildren();
        installed.append(ui.el('p', result.reachable ? 'Ollama 已连接，点击模型名称进行选择。' : '无法连接 Ollama，请检查本机服务。'));
        for (const m of result.models.filter(m => !m.capabilities.length || m.capabilities.includes('completion'))) installed.append(ui.button(m.name, () => {
            name.value = m.name
        }));
    }), installed);
    const ctx = field(ui, local, '上下文窗口', cfg.local_context_window, 'number');
    ctx.min = 4096;
    ctx.max = 65536;
    const timeout = field(ui, local, '本地超时（秒）', cfg.local_timeout_seconds, 'number');
    timeout.min = 5;
    timeout.max = 180;
    const memory = choice(ui, local, '对话记忆', [
        ['review', '提议后由我确认'],
        ['off', '不提议新记忆']
    ], cfg.memory_mode);
    local.append(ui.el('p', '已有记忆仍可用于回答。关闭新记忆提案不会删除对话记录。', 'muted'));
    const cloud = ui.panel('云副模型');
    const enabled = check(ui, cloud, '允许本地能力不足或故障时调用云副模型', cfg.cloud_enabled);
    const base = field(ui, cloud, '云接口地址（兼容 Chat Completions）', cfg.cloud_base_url);
    base.placeholder = 'https://你的服务商/v1';
    const model = field(ui, cloud, '云模型名称', cfg.cloud_model);
    const key = field(ui, cloud, '云 API 密钥', '', 'password');
    key.autocomplete = 'off';
    key.placeholder = cfg.cloud_key_configured ? '已配置，留空保持' : '尚未配置';
    const keyStatus = ui.el('p', cfg.cloud_key_configured ? '密钥已配置；服务不会返回密钥内容。' : '密钥仅保存在本机私有目录，保存后不回显。', 'muted');
    cloud.append(keyStatus);
    const clear = check(ui, cloud, '清除本机保存的云密钥', false);
    const context = choice(ui, cloud, '允许发送给云端的内容', [
        ['question_only', '仅当前问题'],
        ['approved_memories', '当前问题与本轮检索到的已确认记忆']
    ], cfg.cloud_context);
    cloud.append(ui.el('p', '云端不会收到完整聊天历史、本地草稿或未审阅提案。当前问题本身也可能包含你的个人信息。', 'muted'));
    const quota = field(ui, cloud, '每日云请求上限（UTC）', cfg.cloud_daily_request_limit, 'number');
    quota.min = 0;
    quota.max = 1000;
    cloud.append(ui.el('p', '失败或超时的云请求也计入次数。次数上限不等于金额上限。', 'muted'));
    const currency = field(ui, cloud, '计价币种', cfg.cloud_currency || 'USD');
    const inputPrice = field(
        ui,
        cloud,
        '输入价格 / 百万 Token',
        (cfg.cloud_input_cents_per_million || 0) / 100,
        'number'
    );
    inputPrice.min = 0;
    inputPrice.step = '0.0001';
    const outputPrice = field(
        ui,
        cloud,
        '输出价格 / 百万 Token',
        (cfg.cloud_output_cents_per_million || 0) / 100,
        'number'
    );
    outputPrice.min = 0;
    outputPrice.step = '0.0001';
    const costLimit = field(
        ui,
        cloud,
        '每日云费用上限',
        (cfg.cloud_daily_cost_limit_cents || 0) / 100,
        'number'
    );
    costLimit.min = 0;
    costLimit.step = '0.01';
    const budget = await ui.api('models/budget');
    const usedAmount = budget.used_microcents / 100_000_000;
    const limitAmount = budget.daily_cost_limit_cents / 100;
    cloud.append(ui.el(
        'p',
        budget.daily_cost_limit_cents
            ? `今日已预留/结算 ${usedAmount.toFixed(6)} / ${limitAmount.toFixed(2)} ${budget.currency}`
            : `今日已预留/结算 ${usedAmount.toFixed(6)} ${budget.currency}，未设置金额上限`,
        'muted'
    ));
    const triggers = ui.panel('何时请副模型协助');
    const selected = [];
    const labels = {
        capability_limit: '本地模型明确表示能力不足',
        knowledge_gap: '本地模型明确表示知识不足',
        local_unavailable: '本地服务不可用',
        local_timeout: '本地请求超时',
        invalid_response: '本地输出格式不完整'
    };
    for (const [value, title] of Object.entries(labels)) selected.push([value, check(ui, triggers, title, cfg.fallback_on.includes(value))]);
    triggers.append(ui.el('p', '需要你补充信息或明确拒绝的回答不会自动转交云端。路由依据不是正确率证明，你也可以逐轮选择处理方式。', 'muted'));
    const status = ui.el('p', '配置版本 ' + cfg.revision, 'muted');
    triggers.append(ui.button('保存模型与路由', async () => {
        const payload = {
            revision: cfg.revision
        };
        for (const k of fields) payload[k] = cfg[k];
        Object.assign(payload, {
            ollama_base_url: url.value.trim(),
            ollama_model: name.value.trim(),
            local_context_window: Number(ctx.value),
            local_timeout_seconds: Number(timeout.value),
            memory_mode: memory.value,
            cloud_enabled: enabled.checked && !clear.checked,
            cloud_base_url: base.value.trim(),
            cloud_model: model.value.trim(),
            cloud_context: context.value,
            cloud_daily_request_limit: Number(quota.value),
            cloud_currency: currency.value.trim().toUpperCase(),
            cloud_input_cents_per_million: Math.round(Number(inputPrice.value) * 100),
            cloud_output_cents_per_million: Math.round(Number(outputPrice.value) * 100),
            cloud_daily_cost_limit_cents: Math.round(Number(costLimit.value) * 100),
            fallback_on: selected.filter(([, input]) => input.checked).map(([value]) => value),
            clear_cloud_key: clear.checked
        });
        if (key.value) payload.cloud_api_key = key.value;
        const saved = await ui.api('models/config', 'PUT', payload);
        key.value = '';
        Object.assign(cfg, saved);
        clear.checked = false;
        enabled.checked = saved.cloud_enabled;
        status.textContent = '已保存，配置版本 ' + saved.revision;
        keyStatus.textContent = saved.cloud_key_configured ? '密钥已配置；服务不会返回密钥内容。' : '尚未配置云密钥。';
    }), status);
    const journal = ui.panel('最近的模型调用');
    const rows = await ui.api('models/invocations?limit=10');
    for (const r of rows.reverse()) journal.append(ui.el(
        'p',
        (r.phase === 'local' ? '本机' : '云端')
            + ' · '
            + r.model
            + ' · '
            + r.status
            + (r.cost_microcents !== undefined
                ? ' · ' + (r.cost_microcents / 100_000_000).toFixed(6) + ' ' + (r.cloud_currency || '')
                : '')
            + (r.reason ? ' · ' + r.reason : '')
    ));
    if (!rows.length) journal.append(ui.el('p', '还没有发出模型请求。', 'muted'));
    const retrieval = ui.panel('本地语义检索');
    retrieval.append(
        ui.el(
            'p',
            semantic?.enabled
                ? '学习资料使用 ' + semantic.model + ' 做本机神经向量重排；向量缓存在本地数据库，不调用云服务。'
                : '神经向量模型未启用；学习资料使用本地字符向量与词法混合检索。',
            semantic?.enabled ? 'muted' : 'route-note'
        )
    );
}

export async function renderMemories(ui) {
    const pending = (await ui.api('memory/proposals')).filter(p => p.status === 'pending');
    const review = ui.panel('待审阅记忆');
    review.append(ui.el('p', '确认后才进入长期记忆。请核对原文与含义；提案有出处不代表理解一定正确。', 'muted'));
    if (!pending.length) review.append(ui.el('p', '暂时没有待审阅提案。你可以在对话中说“请记住……”。', 'muted'));
    for (const p of pending) {
        const row = ui.el('article', undefined, 'memory-row');
        row.append(ui.el('h3', p.text));
        const subject = choice(ui, row, '这条信息描述谁', [
            ['owner', '我（用户）'],
            ['assistant', 'Fairy（助手）'],
            ['other', '其他人物'],
            ['unspecified', '主体尚未明确']
        ], p.subject || 'unspecified');
        row.append(ui.button('查看原文', () => source(ui, p.source_ids[0], row)), ui.button('确认记住', async () => {
            await ui.api('memory/proposals/' + p.id + '/review', 'POST', {
                revision: p.revision,
                decision: 'approve',
                subject: subject.value
            });
            await ui.refresh()
        }), ui.button('不记住', async () => {
            await ui.api('memory/proposals/' + p.id + '/review', 'POST', {
                revision: p.revision,
                decision: 'reject'
            });
            await ui.refresh()
        }));
        review.append(row)
    }
    const list = ui.panel('已确认记忆');
    const memories = await ui.api('memories');
    if (!memories.length) list.append(ui.el('p', '还没有已确认记忆。待审阅的内容不会在这里显示。', 'muted'));
    for (const m of memories) {
        const row = ui.el('article', undefined, 'memory-row');
        row.dataset.memoryId = m.id;
        row.append(ui.el('h3', m.text), ui.el('p', '版本 ' + m.revision, 'muted'));
        for (const id of m.source_ids) row.append(ui.button('查看当前来源', () => source(ui, id, row)));
        const history = ui.el('div');
        row.append(ui.button('查看版本记录', async () => {
            history.replaceChildren();
            for (const v of await ui.api('memories/' + m.id + '/history')) {
                const h = ui.el('div', undefined, 'version');
                h.append(ui.el('strong', '版本 ' + v.memory_revision + (v.valid_to ? '（已被纠正）' : '（当前）')), ui.el('p', v.text), ui.el('small', v.change_reason==='initial_review'?'初次确认':v.change_reason||'初次确认'));
                history.append(h)
            }
        }), history);
        row.append(ui.button('纠正记忆', () => {
            const editor = ui.el('div');
            const text = field(ui, editor, '纠正后的内容', m.text, 'textarea');
            const reason = field(ui, editor, '纠正原因', '');
            const subject = choice(ui, editor, '纠正后的主体', [
                ['owner', '我（用户）'],
                ['assistant', 'Fairy（助手）'],
                ['other', '其他人物'],
                ['unspecified', '主体尚未明确']
            ], m.subject || 'unspecified');
            editor.append(ui.button('保存纠正', async () => {
                await ui.api('memories/' + m.id, 'PATCH', {
                    revision: m.revision,
                    text: text.value,
                    reason: reason.value,
                    subject: subject.value
                });
                ui.closeDialog();
                await ui.refresh()
            }));
            ui.openDialog('纠正记忆', editor, {
                variant: 'drawer',
                dismissOnBackdrop: false
            });
        }));
        row.append(ui.confirmButton(
            '遗忘这条记忆',
            '遗忘记忆',
            '清除当前记忆及其版本记录，并阻止相关旧来源进入后续回答。原始材料仍可单独查看。',
            async () => {
                await ui.api('memories/' + m.id + '?revision=' + m.revision, 'DELETE');
                await ui.refresh()
            }
        ));
        list.append(row)
    }
    const search = ui.panel('检索当前记忆');
    const q = field(ui, search, '检索关键词', '');
    const result = ui.el('div');
    search.append(ui.button('查询记忆', async () => {
        const data = await ui.api('memories?q=' + encodeURIComponent(q.value));
        result.replaceChildren();
        if (!data.results.length) result.append(ui.el('p', '没有匹配到当前有效记忆。', 'muted'));
        for (const r of data.results) result.append(ui.el('p', r.text))
    }), result);
}

export async function renderConversation(ui) {
    const cfg = await ui.api('models/config');
    const p = ui.panel('与 Fairy 对话');
    p.append(ui.el('p', '本地主模型：' + (cfg.ollama_model || '尚未选择') + ' · 云副模型' + (cfg.cloud_ready ? '已启用' : '未启用'), 'muted'));
    const routing = choice(ui, p, '本轮处理方式', [
        ['auto', '本机优先，必要时请副模型协助'],
        ['local_only', '仅在本机处理'],
        ['cloud_assist', '先由本机处理，再请副模型协助']
    ], 'auto');
    const text = field(ui, p, '输入消息', '', 'textarea');
    text.placeholder = '例如：请记住，我喜欢喝茉莉花茶。';
    const voice = await ui.api('voice/status').catch(() => ({
        local_tts: false,
        local_asr: false,
    }));
    const speechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const localAsr = Boolean(
        voice.local_asr
        && navigator.mediaDevices?.getUserMedia
        && window.MediaRecorder
    );
    const voiceInput = ui.el('button', localAsr ? '本地语音输入' : '语音输入');
    const speakReply = ui.el('button', '朗读最新回答');
    voiceInput.setAttribute('aria-label', localAsr ? '本地语音输入' : '语音输入');
    speakReply.setAttribute('aria-label', '朗读最新回答');
    if (!localAsr && !speechRecognition) {
        voiceInput.disabled = true;
        voiceInput.title = '当前浏览器不提供语音识别';
    }
    if (!voice.local_tts && !('speechSynthesis' in window)) {
        speakReply.disabled = true;
        speakReply.title = '当前浏览器不提供语音合成';
    }
    const speechStatus = ui.el(
        'p',
        localAsr
            ? '本地 Whisper 转写：录音只写入临时目录，转写完成后删除，不经过云模型。'
            : speechRecognition
                ? '本地 ASR 尚未配置，当前使用浏览器语音识别；音频可能由系统或浏览器供应商处理。'
                : '本地 ASR 尚未配置，当前浏览器也不提供语音识别；文字对话仍可使用。',
        'muted'
    );
    const composerTools = ui.el('div', undefined, 'composer-tools');
    composerTools.append(voiceInput, speakReply);
    p.append(composerTools, speechStatus);
    let recognition = null;
    let mediaRecorder = null;
    let mediaStream = null;
    let recordingChunks = [];
    let localAudio = null;
    let localAudioUrl = null;
    const appendTranscript = transcript => {
        const before = text.value.trim();
        text.value = [before, transcript.trim()].filter(Boolean).join(' ');
    };
    const startWebSpeech = () => {
        recognition = new speechRecognition();
        recognition.lang = 'zh-CN';
        recognition.interimResults = true;
        recognition.continuous = false;
        const before = text.value.trim();
        recognition.onresult = event => {
            let transcript = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                transcript += event.results[i][0].transcript;
            }
            text.value = [before, transcript.trim()].filter(Boolean).join(' ');
        };
        recognition.onerror = event => {
            speechStatus.textContent = '语音输入失败：' + event.error;
        };
        recognition.onend = () => {
            recognition = null;
            voiceInput.textContent = '语音输入';
            speechStatus.textContent = text.value ? '语音已转为可编辑文字。' : '';
        };
        voiceInput.textContent = '停止听写';
        speechStatus.textContent = '正在通过浏览器听写……';
        recognition.start();
    };
    const transcribeLocalAudio = async (mimeType = 'audio/webm') => {
        const bytes = new Uint8Array(await new Blob(recordingChunks, {type: mimeType}).arrayBuffer());
        if (bytes.byteLength > 10_000_000) throw Error('录音超过 10 MB 上限');
        let binary = '';
        for (const byte of bytes) binary += String.fromCharCode(byte);
        const result = await ui.api('voice/transcribe', 'POST', {
            audio_base64: btoa(binary),
            media_type: mimeType,
            language: 'zh',
        });
        appendTranscript(result.text);
    };
    const startLocalRecording = async () => {
        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({audio: true});
            recordingChunks = [];
            mediaRecorder = new MediaRecorder(mediaStream);
            mediaRecorder.ondataavailable = event => {
                if (event.data.size) recordingChunks.push(event.data);
            };
            mediaRecorder.onstop = async () => {
                const mimeType = (mediaRecorder?.mimeType || 'audio/webm').split(';')[0];
                mediaStream?.getTracks().forEach(track => track.stop());
                mediaStream = null;
                voiceInput.textContent = '本地语音输入';
                speechStatus.textContent = '正在使用本地 Whisper 转写……';
                try {
                    await transcribeLocalAudio(mimeType);
                    speechStatus.textContent = text.value ? '语音已转为可编辑文字。' : '没有识别到语言。';
                } catch (error) {
                    speechStatus.textContent = '本地语音转写失败：' + error.message;
                } finally {
                    mediaRecorder = null;
                }
            };
            mediaRecorder.start();
            voiceInput.textContent = '停止本地录音';
            speechStatus.textContent = '正在本地录音；再次点击停止并转写。';
        } catch (error) {
            speechStatus.textContent = '无法开始录音：' + error.message;
            mediaStream?.getTracks().forEach(track => track.stop());
            mediaStream = null;
        }
    };
    voiceInput.onclick = async () => {
        if (localAsr) {
            if (mediaRecorder?.state === 'recording') {
                mediaRecorder.stop();
            } else {
                await startLocalRecording();
            }
            return;
        }
        if (!speechRecognition) return;
        if (recognition) {
            recognition.stop();
            recognition = null;
            voiceInput.textContent = '语音输入';
            speechStatus.textContent = '';
            return;
        }
        startWebSpeech();
    };
    let latestTurns = [];
    speakReply.onclick = async () => {
        const reply = [...latestTurns].reverse().find(turn => turn.reply)?.reply;
        if (!reply) {
            speechStatus.textContent = '还没有可朗读的回答。';
            return;
        }
        if (voice.local_tts) {
            speechStatus.textContent = '正在生成本机语音……';
            try {
                const response = await ui.apiResponse('voice/speak', 'POST', {text: reply});
                if (localAudioUrl) URL.revokeObjectURL(localAudioUrl);
                localAudioUrl = URL.createObjectURL(await response.blob());
                localAudio = new Audio(localAudioUrl);
                localAudio.onended = () => speechStatus.textContent = '本地朗读完成。';
                await localAudio.play();
                speechStatus.textContent = '正在本地朗读最新回答。';
            } catch (error) {
                speechStatus.textContent = '本机朗读失败：' + error.message;
            }
            return;
        }
        if (!('speechSynthesis' in window)) return;
        speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(reply);
        utterance.lang = 'zh-CN';
        speechSynthesis.speak(utterance);
        speechStatus.textContent = '正在通过浏览器朗读最新回答。';
    };
    const progress = ui.el('p', '记忆提案需要你在「记忆审阅」中确认。', 'muted');
    p.append(progress);
    let inFlight = false;
    const send = ui.button('发送', async () => {
        if (inFlight || !text.value.trim()) return;
        inFlight = true;
        send.disabled = true;
        text.disabled = true;
        progress.textContent = '本地主模型正在处理……';
        try {
            const r = await ui.api('turns', 'POST', {
                text: text.value,
                routing: routing.value
            });
            text.value = '';
            progress.textContent = r.error ? explain(r.error) : (r.memory_proposal_ids?.length ? '回答已返回，有 ' + r.memory_proposal_ids.length + ' 条记忆提案等待审阅。' : '回答已返回。');
            followLatest = true;
            await refresh()
        } finally {
            inFlight = false;
            send.disabled = false;
            text.disabled = false
        }
    });
    p.append(send);
    text.addEventListener('keydown', event => {
        if (
            event.key === 'Enter'
            && !event.shiftKey
            && !event.isComposing
            && event.keyCode !== 229
        ) {
            event.preventDefault();
            send.click();
        }
    });
    const history = ui.panel('对话记录');
    history.classList.add('conversation-panel');
    const toolbar = ui.el('div', undefined, 'conversation-toolbar');
    const jumpLatest = ui.el('button', '跳到最新', 'button button-secondary');
    jumpLatest.type = 'button';
    jumpLatest.hidden = true;
    toolbar.append(jumpLatest);
    const output = ui.el('div', undefined, 'conversation-scroll');
    history.append(toolbar, output);
    let followLatest = true;
    const updateFollowState = () => {
        const distance = output.scrollHeight - output.scrollTop - output.clientHeight;
        followLatest = distance < 48;
        jumpLatest.hidden = followLatest;
    };
    output.addEventListener('scroll', updateFollowState, {passive: true});
    jumpLatest.onclick = () => {
        followLatest = true;
        output.scrollTo({top: output.scrollHeight, behavior: 'smooth'});
        jumpLatest.hidden = true;
    };
    async function refresh() {
        const turns = await ui.api('turns');
        latestTurns = turns;
        if (!output.isConnected) return;
        const previousTop = output.scrollTop;
        output.replaceChildren();
        if (!turns.length) output.append(ui.el('p', '从一条消息开始。', 'muted'));
        for (const t of turns.slice(-30)) {
            const article = ui.el('article', undefined, 'conversation');
            article.append(ui.el('p', t.text, 'user-message'));
            article.append(ui.el('p', t.reply || (t.error ? explain(t.error) : t.status === 'pending' ? '正在处理……' : '已中断'), 'assistant-message'));
            const r = t.model_route;
            if (r) {
                article.append(ui.el('small', (r.provider === 'memory' ? '来源记忆校验' : r.cloud_used ? '云副模型' : '本地主模型') + ' · ' + r.model));
                if (r.cloud_skip_reason) article.append(ui.el('p', explain(r.cloud_skip_reason), 'route-note'));
                if (r.local_outcome === 'needs_cloud' && !r.cloud_used) article.append(ui.el('p', '本机表示需要进一步协助，这条回答尚未解决问题。', 'route-note'))
            }
            if (t.memory_proposal_ids?.length) {
                const link = ui.el('a', '审阅本轮记忆提案');
                link.href = '#memories';
                article.append(link)
            }
            if (t.status === 'pending') article.append(ui.button('中断本轮', async () => {
                await ui.api('turns/' + t.id + '/cancel', 'POST', {});
                await refresh()
            }));
            output.append(article)
        }
        requestAnimationFrame(() => {
            if (followLatest) {
                output.scrollTop = output.scrollHeight;
                jumpLatest.hidden = true;
            } else {
                output.scrollTop = previousTop;
                jumpLatest.hidden = false;
            }
        });
    }
    await refresh();
    return {
        refresh,
        onEvent: event => {
            if (event.type === 'model.dispatched') progress.textContent = event.payload.phase === 'cloud' ? '云副模型正在协助……' : '本地主模型正在处理……'
        }
    };
}

// SSE carries the bearer in a header, never in a URL. Cursor survives reconnects in memory.
export function watchEvents(getToken, onEvent, onConnection, initialCursor = 0) {
    const abort = new AbortController();
    let cursor = Math.max(0, Number(initialCursor) || 0);
    let stopped = false;
    const reconnect = ms => new Promise(resolve => {
        const done = () => {
            clearTimeout(timer);
            abort.signal.removeEventListener('abort', done);
            resolve()
        };
        const timer = setTimeout(done, ms);
        abort.signal.addEventListener('abort', done, {
            once: true
        });
    });
    (async () => {
        while (!stopped) {
            try {
                const response = await fetch('/v2/stream', {
                    headers: {
                        Authorization: 'Bearer ' + getToken(),
                        'Last-Event-ID': String(cursor)
                    },
                    signal: abort.signal
                });
                if (!response.ok) throw Error('event_stream_unavailable');
                onConnection(true);
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                while (!stopped) {
                    const {
                        done,
                        value
                    } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, {
                        stream: true
                    });
                    let index;
                    while ((index = buffer.indexOf('\n\n')) >= 0) {
                        const frame = buffer.slice(0, index);
                        buffer = buffer.slice(index + 2);
                        const data = frame.split('\n').find(x => x.startsWith('data: '));
                        if (data) {
                            const event = JSON.parse(data.slice(6));
                            if (event.seq > cursor) {
                                cursor = event.seq;
                                onEvent(event)
                            }
                        }
                    }
                }
            } catch (e) {
                if (stopped) break;
                onConnection(false)
            }
            if (!stopped) await reconnect(2000)
        }
    })();
    return () => {
        stopped = true;
        abort.abort()
    };
}
