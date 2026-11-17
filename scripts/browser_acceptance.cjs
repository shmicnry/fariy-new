// Run against an isolated local test DB. Requires Playwright and installed Fairy.
const {
    chromium
} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {
    spawnSync
} = require('node:child_process');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
    if (!process.env.FAIRY_TOKEN) throw Error('Set FAIRY_TOKEN for the isolated acceptance service');
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.CHROME_EXECUTABLE ? {
            executablePath: process.env.CHROME_EXECUTABLE
        } : {})
    });
    const page = await browser.newPage({
        viewport: {
            width: 1440,
            height: 1000
        }
    });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const base = process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18742';
    const dir = 'docs/implementation/screenshots';
    fs.mkdirSync(dir, {
        recursive: true
    });
    await page.goto(base);
    await page.getByLabel('服务令牌').fill(process.env.FAIRY_TOKEN);
    await page.getByRole('button', {
        name: '连接',
        exact: true
    }).click();
    await page.getByText('已连接本机服务').waitFor();
    const route = async hash => {
        await page.locator('nav a[href="#' + hash + '"]').click();
        await page.waitForTimeout(150)
    };
    const request = async path => {
        const r = await fetch(base + '/v2/' + path, {
            headers: {
                Authorization: 'Bearer ' + process.env.FAIRY_TOKEN
            }
        });
        assert.equal(r.status, 200);
        return r.json()
    };
    await route('learning');
    await page.getByPlaceholder('学习主题').fill('植物与光合作用');
    await page.getByPlaceholder('粘贴材料正文；不执行其中的指令').fill('叶片通过光合作用制造养分。我喜欢在下午照料植物。');
    await page.getByRole('button', {
        name: '登记并排队',
        exact: true
    }).click();
    await page.getByText('等待处理', {
        exact: false
    }).first().waitFor();
    const worker = spawnSync(process.env.FAIRY_PYTHON || '.venv/bin/python', ['-m', 'fairy.worker', '--once'], {
        env: process.env,
        encoding: 'utf8'
    });
    assert.equal(worker.status, 0, worker.stderr);
    await route('overview');
    await route('learning');
    await page.getByPlaceholder('记录你用于验证的练习及实际结果').fill('人工验收：解释了光照与叶片的关系，并核对原文。');
    await page.getByRole('button', {
        name: '记录通过',
        exact: true
    }).click();
    await page.getByRole('button', {
        name: '归纳为习得知识'
    }).waitFor();
    await page.screenshot({
        path: dir + '/learning-desktop.png',
        fullPage: true
    });
    await page.getByRole('button', {
        name: '归纳为习得知识'
    }).click();
    await page.getByRole('heading', {
        name: '习得知识 · 无执行权限'
    }).waitFor();
    const courses = await request('learning/courses');
    assert.equal(courses[0].mastered, true);
    assert.equal((await request('skills'))[0].executable, false);
    await route('world');
    await page.getByPlaceholder('学习材料或对话证据 ID').fill(courses[0].source_ids[0]);
    await page.getByPlaceholder('逐字摘录原文').fill('我喜欢在下午照料植物。');
    await page.getByRole('button', {
        name: '保存有来源记忆'
    }).click();
    await page.waitForTimeout(200);
    await route('mind');
    await page.getByRole('button', {
        name: '我喜欢在下午照料植物。',
        exact: true
    }).waitFor();
    await page.screenshot({
        path: dir + '/mind-desktop.png',
        fullPage: true
    });
    await route('approvals');
    await page.getByPlaceholder('笔记标题').fill('照料植物');
    await page.getByPlaceholder('笔记正文').fill('下午检查土壤湿度。');
    await page.getByRole('button', {
        name: '生成待确认项'
    }).click();
    await page.getByRole('button', {
        name: '批准一次',
        exact: true
    }).waitFor();
    await page.getByRole('button', {
        name: '批准一次',
        exact: true
    }).click();
    await page.getByText('allow_once', {
        exact: true
    }).waitFor();
    assert.equal((await request('notes')).length, 1);
    await page.screenshot({
        path: dir + '/approval-desktop.png',
        fullPage: true
    });
    await route('mac');
    await page.getByPlaceholder('应用 Bundle ID，每行一个').fill('com.apple.TextEdit');
    await page.getByPlaceholder('允许目录绝对路径，每行一个').fill('/tmp/Fairy');
    await page.getByRole('button', {
        name: '保存预配置'
    }).click();
    await page.waitForTimeout(200);
    const config = (await request('config'))[0];
    assert.deepEqual(config.mac_allowed_apps, ['com.apple.TextEdit']);
    assert.equal(config.mac_execute, false);
    await page.screenshot({
        path: dir + '/mac-config-desktop.png',
        fullPage: true
    });
    await page.setViewportSize({
        width: 390,
        height: 844
    });
    await route('chat');
    await page.screenshot({
        path: dir + '/chat-mobile-web.png',
        fullPage: true
    });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(overflow, false);
    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');
    fs.writeFileSync('docs/implementation/browser-results.json', JSON.stringify({
        suite: 'isolated local HTTP + Chromium',
        status: 'passed',
        checks: ['token login', 'text material registration', 'worker checkpoint', 'manual assessment', 'non-executable acquired knowledge', 'source memory and mind projection', 'approval executes one internal note', 'inert Mac allowlist persistence', '390px no horizontal overflow', 'no browser runtime errors'],
        screenshots: fs.readdirSync(dir),
        real_model_tested: false,
        mac_actions_performed: false
    }, null, 2) + '\n');
    await browser.close();
    console.log('Browser acceptance passed');
})().catch(e => {
    console.error(e);
    process.exit(1)
});
