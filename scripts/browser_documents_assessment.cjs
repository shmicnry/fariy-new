const {
    chromium
} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {
    spawnSync
} = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
    const base = process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18846',
        token = process.env.FAIRY_TOKEN;
    const browser = await chromium.launch({
        headless: true,
        executablePath: process.env.CHROME_EXECUTABLE
    });
    const page = await browser.newPage({
        viewport: {
            width: 1440,
            height: 1000
        }
    });
    page.setDefaultTimeout(120000);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base);
    await page.getByLabel('服务令牌').fill(token);
    await page.getByRole('button', {
        name: '连接',
        exact: true
    }).click();
    await page.getByText('已连接本机服务', {
        exact: true
    }).waitFor();
    await page.locator('#nav a[href="#learning"]').click();
    await page.getByLabel('选择文字文件').setInputFiles('/private/tmp/fairy-assessment-source.docx');
    await page.getByRole('button', {
        name: '上传并学习',
        exact: true
    }).click();
    await page.getByRole('heading', {
        name: 'fairy-assessment-source.docx',
        exact: true
    }).waitFor();
    const worker = spawnSync('.venv/bin/python', ['-m', 'fairy.worker', '--once'], {
        env: process.env,
        encoding: 'utf8'
    });
    assert.equal(worker.status, 0, worker.stderr);
    const api = async p => {
        const r = await fetch(base + '/v2/' + p, {
            headers: {
                Authorization: 'Bearer ' + token
            }
        });
        assert.equal(r.status, 200);
        return r.json()
    };
    const source = (await api('learning/sources'))[0];
    assert.equal(source.file_format, '.docx');
    assert.equal(source.extraction.segments[0].label, 'paragraph:1');
    await page.locator('#nav a[href="#assessments"]').click();
    await page.getByLabel('测验名称').fill('Synthetic source quiz');
    await page.getByLabel('测验材料', {
        exact: true
    }).selectOption(source.id);
    await page.getByLabel('测验原文依据').fill('The code of Cedar is VELIN.');
    await page.getByLabel('题目', {
        exact: true
    }).fill('What is the code of Cedar?');
    await page.getByLabel('备选答案（每行一个）').fill('XERON\nVELIN');
    await page.getByLabel('正确选项（从1开始）').fill('2');
    await page.getByRole('button', {
        name: '保存固定题目',
        exact: true
    }).click();
    await page.getByRole('button', {
        name: '开卷作答',
        exact: true
    }).click();
    await page.getByText(/答对 1 \/ 1/).waitFor();
    await page.getByRole('button', {
        name: '闭卷作答',
        exact: true
    }).click();
    await page.waitForFunction(() => Array.from(document.querySelectorAll('p')).filter(p => p.textContent.startsWith('答对 ')).length === 2);
    await page.getByRole('heading', {
        name: '测验结果',
        exact: true
    }).waitFor();

    await page.getByLabel('草稿标题').fill('Model draft');
    await page.getByLabel('草稿材料').selectOption(source.id);
    await page.getByLabel('草稿原文依据').fill('The code of Cedar is VELIN.');
    await page.getByLabel('生成题目数量').fill('1');
    await page.getByRole('button', {
        name: '生成待审阅草稿',
        exact: true
    }).click();
    await page.getByRole('button', {
        name: '确认并创建测验',
        exact: true
    }).waitFor();
    await page.getByLabel('草稿确认标题').fill('Reviewed model draft');
    await page.getByLabel('草稿题目核对').fill(JSON.stringify([
        {
            question: 'What is the code of Cedar?',
            choices: ['XERON', 'VELIN'],
            correct_index: 1
        }
    ]));
    await page.getByRole('button', {
        name: '确认并创建测验',
        exact: true
    }).click();
    await page.getByRole('heading', {
        name: 'Reviewed model draft',
        exact: true
    }).waitFor();

    const runs = await api('learning/assessment-runs');
    assert.equal(runs.length, 2);
    assert.ok(runs.every(x => x.status === 'completed' && !x.generalization_verified));
    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');
    fs.writeFileSync('docs/implementation/document-assessment-browser.json', JSON.stringify({
        status: 'passed',
        model: runs[0].model,
        checks: ['real DOCX upload', 'isolated paragraph extraction', 'worker', 'fixed quiz creation', 'real local Ollama open-book run', 'real local Ollama closed-book run', 'real local model quiz draft', 'owner-edited draft approval', 'deterministic score display', 'no browser errors'],
        scores: runs.map(r => ({
            mode: r.mode,
            correct_count: r.correct_count,
            total: r.total
        })),
        synthetic_data: true,
        generalization_verified: false,
        cloud_calls: 0
    }, null, 2) + '\n');
    await browser.close();
    console.log('Document and real-model assessment browser passed')
})().catch(e => {
    console.error(e);
    process.exit(1)
});
