const workStateLabels = {
    QUEUED: '排队中',
    RUNNING: '处理中',
    COMPLETED: '已完成 · 待播报',
    DELIVERING: '正在播报',
    DELIVERED: '已送达',
    FAILED: '失败',
    CANCELLING: '取消中',
    CANCELLED: '已取消'
};
const orbLabels = {
    disconnected: '未连接',
    idle: '待命 · 开口即可',
    listening: '聆听中',
    thinking: '思考中',
    speaking: '回应中 · 可随时打断'
};

export async function renderDuplex(ui) {
    const {el, api, panel, button, controlLabel, openDialog, closeDialog, showToast, getToken} = ui;
    let disposed = false;
    let connected = false;
    let ready = false;
    let ws = null;
    let audioCtx = null;
    let micStream = null;
    let micSource = null;
    let processor = null;
    let worksTimer = null;
    let flashTimer = null;
    let playing = null;
    let worksSnapshot = '';
    const queue = [];
    const items = new Map();
    const works = new Map();
    const stale = () => disposed || (location.hash.slice(1) || 'overview') !== 'duplex';

    const stagePanel = panel('全双工对话');
    stagePanel.append(el('p', '直接开口和 Fairy 说话：她边听边想，回应时你随时可以插话打断；短促的附和（比如「嗯」「对」）不会打断她。', 'muted'));
    const stage = el('div', undefined, 'duplex-stage');
    stage.dataset.state = 'disconnected';
    const orbWrap = el('div', undefined, 'duplex-orb-wrap');
    const orb = el('div', undefined, 'duplex-orb');
    orbWrap.append(
        orb,
        el('div', undefined, 'duplex-ring'),
        el('div', undefined, 'duplex-ring duplex-ring-b'),
        el('div', undefined, 'duplex-orbit')
    );
    const bars = el('div', undefined, 'duplex-bars');
    for (let i = 0; i < 5; i += 1) bars.append(el('span'));
    const stateLabel = el('p', orbLabels.disconnected, 'duplex-state-label');
    stateLabel.setAttribute('aria-live', 'polite');
    stage.append(orbWrap, bars, stateLabel);
    stagePanel.append(stage);
    const setOrb = (state) => {
        const next = orbLabels[state] ? state : 'idle';
        stage.dataset.state = next;
        stateLabel.textContent = orbLabels[next];
    };

    const controls = el('div', undefined, 'button-row duplex-controls');
    const connectBtn = el('button', '开始对话', 'button button-primary');
    connectBtn.type = 'button';
    const restoreConnect = () => {
        connectBtn.disabled = false;
        connectBtn.textContent = '开始对话';
        connectBtn.className = 'button button-primary';
    };
    connectBtn.onclick = () => {
        if (connected) teardown('对话结束');
        else connect();
    };
    const interruptBtn = button('中断', async () => {
        if (!connected) throw new Error('请先开始对话');
        send({type: 'interrupt'});
    });
    const delegateBtn = el('button', '委派后台任务', 'button button-secondary');
    delegateBtn.type = 'button';
    delegateBtn.onclick = () => {
        if (!connected) {
            showToast('请先开始对话', 'error');
            return
        }
        const body = el('div', undefined, 'confirm-content');
        const textarea = el('textarea');
        textarea.rows = 4;
        controlLabel('任务内容', textarea, body, '任务会在后台运行，结果将在你空闲时播报。');
        const actions = el('div', undefined, 'button-row dialog-actions');
        const cancel = el('button', '取消', 'button button-secondary');
        cancel.type = 'button';
        cancel.onclick = closeDialog;
        const submit = button('开始委派', async () => {
            const text = textarea.value.trim();
            if (!text) throw new Error('请先填写任务内容');
            send({type: 'delegate', text});
            closeDialog();
        });
        actions.append(cancel, submit);
        body.append(actions);
        openDialog('委派后台任务', body, {variant: 'modal'});
        textarea.focus();
    };
    controls.append(connectBtn, interruptBtn, delegateBtn);
    stagePanel.append(controls);

    const transcriptPanel = panel('对话记录');
    const scroll = el('div', undefined, 'conversation-scroll duplex-scroll');
    transcriptPanel.append(scroll);
    const addBubble = (role, text, tag) => {
        const article = el('article', undefined, 'conversation');
        const p = el('p', text, role === 'user' ? 'user-message' : 'assistant-message');
        article.append(p);
        if (tag) article.append(el('small', tag, 'route-note'));
        scroll.append(article);
        scroll.scrollTop = scroll.scrollHeight;
        return p
    };
    const composer = el('div', undefined, 'duplex-composer');
    const input = el('input');
    input.className = 'control';
    input.type = 'text';
    input.placeholder = '也可以打字交流…';
    input.setAttribute('aria-label', '文字输入');
    const sendText = () => {
        const text = input.value.trim();
        if (!text) return;
        if (!connected) {
            showToast('请先开始对话', 'error');
            return
        }
        addBubble('user', text);
        send({type: 'text', text});
        input.value = '';
    };
    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') sendText();
    });
    composer.append(input, button('发送', async () => sendText()));
    transcriptPanel.append(composer);

    const worksPanel = panel('后台任务');
    worksPanel.append(el('p', '委派的任务在后台运行。「已完成」只表示算出了结果，真正播报完并收到播放确认后才会标记「已送达」。', 'muted'));
    const statusRow = el('div', undefined, 'row');
    worksPanel.append(statusRow);
    const worksList = el('div', undefined, 'duplex-works');
    worksPanel.append(worksList);
    const renderWorks = () => {
        const snapshot = JSON.stringify([...works.values()]);
        if (snapshot === worksSnapshot) return;
        worksSnapshot = snapshot;
        worksList.replaceChildren();
        if (!works.size) {
            worksList.append(el('p', '还没有后台任务。开始对话后点「委派后台任务」。', 'muted'));
            return
        }
        for (const work of [...works.values()].reverse()) {
            const row = el('article', undefined, 'memory-row');
            row.append(el('p', work.text));
            let label = workStateLabels[work.state] || work.state;
            if (work.state === 'FAILED' && work.error) label += ' · ' + work.error;
            row.append(el('small', label, 'muted'));
            if (['QUEUED', 'RUNNING', 'COMPLETED', 'DELIVERING'].includes(work.state)) {
                row.append(button('取消任务', async () => {
                    await api('duplex/works/' + work.id + '/cancel', 'POST', {});
                    await refreshWorks();
                }));
            }
            worksList.append(row);
        }
    };
    const refreshWorks = async () => {
        try {
            const list = await api('duplex/works');
            works.clear();
            for (const work of list) works.set(work.id, work);
            renderWorks();
        } catch { /* 保留上一次快照 */ }
    };
    try {
        const status = await api('duplex/status');
        statusRow.append(
            el('span', '全双工', 'tag'),
            el('span', '支持打断', 'tag'),
            el('span', '附和忽略', 'tag'),
            el('span', status.voice?.local_asr ? '本地识别可用' : '本地识别未配置', 'tag'),
            el('span', status.voice?.local_tts ? '本地合成可用' : '本地合成不可用', 'tag')
        );
    } catch { /* 状态行可选 */ }
    if (stale()) return {dispose};
    await refreshWorks();
    if (stale()) return {dispose};
    renderWorks();

    const downsample = (samples, from, to) => {
        const ratio = from / to;
        const length = Math.floor(samples.length / ratio);
        const out = new Int16Array(length);
        for (let i = 0; i < length; i += 1) {
            const start = Math.floor(i * ratio);
            const end = Math.min(samples.length, Math.floor((i + 1) * ratio));
            let sum = 0;
            let count = 0;
            for (let j = start; j < end; j += 1) {
                sum += samples[j];
                count += 1;
            }
            let v = count ? sum / count : 0;
            v = Math.max(-1, Math.min(1, v));
            out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
        }
        return out
    };

    async function connect() {
        connectBtn.disabled = true;
        connectBtn.textContent = '正在连接…';
        try {
            if (!audioCtx) audioCtx = new AudioContext();
            if (audioCtx.state === 'suspended') await audioCtx.resume();
            micStream = await navigator.mediaDevices.getUserMedia({
                audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}
            });
        } catch {
            showToast('无法访问麦克风，请检查浏览器权限', 'error');
            restoreConnect();
            return
        }
        if (disposed) {
            stopMic();
            return
        }
        micSource = audioCtx.createMediaStreamSource(micStream);
        processor = audioCtx.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = (event) => {
            if (ws && ws.readyState === 1 && ready) {
                ws.send(downsample(event.inputBuffer.getChannelData(0), audioCtx.sampleRate, 16000).buffer);
            }
        };
        micSource.connect(processor);
        processor.connect(audioCtx.destination);
        const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/v2/duplex/ws`);
        ws = socket;
        socket.onopen = () => send({type: 'auth', token: getToken()});
        socket.onmessage = (event) => {
            let msg;
            try {
                msg = JSON.parse(event.data);
            } catch {
                return
            }
            handle(msg);
        };
        socket.onclose = () => {
            if (disposed) return;
            if (connected) teardown('连接已断开', 'error');
            else {
                stopMic();
                restoreConnect();
                showToast('连接失败，请重试', 'error');
            }
        };
    }

    function handle(msg) {
        if (disposed) return;
        switch (msg.type) {
            case 'ready':
                connected = true;
                ready = true;
                setOrb(msg.state || 'idle');
                connectBtn.disabled = false;
                connectBtn.textContent = '结束对话';
                connectBtn.className = 'button button-secondary';
                worksTimer = setInterval(refreshWorks, 4000);
                refreshWorks();
                showToast('已连接，可以直接说话');
                break;
            case 'state':
                setOrb(msg.state);
                break;
            case 'vad':
                if (msg.event === 'speech_start') orbWrap.classList.add('is-voiced');
                else orbWrap.classList.remove('is-voiced');
                break;
            case 'transcript':
                addBubble('user', msg.text);
                break;
            case 'reply':
                addBubble('assistant', msg.text, '路由 ' + (msg.route || '本地'));
                break;
            case 'speech':
                onSpeech(msg);
                break;
            case 'stop_playback':
                stopItem(msg.item_id);
                break;
            case 'backchannel':
                orbWrap.classList.add('is-backchannel');
                clearTimeout(flashTimer);
                flashTimer = setTimeout(() => orbWrap.classList.remove('is-backchannel'), 600);
                break;
            case 'work':
                works.set(msg.work.id, msg.work);
                renderWorks();
                break;
            case 'error':
            case 'asr_error':
                showToast(msg.detail || '发生错误', 'error');
                break;
        }
    }

    const itemFor = (id) => {
        if (!items.has(id)) items.set(id, {cancelled: false, acked: new Set(), bubble: null});
        return items.get(id)
    };
    function ack(item, itemId, seq, played) {
        if (item.acked.has(seq)) return;
        item.acked.add(seq);
        send({type: 'playback_ack', item_id: itemId, seq, played});
    }
    function onSpeech(msg) {
        const item = itemFor(msg.item_id);
        if (msg.kind === 'work') {
            if (!item.bubble) item.bubble = addBubble('assistant', msg.text || '', '后台任务结果');
            else if (msg.text) item.bubble.textContent += msg.text;
            scroll.scrollTop = scroll.scrollHeight;
        }
        if (item.cancelled) {
            ack(item, msg.item_id, msg.seq, false);
            return
        }
        if (!msg.audio_base64) {
            ack(item, msg.item_id, msg.seq, true);
            return
        }
        let bytes;
        try {
            const raw = atob(msg.audio_base64);
            bytes = new Uint8Array(raw.length);
            for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
        } catch {
            ack(item, msg.item_id, msg.seq, true);
            return
        }
        audioCtx.decodeAudioData(bytes.buffer.slice(0)).then((buffer) => {
            if (disposed || item.cancelled) {
                ack(item, msg.item_id, msg.seq, false);
                return
            }
            queue.push({item_id: msg.item_id, seq: msg.seq, buffer, item});
            pump();
        }).catch(() => ack(item, msg.item_id, msg.seq, true));
    }
    function pump() {
        if (playing || !queue.length || disposed) return;
        const next = queue.shift();
        if (next.item.cancelled) {
            ack(next.item, next.item_id, next.seq, false);
            pump();
            return
        }
        const src = audioCtx.createBufferSource();
        src.buffer = next.buffer;
        src.connect(audioCtx.destination);
        playing = {src, item_id: next.item_id, seq: next.seq, item: next.item};
        src.onended = () => {
            const was = playing;
            playing = null;
            if (was && was.src === src) ack(next.item, next.item_id, next.seq, !next.item.cancelled && !disposed);
            pump();
        };
        src.start();
    }
    function stopItem(itemId) {
        const item = itemFor(itemId);
        item.cancelled = true;
        if (playing && playing.item_id === itemId) {
            try {
                playing.src.stop();
            } catch { /* 已停止 */ }
        }
        for (let i = queue.length - 1; i >= 0; i -= 1) {
            if (queue[i].item_id === itemId) {
                const [entry] = queue.splice(i, 1);
                ack(entry.item, entry.item_id, entry.seq, false);
            }
        }
    }

    function stopMic() {
        if (processor) {
            processor.onaudioprocess = null;
            try {
                processor.disconnect();
            } catch { /* 已断开 */ }
            processor = null;
        }
        if (micSource) {
            try {
                micSource.disconnect();
            } catch { /* 已断开 */ }
            micSource = null;
        }
        if (micStream) {
            for (const track of micStream.getTracks()) track.stop();
            micStream = null;
        }
    }
    function teardown(reason, tone = 'success') {
        connected = false;
        ready = false;
        clearInterval(worksTimer);
        worksTimer = null;
        stopMic();
        const socket = ws;
        ws = null;
        if (socket) {
            try {
                socket.close();
            } catch { /* 已关闭 */ }
        }
        queue.length = 0;
        if (playing) {
            try {
                playing.src.stop();
            } catch { /* 已停止 */ }
            playing = null;
        }
        setOrb('disconnected');
        restoreConnect();
        if (reason && !disposed) showToast(reason, tone);
    }
    function dispose() {
        if (disposed) return;
        disposed = true;
        teardown();
        clearTimeout(flashTimer);
        if (audioCtx) {
            audioCtx.close().catch(() => {});
            audioCtx = null;
        }
    }
    function send(obj) {
        if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
    }
    return {dispose}
}
