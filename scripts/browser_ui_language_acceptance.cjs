const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const base = process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18860';
const token = process.env.FAIRY_TOKEN;

async function request(path, method = 'GET', body) {
    const response = await fetch(base + '/v2/' + path, {
        method,
        headers: {
            Authorization: 'Bearer ' + token,
            'Content-Type': 'application/json',
            'Idempotency-Key': crypto.randomUUID(),
        },
        body: body ? JSON.stringify(body) : undefined,
    });
    const payload = await response.json();
    assert.equal(response.ok, true, JSON.stringify(payload));
    return payload;
}

(async () => {
    const browser = await chromium.launch({
        headless: true,
        executablePath: process.env.CHROME_EXECUTABLE,
    });
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.getByLabel('服务令牌').fill(token);
    await page.getByRole('button', {name: '连接', exact: true}).click();
    await page.getByText('已连接本机服务', {exact: true}).waitFor();

    const resizer = page.getByRole('separator', {name: '调整侧边栏宽度'});
    const initialWidth = await page.evaluate(
        () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width'))
    );
    await resizer.focus();
    await resizer.press('ArrowRight');
    const keyboardWidth = await page.evaluate(
        () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width'))
    );
    assert.equal(keyboardWidth, initialWidth + 16);
    await resizer.dblclick();
    const resetWidth = await page.evaluate(
        () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width'))
    );
    assert.equal(resetWidth, 238);

    await page.locator('#nav a[href="#learning"]').click();
    const longName = `2026-11-18-Fairy-${crypto.randomUUID()}-learning-source-with-important-suffix.md`;
    await page.getByLabel('选择文字文件').setInputFiles({
        name: longName,
        mimeType: 'text/markdown',
        buffer: Buffer.from('Fairy 的长文件名应保留扩展名。'),
    });
    await page.getByRole('button', {name: '上传并学习', exact: true}).click();
    const compactHeading = page.locator(`#content h2[title="${longName}"]`);
    await compactHeading.waitFor();
    assert.match(await compactHeading.innerText(), /…\.md$/);

    await page.locator('#nav a[href="#world"]').click();
    const sourceCard = page.locator('article').filter({hasText: longName});
    await sourceCard.getByRole('button', {name: '删除这份来源', exact: true}).click();
    const confirm = page.locator('#detailDialog');
    await confirm.waitFor({state: 'visible'});
    assert.equal(await confirm.getAttribute('data-variant'), 'confirm');
    await confirm.evaluate(element => element.dispatchEvent(
        new MouseEvent('click', {bubbles: true})
    ));
    assert.equal(await confirm.isVisible(), true);
    await confirm.getByRole('button', {name: '取消', exact: true}).click();

    await request('approvals', 'POST', {
        title: '抽屉测试',
        text: '通知中心应作为侧边抽屉打开。',
    });
    await page.getByRole('button', {name: '打开通知中心', exact: true}).click();
    await confirm.waitFor({state: 'visible'});
    assert.equal(await confirm.getAttribute('data-variant'), 'drawer');
    assert.equal(await confirm.evaluate(element => element.classList.contains('detail-drawer')), true);
    await confirm.getByRole('button', {name: '关闭详情', exact: true}).click();

    await page.locator('#nav a[href="#cards"]').click();
    await page.getByLabel('标题', {exact: true}).fill('Toast 测试卡片');
    await page.getByLabel('内容', {exact: true}).fill('完成后应出现 Toast。');
    await page.getByRole('button', {name: '创建卡片', exact: true}).click();
    await page.locator('.toast').filter({hasText: '创建卡片已完成'}).waitFor();

    await page.locator('#nav a[href="#chat"]').click();
    const scroller = page.locator('.conversation-scroll');
    await scroller.waitFor();
    await page.evaluate(() => {
        const output = document.querySelector('.conversation-scroll');
        for (let index = 0; index < 40; index += 1) {
            const item = document.createElement('article');
            item.className = 'conversation';
            item.textContent = '测试消息 ' + index + ' · '.repeat(12);
            output.append(item);
        }
        output.scrollTop = 80;
        output.dispatchEvent(new Event('scroll'));
    });
    const jump = page.getByRole('button', {name: '跳到最新', exact: true});
    await jump.waitFor();
    await jump.click();
    await page.waitForFunction(() => {
        const element = document.querySelector('.conversation-scroll');
        return Math.abs(element.scrollHeight - element.scrollTop - element.clientHeight) < 4;
    });
    assert.equal(
        await scroller.evaluate(element =>
            Math.abs(element.scrollHeight - element.scrollTop - element.clientHeight) < 4
        ),
        true
    );

    const composer = page.getByLabel('输入消息');
    await composer.fill('中文输入法组合态');
    await composer.evaluate(element => element.dispatchEvent(
        new KeyboardEvent('keydown', {
            key: 'Enter',
            code: 'Enter',
            keyCode: 229,
            isComposing: true,
            bubbles: true,
        })
    ));
    assert.equal(await composer.inputValue(), '中文输入法组合态');
    assert.equal(await page.locator('#error').innerText(), '');

    const currentConfigs = await request('config');
    const currentConfig = currentConfigs[0] || {revision: 0};
    await request('config', 'PUT', {
        revision: currentConfig.revision,
        daily_minutes: currentConfig.daily_minutes ?? 45,
        pet_enabled: currentConfig.pet_enabled ?? false,
        mac_execute: true,
        mac_allowed_apps: ['TextEdit'],
        mac_allowed_paths: currentConfig.mac_allowed_paths || [],
        autonomous_paid: currentConfig.autonomous_paid ?? false,
        autonomy_enabled: currentConfig.autonomy_enabled ?? false,
        autonomy_daily_minutes: currentConfig.autonomy_daily_minutes ?? 30,
        autonomy_daily_items: currentConfig.autonomy_daily_items ?? 10,
    });
    await page.locator('#nav a[href="#evolution"]').click();
    await page.getByRole('button', {name: '保存自主预算', exact: true}).click();
    await page.locator('.toast').filter({hasText: '保存自主预算已完成'}).waitFor();
    const updatedConfig = (await request('config'))[0];
    assert.equal(updatedConfig.mac_execute, true);
    assert.deepEqual(updatedConfig.mac_allowed_apps, ['TextEdit']);

    const experimentDraft = 'background-event-draft-' + crypto.randomUUID();
    const experimentField = page.getByLabel('实验用例与候选输出（JSON）');
    await experimentField.fill(experimentDraft);
    await request('evolution/experiments', 'POST', {
        name: '保稿竞态事件',
        baseline: 'baseline',
        cases: [{input: '测试', required_terms: ['正确'], forbidden_terms: []}],
        candidates: [
            {name: 'baseline', outputs: ['正确']},
            {name: 'candidate', outputs: ['正确且完整']},
        ],
    });
    await page.locator('#syncNotice').waitFor({state: 'visible'});
    await page.waitForTimeout(350);
    assert.equal(await experimentField.inputValue(), experimentDraft);
    assert.equal(await page.locator('#syncNotice').isVisible(), true);

    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await resizer.isVisible(), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert.deepEqual(errors, []);

    fs.writeFileSync(
        'docs/implementation/ui-language-browser-results.json',
        JSON.stringify({
            status: 'passed',
            checks: [
                'keyboard-resizable macOS sidebar',
                'double-click sidebar reset',
                'long filename truncation preserves suffix',
                'confirmation dialog blocks backdrop dismissal',
                'notification center uses drawer',
                'explicit action confirmation labels',
                'toast completion feedback',
                'chat stops following after upward scroll',
                'jump-to-latest behavior',
                'IME composition does not submit',
                'autonomy settings preserve Mac execution scope',
                'draft survives background event refresh',
                'iPhone layout has no horizontal overflow',
                'no browser runtime errors',
            ],
            synthetic_data: true,
        }, null, 2) + '\n'
    );
    await browser.close();
    console.log('UI language acceptance passed');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
