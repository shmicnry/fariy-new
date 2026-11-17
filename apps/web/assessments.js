export async function renderAssessments(ui) {
    const {
        el,
        api,
        panel,
        button
    } = ui;
    const make = (p, label, type = 'input') => {
        const l = el('label', label, 'field'),
            x = el(type);
        x.setAttribute('aria-label', label);
        l.append(x);
        p.append(l);
        return x
    };
    const form = panel('固定题目测验');
    form.append(el('p', '由你预先确定答案，本地模型作答、程序评分。开卷使用你选择的原文依据；闭卷不提供材料。分数不代表模型参数已学习或具备通用迁移能力。', 'muted'));
    const title = make(form, '测验名称'),
        source = make(form, '测验材料 ID'),
        evidence = make(form, '测验原文依据');
    const question = make(form, '题目', 'textarea'),
        options = make(form, '备选答案（每行一个）', 'textarea'),
        correct = make(form, '正确选项（从1开始）');
    correct.type = 'number';
    correct.min = 1;
    correct.max = 6;
    correct.value = 1;
    const items = [],
        preview = el('div');
    const add = () => {
        const choices = options.value.split('\n').map(x => x.trim()).filter(Boolean),
            index = Number(correct.value) - 1;
        if (!question.value.trim() || choices.length < 2 || choices.length > 6 || !Number.isInteger(index) || index < 0 || index >= choices.length) throw Error('请填写题目、2–6个选项，并选择正确答案序号');
        if (items.length >= 10) throw Error('每份测验最多10题');
        items.push({
            question: question.value.trim(),
            choices,
            correct_index: index
        });
        preview.append(el('p', '第' + items.length + '题：' + question.value.trim() + '（正确答案：' + choices[index] + '）'));
        question.value = '';
        options.value = '';
        correct.value = 1
    };
    form.append(button('加入题目', add), preview, el('p', '每份1–10题。标准答案只用于程序评分，不会发送给模型。', 'muted'), button('保存固定题目', async () => {
        if (question.value.trim()) add();
        await api('learning/quizzes', 'POST', {
            title: title.value,
            source_id: source.value,
            evidence: evidence.value,
            questions: items
        });
        await ui.refresh()
    }));
    const quizzes = panel('本机作答');
    for (const q of await api('learning/quizzes')) {
        const row = el('article', undefined, 'memory-row');
        row.append(el('h3', q.title), el('p', '题目 ' + q.questions.length + ' 道'));
        for (const [mode, label] of [
                ['open_book', '开卷作答'],
                ['closed_book', '闭卷作答']
            ]) row.append(button(label, async () => {
            const r = await api('learning/quizzes/' + q.id + '/runs', 'POST', {
                mode
            });
            if (r.status === 'failed') throw Error('作答失败：' + r.error);
            await ui.refresh()
        }));
        quizzes.append(row)
    }
    const results = panel('测验结果');
    for (const r of (await api('learning/assessment-runs')).reverse()) {
        const row = el('article', undefined, 'memory-row');
        row.append(el('p', (r.mode === 'open_book' ? '开卷' : '闭卷') + ' · ' + r.model), el('p', r.status === 'completed' ? '答对 ' + r.correct_count + ' / ' + r.total + '，程序按固定答案计分' : r.error || r.status));
        if (r.status === 'pending') row.append(button('停止本次作答', async () => {
            await api('learning/assessment-runs/' + r.id + '/cancel', 'POST', {});
            await ui.refresh()
        }));
        results.append(row)
    }
}
