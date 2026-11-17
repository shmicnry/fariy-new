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
    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');
    fs.writeFileSync('docs/implementation/p2-browser-results.json', JSON.stringify({
        status: 'passed',
        checks: ['file upload', 'worker', 'practice with citation', 'source search', 'no runtime errors'],
        synthetic_data: true
    }, null, 2) + '\n');
    await browser.close();
    console.log('P2 browser passed')
})().catch(e => {
    console.error(e);
    process.exit(1)
});
