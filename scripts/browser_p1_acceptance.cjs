// Opt-in: a fresh Fairy DB, real local Ollama, synthetic data, no cloud requests.
const {
    chromium
} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
    const base = process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18842';
    const token = process.env.FAIRY_TOKEN;
    if (!token) throw Error('Set FAIRY_TOKEN');
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
    page.setDefaultTimeout(120000);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const request = async (path, method = 'GET', body) => {
        const r = await fetch(base + '/v2/' + path, {
            method,
            headers: {
                Authorization: 'Bearer ' + token,
                'Content-Type': 'application/json',
                'Idempotency-Key': crypto.randomUUID()
            },
            body: body ? JSON.stringify(body) : undefined
        });
        assert.equal(r.status, 200, await r.clone().text());
        return r.json()
    };
    const dir = 'docs/implementation/screenshots/p1';
    fs.mkdirSync(dir, {
        recursive: true
    });
    await page.goto(base);
    await page.getByLabel('服务令牌').fill(token);
    await page.getByRole('button', {
        name: '连接',
        exact: true
    }).click();
    await page.getByText('已连接本机服务', {
        exact: true
    }).waitFor();
    const route = async value => {
        await page.locator('#nav a[href="#' + value + '"]').click()
    };
    await route('models');
    await page.getByRole('button', {
        name: '检测本机模型'
    }).click();
    await page.getByRole('button', {
        name: 'qwen3:4b',
        exact: true
    }).waitFor();
    await page.getByRole('button', {
        name: 'qwen3:4b',
        exact: true
    }).click();
    await page.getByLabel('云接口地址（兼容 Chat Completions）').fill('https://provider.example/v1');
    await page.getByLabel('云模型名称', {
        exact: true
    }).fill('fill-in-your-cloud-model');
    await page.getByLabel('云 API 密钥', {
        exact: true
    }).fill('synthetic-browser-key-not-a-real-credential');
    await page.getByLabel('每日云请求上限（UTC）').fill('2');
    await page.getByRole('button', {
        name: '保存模型与路由'
    }).click();
    await page.getByText(/已保存，配置版本/).waitFor();
    assert.equal(await page.getByLabel('云 API 密钥', {
        exact: true
    }).inputValue(), '');
    const cfg = await request('models/config');
    assert.equal(cfg.cloud_enabled, false);
    assert.equal(cfg.cloud_key_configured, true);
    assert.ok(!JSON.stringify(cfg).includes('synthetic-browser-key'));
    await page.screenshot({
        path: dir + '/models-desktop.png',
        fullPage: true
    });
    await route('chat');
    await page.getByLabel('本轮处理方式').selectOption('local_only');
    await page.getByLabel('输入消息').fill('请记住，我喜欢喝茉莉花茶。');
    await page.getByRole('button', {
        name: '发送',
        exact: true
    }).click();
    await page.getByRole('link', {
        name: '审阅本轮记忆提案'
    }).waitFor();
    assert.equal((await request('memories')).length, 0);
    await page.screenshot({
        path: dir + '/chat-desktop.png',
        fullPage: true
    });
    await route('memories');
    await page.getByRole('button', {
        name: '查看原文',
        exact: true
    }).first().click();
    await page.locator('blockquote.source').waitFor();
    await page.screenshot({
        path: dir + '/review-desktop.png',
        fullPage: true
    });
    await page.getByRole('button', {
        name: '确认记住',
        exact: true
    }).first().click();
    await page.getByText('纠正这条记忆', {
        exact: true
    }).waitFor();
    await page.getByText('纠正这条记忆', {
        exact: true
    }).click();
    await page.getByLabel('纠正后的内容').fill('我现在喜欢喝温水。');
    await page.getByLabel('纠正原因').fill('合成验收：更新偏好');
    await page.getByRole('button', {
        name: '保存纠正',
        exact: true
    }).click();
    await page.getByRole('heading', {
        name: '我现在喜欢喝温水。',
        exact: true
    }).waitFor();
    await page.getByRole('button', {
        name: '查看版本记录',
        exact: true
    }).click();
    await page.getByText('版本 1（已被纠正）', {
        exact: true
    }).waitFor();
    await page.screenshot({
        path: dir + '/correction-desktop.png',
        fullPage: true
    });
    const memories = await request('memories');
    assert.equal(memories[0].revision, 2);
    assert.equal((await request('memories?q=' + encodeURIComponent('喝茶'))).results.length, 0);
    await route('chat');
    await page.getByLabel('本轮处理方式').selectOption('local_only');
    await page.getByLabel('输入消息').fill('我喜欢喝什么？');
    await page.getByRole('button', {
        name: '发送',
        exact: true
    }).click();
    await page.getByText('回答已返回。', {
        exact: true
    }).waitFor();
    const turns = await request('turns');
    assert.ok(turns.at(-1).reply.includes('温水'));
    assert.ok(!turns.at(-1).reply.includes('茉莉花茶'));
    const syncText = '请用一句话说你好，测试实时同步。';
    await request('turns', 'POST', {
        text: syncText,
        routing: 'local_only'
    });
    await page.getByText(syncText, {
        exact: true
    }).waitFor();
    await route('memories');
    await page.setViewportSize({
        width: 390,
        height: 844
    });
    await page.getByRole('button', {
        name: '查看版本记录',
        exact: true
    }).click();
    await page.getByText('版本 1（已被纠正）', {
        exact: true
    }).waitFor();
    await page.screenshot({
        path: dir + '/memory-mobile-web.png',
        fullPage: true
    });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.getByText('遗忘这条记忆', {
        exact: true
    }).click();
    await page.getByRole('button', {
        name: '确认遗忘这条记忆',
        exact: true
    }).click();
    await page.getByText('还没有已确认记忆。待审阅的内容不会在这里显示。', {
        exact: true
    }).waitFor();
    assert.equal((await request('memories')).length, 0);
    assert.equal((await request('memories/' + memories[0].id + '/history')).length, 0);
    const invocations = await request('models/invocations');
    assert.ok(invocations.length >= 3);
    assert.ok(invocations.every(i => i.phase === 'local'));
    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');
    fs.writeFileSync('docs/implementation/p1-browser-results.json', JSON.stringify({
        status: 'passed',
        provider: 'real local Ollama',
        model: cfg.ollama_model,
        checks: ['native Ollama discovery', 'model profile save', 'write-only credential redaction', 'real conversation', 'pending proposal not recalled', 'source inspection', 'review approval', 'versioned correction', 'real corrected answer', 'live SSE update from another client', '390px no horizontal overflow', 'forget current and historical memory', 'no browser runtime errors'],
        synthetic_data: true,
        cloud_requests: 0,
        screenshots: fs.readdirSync(dir)
    }, null, 2) + '\n');
    await browser.close();
    console.log('P1 real Ollama browser acceptance passed');
})().catch(error => {
    console.error(error);
    process.exit(1)
});
