import {
    explain
} from './p1.js';

export async function renderAssessments(ui) {
    const {
        el,
        api,
        panel,
        button,
        confirmButton
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
        evidence = make(form, '测验原文依据');
    const sourceLabel = el('label', '测验材料', 'field');
    const source = el('select');
    source.setAttribute('aria-label', '测验材料');
    const sourceMaterials = await api('learning/sources');
    if (!sourceMaterials.length) {
        const empty = el('option', '请先在「学习中心」投喂材料');
        empty.value = '';
        empty.disabled = true;
        empty.selected = true;
        source.append(empty);
    }
    for (const material of sourceMaterials) {
        const option = el(
            'option',
            material.title + ' · ' + (material.quality?.rating || 'unreviewed')
        );
        option.value = material.id;
        option.disabled = !material.source_eligible;
        if (!material.source_eligible) option.textContent += '（当前不可用）';
        source.append(option);
    }
    const firstEligible = [...source.options].find(option => !option.disabled);
    if (firstEligible) source.value = firstEligible.value;
    sourceLabel.append(source);
    form.append(sourceLabel);
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

    const drafts = panel('模型测题草稿');
    drafts.append(el(
        'p',
        '本地模型只生成候选题。你必须核对原文、修改答案并确认后，草稿才会变成可执行测验。',
        'muted'
    ));
    const draftTitle = make(drafts, '草稿标题'),
        draftEvidence = make(drafts, '草稿原文依据'),
        draftCount = make(drafts, '生成题目数量');
    draftCount.type = 'number';
    draftCount.min = 1;
    draftCount.max = 5;
    draftCount.value = 3;
    const draftSourceLabel = el('label', '草稿材料', 'field');
    const draftSource = el('select');
    draftSource.setAttribute('aria-label', '草稿材料');
    for (const material of sourceMaterials) {
        const option = el('option', material.title);
        option.value = material.id;
        option.disabled = !material.source_eligible;
        draftSource.append(option);
    }
    if (firstEligible) draftSource.value = source.value;
    draftSourceLabel.append(draftSource);
    drafts.append(
        draftSourceLabel,
        button('生成待审阅草稿', async () => {
            const result = await api('learning/quizzes/drafts', 'POST', {
                source_id: draftSource.value,
                title: draftTitle.value,
                evidence: draftEvidence.value,
                question_count: Number(draftCount.value),
            });
            if (result.status === 'failed') {
                throw Error('草稿生成失败：' + explain(result.error));
            }
            await ui.refresh();
        })
    );
    for (const draft of await api('learning/quizzes/drafts')) {
        if (draft.status !== 'pending_review') continue;
        const row = el('article', undefined, 'memory-row');
        const reviewTitle = el('input');
        reviewTitle.value = draft.title;
        reviewTitle.setAttribute('aria-label', '草稿确认标题');
        const reviewQuestions = el('textarea');
        reviewQuestions.value = JSON.stringify(
            draft.questions.map(({question, choices, correct_index}) => ({
                question,
                choices,
                correct_index,
            })),
            null,
            2
        );
        reviewQuestions.setAttribute('aria-label', '草稿题目核对');
        row.append(
            el('h3', draft.title),
            el('p', '模型 ' + draft.model + ' · 待人工审阅 · 尚不可执行', 'route-note'),
            el('blockquote', draft.evidence),
            el('label', '草稿确认标题', 'field'),
            el('label', '草稿题目核对', 'field')
        );
        row.querySelectorAll('label')[0].append(reviewTitle);
        row.querySelectorAll('label')[1].append(reviewQuestions);
        row.append(
            button('确认并创建测验', async () => {
                let questions;
                try {
                    questions = JSON.parse(reviewQuestions.value);
                } catch {
                    throw Error('草稿题目 JSON 格式不正确');
                }
                await api(
                    'learning/quizzes/drafts/' + draft.id + '/approve',
                    'POST',
                    {
                        revision: draft.revision,
                        title: reviewTitle.value,
                        questions,
                    }
                );
                await ui.refresh();
            }),
            confirmButton(
                '拒绝这份草稿',
                '拒绝模型草稿',
                '拒绝后不能执行，也不会创建测验。',
                async () => {
                    await api(
                        'learning/quizzes/drafts/' + draft.id + '/reject',
                        'POST',
                        {
                            revision: draft.revision,
                            reason: 'owner_rejected_model_draft',
                        }
                    );
                    await ui.refresh();
                },
                'secondary'
            )
        );
        drafts.append(row);
    }
    const quizzes = panel('本机作答');
    for (const q of await api('learning/quizzes')) {
        const row = el('article', undefined, 'memory-row');
        row.append(el('h3', q.title), el('p', '题目 ' + q.questions.length + ' 道' + (q.source_eligible ? '' : '；来源已失效')));
        for (const [mode, label] of [
                ['open_book', '开卷作答'],
                ['closed_book', '闭卷作答']
            ]) row.append(button(label, async () => {
            const r = await api('learning/quizzes/' + q.id + '/runs', 'POST', {
                mode
            });
            if (r.status === 'failed') throw Error('作答失败：' + explain(r.error));
            await ui.refresh()
        }));
        row.append(confirmButton(
            '撤回这份测验',
            '撤回固定测验',
            '撤回后不能再发起新的作答，已有关联记录会被标记失效。',
            async () => {
                await api('records/' + q.id + '?revision=' + q.revision, 'DELETE');
                await ui.refresh()
            }
        ));
        quizzes.append(row)
    }
    const results = panel('测验结果');
    for (const r of (await api('learning/assessment-runs')).reverse()) {
        const row = el('article', undefined, 'memory-row');
        row.append(el('p', (r.mode === 'open_book' ? '开卷' : '闭卷') + ' · ' + r.model), el('p', r.status === 'completed' ? '答对 ' + r.correct_count + ' / ' + r.total + '，程序按固定答案计分' : r.error || r.status));
        if (r.status === 'completed' && !r.source_eligible) {
            row.append(el('p', '来源已失效，这次得分不再计入当前学习效果。', 'route-note'));
        }
        if (r.status === 'pending') row.append(button('停止本次作答', async () => {
            await api('learning/assessment-runs/' + r.id + '/cancel', 'POST', {});
            await ui.refresh()
        }));
        results.append(row)
    }
}
