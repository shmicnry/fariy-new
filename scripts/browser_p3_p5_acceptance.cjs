const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawnSync} = require('node:child_process');
const fs = require('node:fs');
const assert = require('node:assert/strict');

const base = process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18860';
const token = process.env.FAIRY_TOKEN;
const workerState = process.env.FAIRY_STATE_DIR;
const workerDatabase = process.env.FAIRY_DATABASE_URL;
if (!workerState || !workerDatabase) {
    throw new Error(
        'P3-P5 browser acceptance requires explicit FAIRY_STATE_DIR and FAIRY_DATABASE_URL'
    );
}
const jsonHeaders = {
    Authorization: 'Bearer ' + token,
    'Content-Type': 'application/json',
};

async function api(path, method = 'GET', body) {
    const response = await fetch(base + '/v2/' + path, {
        method,
        headers: {...jsonHeaders, 'Idempotency-Key': crypto.randomUUID()},
        body: body ? JSON.stringify(body) : undefined,
    });
    const payload = await response.json();
    assert.ok(response.ok, JSON.stringify(payload));
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
    const resetScroll = () => page.evaluate(() => {
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;
        for (const element of document.querySelectorAll('*')) {
            if (element.scrollTop) element.scrollTop = 0;
        }
    });

    await page.goto(base);
    await page.getByLabel('服务令牌').fill(token);
    await page.getByRole('button', {name: '连接', exact: true}).click();
    await page.getByText('已连接本机服务', {exact: true}).waitFor();

    const manifest = await fetch(base + '/assets/manifest.webmanifest');
    assert.equal(manifest.status, 200);
    assert.equal((await manifest.json()).display, 'standalone');
    await page.waitForFunction(() => navigator.serviceWorker?.controller || navigator.serviceWorker?.ready);

    await page.locator('#nav a[href="#mac"]').click();
    await page.getByRole('heading', {name: '这台 Mac · 只读状态'}).waitFor();
    await page.getByLabel('允许应用').fill('TextEdit');
    await page.getByLabel('允许启动允许列表应用').check();
    await page.getByRole('button', {name: '保存设备范围'}).click();
    await page.getByRole('heading', {name: '这台 Mac · 只读状态'}).waitFor();
    await page.getByRole('button', {name: '保存设备范围'}).waitFor();
    await resetScroll();
    await page.waitForTimeout(400);
    const capabilities = await api('capabilities');
    assert.equal(capabilities.mac_execute, true);
    assert.equal(capabilities.mac_execute_scope, 'allowlisted_app_launch');
    await page.screenshot({
        path: 'docs/implementation/screenshots/p3-mac-desktop.png',
        fullPage: false,
    });

    await page.locator('#nav a[href="#skills"]').click();
    const statusSkill = page.locator('article').filter({has: page.getByRole('heading', {name: 'Mac 只读状态'})});
    await statusSkill.getByRole('button', {name: '安装并检查'}).click();
    await statusSkill.getByRole('button', {name: '确认授权并启用'}).click();
    await statusSkill.getByRole('button', {name: '只读执行一次'}).click();
    await statusSkill.locator('.skill-output').getByText(/arbitrary_shell/).waitFor();
    await statusSkill.getByRole('button', {name: '停用并撤销授权'}).click();
    await page.getByRole('dialog').getByRole('button', {name: '停用并撤销授权'}).click();

    const material = await api('learning/materials', 'POST', {
        title: '自主候选用例',
        text: '光合作用需要光照。',
    });
    let course;
    for (let attempt = 0; attempt < 10; attempt += 1) {
        const worker = spawnSync('.venv/bin/python', ['-m', 'fairy.worker', '--once'], {
            env: {
                ...process.env,
                FAIRY_STATE_DIR: workerState,
                FAIRY_DATABASE_URL: workerDatabase,
            },
            encoding: 'utf8',
        });
        assert.equal(worker.status, 0, worker.stderr);
        course = (await api('learning/courses')).find(item => item.id === material.course.id);
        if (course?.stage === 'awaiting_assessment') break;
    }
    assert.equal(course?.stage, 'awaiting_assessment', 'worker did not finish the acceptance course');
    const assessment = await fetch(base + '/v2/learning/courses/' + course.id + '/assess', {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
            revision: course.revision,
            passed: false,
            evidence: '需要更多练习',
        }),
    });
    assert.ok(assessment.ok, await assessment.text());

    await page.locator('#nav a[href="#evolution"]').click();
    await page.getByLabel('启用自主候选').check();
    await page.getByRole('button', {name: '保存自主预算'}).click();
    await page.waitForTimeout(250);
    await page.getByRole('button', {name: '从当前缺口刷新候选'}).click();
    const candidate = page.locator('article').filter({hasText: '继续练习：自主候选用例'});
    await candidate.waitFor();
    await candidate.getByRole('button', {name: '接受并加入目标'}).click();
    await page.getByRole('button', {name: '运行隔离评测'}).click();
    await page.getByRole('heading', {name: '回答约束实验', exact: true}).waitFor();
    await page.getByRole('button', {name: '记录为待人工评审', exact: true}).click();
    await page.getByText(/运行版本未改变/).first().waitFor();
    await page.getByRole('heading', {name: '隔离进化实验', exact: true}).waitFor();
    await resetScroll();
    await page.waitForTimeout(400);
    await page.screenshot({
        path: 'docs/implementation/screenshots/p5-autonomy-desktop.png',
        fullPage: false,
    });

    await page.setViewportSize({width: 390, height: 844});
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.locator('nav a[href="#chat"]').last().click();
    await page.getByRole('heading', {name: '与 Fairy 对话', exact: true}).waitFor();
    await page.getByRole('button', {name: '语音输入', exact: true}).waitFor();
    await page.getByRole('button', {name: '朗读最新回答', exact: true}).waitFor();
    await resetScroll();
    await page.waitForTimeout(400);
    const panelOpacity = await page.locator('#content .panel').first().evaluate(element => getComputedStyle(element).opacity);
    assert.equal(panelOpacity, '1');
    const tabs = page.locator('#mobileTabs');
    await tabs.waitFor();
    assert.equal(await tabs.locator('a').count(), 5);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({
        path: 'docs/implementation/screenshots/p4-iphone-layout.png',
        fullPage: false,
    });
    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');

    fs.writeFileSync(
        'docs/implementation/p3-p5-browser-results.json',
        JSON.stringify({
            status: 'passed',
            checks: [
                'macOS-style management shell',
                'read-only Mac status',
                'allowlisted launch scope configured without launching',
                'skill install/grant/invoke/disable',
                'autonomy candidate generation and budget acceptance',
                'isolated evolution evaluation and review state',
                'PWA manifest and service worker',
                'browser voice input and read-aloud controls',
                'iPhone bottom tabs at 390px',
                'no horizontal overflow',
                'no browser runtime errors',
            ],
            synthetic_data: true,
            actual_app_launched: false,
            runtime_evolution_applied: false,
        }, null, 2) + '\n'
    );
    await browser.close();
    console.log('P3-P5 browser acceptance passed');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
