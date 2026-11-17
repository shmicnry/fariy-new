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
    const context = await browser.newContext({
        viewport: {width: 1440, height: 1000},
        permissions: ['notifications'],
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));

    await page.goto(base);
    await page.getByLabel('服务令牌').fill(token);
    await page.getByRole('button', {name: '连接', exact: true}).click();
    await page.getByText('已连接本机服务', {exact: true}).waitFor();
    await page.locator('#nav a[href="#approvals"]').click();
    await page.getByPlaceholder('笔记标题').waitFor();

    await request('approvals', 'POST', {
        title: '同步测试操作',
        text: '验证实时更新和通知中心。',
    });
    await page.getByText('同步测试操作', {exact: true}).waitFor();
    await page.locator('#notificationBadge').waitFor({state: 'visible'});

    await page.locator('#nav a[href="#cards"]').click();
    const draft = page.getByLabel('标题', {exact: true});
    await draft.fill('不要被后台刷新覆盖');
    await request('cards', 'POST', {
        title: '后台新增卡片',
        text: '这条记录由 SSE 更新发现。',
        subtype: 'note',
        remind_at: null,
    });
    await page.locator('#syncNotice').waitFor({state: 'visible'});
    assert.equal(await draft.inputValue(), '不要被后台刷新覆盖');

    await page.getByRole('button', {name: '打开通知中心', exact: true}).click();
    const dialog = page.locator('#detailDialog');
    await dialog.waitFor({state: 'visible'});
    await dialog.getByText('通知中心', {exact: true}).waitFor();
    assert.ok(await dialog.locator('.notification-row').count() >= 2);
    await dialog.getByRole('button', {name: '全部标为已读', exact: true}).click();
    await page.locator('#notificationBadge').waitFor({state: 'hidden'});
    await page.screenshot({
        path: 'docs/implementation/screenshots/notification-center.png',
        fullPage: false,
    });

    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');
    fs.writeFileSync(
        'docs/implementation/sync-notifications-browser-results.json',
        JSON.stringify({
            status: 'passed',
            checks: [
                'SSE event refresh on approvals page',
                'notification badge from background event',
                'dirty form preserved with refresh notice',
                'notification center shows multiple event types',
                'mark all notifications read',
                'no browser runtime errors',
            ],
            synthetic_data: true,
            external_push_tested: false,
        }, null, 2) + '\n'
    );
    await browser.close();
    console.log('Sync and notification acceptance passed');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
