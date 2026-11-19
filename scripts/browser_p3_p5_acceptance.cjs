const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawnSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
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
    await page.getByRole('heading', {name: '这台 Mac · 权限与范围'}).waitFor();
    const allowedDirectory = path.join(workerState, 'acceptance-allowed-files');
    fs.mkdirSync(allowedDirectory, {recursive: true});
    await page.getByLabel('允许应用').fill('TextEdit');
    await page.getByLabel('允许目录', {exact: true}).fill(allowedDirectory);
    await page.getByLabel('允许启动允许列表应用').check();
    await page.getByLabel('允许在允许目录中创建新文件').check();
    await page.getByRole('button', {name: '保存设备范围'}).click();
    await page.getByRole('heading', {name: '这台 Mac · 权限与范围'}).waitFor();
    await page.getByRole('button', {name: '保存设备范围'}).waitFor();
    await resetScroll();
    await page.waitForTimeout(400);
    const capabilities = await api('capabilities');
    assert.equal(capabilities.mac_execute, true);
    assert.equal(capabilities.mac_execute_scope, 'allowlisted_app_launch');
    assert.equal(capabilities.mac_file_write, true);
    assert.equal(capabilities.mac_file_write_scope, 'allowlisted_directory_create_only');
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

    const fileSkill = page.locator('article').filter({has: page.getByRole('heading', {name: 'Mac 创建允许文件'})});
    await fileSkill.getByRole('button', {name: '安装并检查'}).click();
    await fileSkill.getByRole('button', {name: '确认授权并启用'}).click();
    const targetFile = path.join(allowedDirectory, `acceptance-${crypto.randomUUID()}.txt`);
    const targetContent = 'Fairy browser acceptance file';
    await fileSkill.getByLabel('新文件的绝对路径').fill(targetFile);
    await fileSkill.getByLabel('新文件内容').fill(targetContent);
    await fileSkill.getByRole('button', {name: '创建受控文件'}).click();
    const createDialog = page.getByRole('dialog');
    await createDialog.getByRole('button', {name: '创建受控文件'}).click();
    await fileSkill.locator('.skill-output').getByText(/hash_and_byte_readback_matched/).waitFor();
    assert.equal(fs.readFileSync(targetFile, 'utf8'), targetContent);
    await resetScroll();
    await page.waitForTimeout(2500);
    await page.screenshot({
        path: 'docs/implementation/screenshots/p3-mac-file-create.png',
        fullPage: false,
    });

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
    const preservedConfig = (await api('config'))[0];
    assert.equal(preservedConfig.mac_execute, true);
    assert.equal(preservedConfig.mac_file_write, true);
    await page.waitForTimeout(250);
    await page.getByRole('button', {name: '从当前缺口刷新候选'}).click();
    const candidate = page.locator('article').filter({hasText: '继续练习：自主候选用例'});
    await candidate.waitFor();
    await candidate.getByRole('button', {name: '接受并加入目标'}).click();
    const goal = page.locator('article').filter({hasText: '继续练习：自主候选用例'});
    await goal.getByRole('button', {name: '开始执行'}).click();
    await goal.getByRole('button', {name: '暂停并保留进度'}).click();
    await goal.getByRole('button', {name: '继续执行'}).waitFor();
    const completionSummary = '已完成合成课程练习并记录验证结果。';
    const completionField = goal.locator('textarea');
    await completionField.fill(completionSummary);
    assert.equal(await completionField.inputValue(), completionSummary);
    const completionResponsePromise = page.waitForResponse(
        response => response.url().includes('/autonomy/goals/')
            && response.url().endsWith('/complete')
            && response.request().method() === 'POST'
    );
    await goal.getByRole('button', {name: '完成并结算'}).click();
    const completionResponse = await completionResponsePromise;
    assert.ok(completionResponse.ok(), await completionResponse.text());
    assert.equal(
        (await completionResponse.request().postDataJSON()).summary,
        completionSummary
    );
    await goal.getByText(completionSummary, {exact: true}).waitFor();
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
                'allowlisted create-only file write with hash verification',
                'skill install/grant/invoke/disable',
                'autonomy candidate generation and budget acceptance',
                'autonomy goal start, pause and actual-time settlement',
                'isolated evolution evaluation and review state',
                'PWA manifest and service worker',
                'browser voice input and read-aloud controls',
                'iPhone bottom tabs at 390px',
                'no horizontal overflow',
                'no browser runtime errors',
            ],
            synthetic_data: true,
            actual_file_created: true,
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
