const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawnSync} = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const base = process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18844';
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
    const material = await request('learning/materials', 'POST', {
        title: '猫科护理',
        text: '猫科动物通常需要蛋白质、清洁饮水和安全的活动空间。',
    });
    const worker = spawnSync('.venv/bin/python', ['-m', 'fairy.worker', '--once'], {
        env: process.env,
        encoding: 'utf8',
    });
    assert.equal(worker.status, 0, worker.stderr);

    const search = await request(
        'learning/search?q=' + encodeURIComponent('小猫需要什么')
    );
    assert.equal(search.retrieval_mode, 'ollama_semantic_rerank_with_local_character_fallback');
    assert.equal(search.semantic_available, true);
    assert.ok(search.results.some(item => item.course_id === material.course.id));
    const match = search.results.find(item => item.course_id === material.course.id);
    assert.ok(match.semantic_relevance >= 0.68);

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
    await page.locator('#nav a[href="#learning"]').click();
    await page.getByLabel('检索关键词').fill('小猫需要什么');
    await page.getByRole('button', {name: '检索资料', exact: true}).click();
    await page.getByText(
        '猫科动物通常需要蛋白质、清洁饮水和安全的活动空间。',
        {exact: true}
    ).first().waitFor();
    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');

    fs.writeFileSync(
        'docs/implementation/semantic-retrieval-browser-results.json',
        JSON.stringify({
            status: 'passed',
            provider: 'local Ollama',
            model: 'bge-m3:latest',
            query: '小猫需要什么',
            semantic_relevance: match.semantic_relevance,
            checks: [
                'local neural embedding',
                'hybrid lexical rerank',
                'synonym-style query match',
                'learning page retrieval',
                'no browser runtime errors',
            ],
            cloud_used: false,
            synthetic_data: true,
        }, null, 2) + '\n'
    );
    await browser.close();
    console.log('Semantic retrieval acceptance passed');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
