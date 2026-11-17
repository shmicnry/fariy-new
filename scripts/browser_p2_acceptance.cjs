const {
    chromium
} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {
    spawnSync
} = require('node:child_process');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
    const browser = await chromium.launch({
        headless: true,
        executablePath: process.env.CHROME_EXECUTABLE
    });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18844');
    await page.getByLabel('服务令牌').fill(process.env.FAIRY_TOKEN);
    await page.getByRole('button', {
        name: '连接',
        exact: true
    }).click();
    await page.getByText('已连接本机服务', {
        exact: true
    }).waitFor();
    await page.locator('nav a[href="#learning"]').click();
    await page.getByLabel('选择文字文件').setInputFiles({
        name: '植物知识.md',
        mimeType: 'text/markdown',
        buffer: Buffer.from('植物需要阳光和水分。')
    });
    await page.getByRole('button', {
        name: '上传并学习',
        exact: true
    }).click();
    await page.getByRole('heading', {
        name: '植物知识.md',
        exact: true
    }).waitFor();
    const w = spawnSync('.venv/bin/python', ['-m', 'fairy.worker', '--once'], {
        env: process.env,
        encoding: 'utf8'
    });
    assert.equal(w.status, 0, w.stderr);
    await page.locator('nav a[href="#overview"]').click();
    await page.locator('nav a[href="#learning"]').click();
    await page.getByPlaceholder('练习答案').fill('植物生长需要阳光。');
    await page.getByPlaceholder('用于支持答案的原文摘录').fill('植物需要阳光和水分。');
    await page.getByRole('button', {
        name: '提交有出处的练习',
        exact: true
    }).click();
    await page.getByRole('button', {
        name: '查看练习记录',
        exact: true
    }).click();
    await page.getByText('未自动评分，需人工核对', {
        exact: true
    }).waitFor();
    await page.getByPlaceholder('检索学习资料关键词').fill('植物');
    await page.getByRole('button', {
        name: '检索资料',
        exact: true
    }).click();
    await page.getByText(/原文位置 0/).waitFor();
    await page.locator('nav a[href="#world"]').click();
    await page.getByLabel('来源标签 植物知识.md').selectOption('primary');
    await page.getByLabel('复核理由 植物知识.md').fill('人工核对了材料出处');
    await Promise.all([
        page.waitForResponse(response => response.url().includes('/v2/learning/sources/') && response.request().method() === 'PATCH'),
        page.getByRole('button', {
            name: '保存来源复核',
            exact: true
        }).click()
    ]);
    const materials = await (await fetch((process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18844') + '/v2/learning/sources', {
        headers: {
            Authorization: 'Bearer ' + process.env.FAIRY_TOKEN
        }
    })).json();
    await page.getByLabel('实体或主题').fill('植物');
    await page.getByLabel('属性或关系').fill('需求');
    await page.getByLabel('主张内容').fill('阳光和水分');
    await page.getByLabel('引用材料 ID').fill(materials[0].id);
    await page.getByLabel('逐字原文依据').fill('植物需要阳光和水分。');
    await page.getByRole('button', {
        name: '登记知识主张',
        exact: true
    }).click();
    await page.getByRole('heading', {
        name: '植物 / 需求',
        exact: true
    }).waitFor();
    await page.getByRole('button', {
        name: '撤回这条主张',
        exact: true
    }).click();
    await page.getByRole('heading', {
        name: '植物 / 需求',
        exact: true
    }).waitFor({
        state: 'detached'
    });
    await page.locator('nav a[href="#learning"]').click();
    await page.getByRole('button', {
        name: '评定练习与查看效果',
        exact: true
    }).click();
    await page.getByLabel('练习评分').fill('4');
    await page.getByPlaceholder('评定理由与不足').fill('内容与原文一致，迁移能力未测试');
    await page.getByRole('button', {
        name: '保存练习评定',
        exact: true
    }).click();
    await page.getByRole('button', {
        name: '评定练习与查看效果',
        exact: true
    }).click();
    await page.getByText(/最近分数 4/).waitFor();
    await page.getByPlaceholder('填写用于最终确认的逐字原文依据').fill('植物需要阳光和水分。');
    await page.getByRole('button', {
        name: '记录通过',
        exact: true
    }).click();
    await page.getByRole('button', {
        name: '归纳为习得知识',
        exact: true
    }).waitFor();
    await page.locator('nav a[href="#world"]').click();
    await page.getByText('删除这份来源', {
        exact: true
    }).click();
    await page.getByRole('button', {
        name: '确认删除来源',
        exact: true
    }).click();
    const skills = await (await fetch((process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18844') + '/v2/skills', {
        headers: {
            Authorization: 'Bearer ' + process.env.FAIRY_TOKEN
        }
    })).json();
    assert.deepEqual(skills, []);
    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');
    fs.writeFileSync('docs/implementation/p2-browser-results.json', JSON.stringify({
        status: 'passed',
        checks: ['file upload', 'worker', 'practice with citation', 'source search', 'no runtime errors', 'source review', 'world claim with quote and withdrawal', 'practice rubric grade', 'exact final evidence', 'course completion gate', 'source deletion revokes acquired knowledge'],
        synthetic_data: true
    }, null, 2) + '\n');
    await browser.close();
    console.log('P2 browser passed')
})().catch(e => {
    console.error(e);
    process.exit(1)
});
