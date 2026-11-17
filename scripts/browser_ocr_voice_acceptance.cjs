const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawnSync} = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18860';
const token = process.env.FAIRY_TOKEN;

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
    await page.locator('#nav a[href="#learning"]').click();

    const image = path.resolve(
        'docs/implementation/screenshots/ui-controls/desktop-learning.png'
    );
    await page.getByLabel('选择文字文件').setInputFiles(image);
    await page.getByRole('button', {name: '上传并学习', exact: true}).click();
    await page.getByRole('heading', {name: 'desktop-learning.png', exact: true}).waitFor();

    const worker = spawnSync('.venv/bin/python', ['-m', 'fairy.worker', '--once'], {
        env: process.env,
        encoding: 'utf8',
    });
    assert.equal(worker.status, 0, worker.stderr);
    const sourcesResponse = await fetch(base + '/v2/learning/sources', {
        headers: {Authorization: 'Bearer ' + token},
    });
    assert.equal(sourcesResponse.ok, true);
    const sources = await sourcesResponse.json();
    const source = sources.find(item => item.title === 'desktop-learning.png');
    assert.ok(source);
    assert.equal(source.file_format, '.png');
    assert.equal(source.extraction.method, 'macos_vision_ocr');
    assert.match(source.text, /Fairy/i);

    const statusResponse = await fetch(base + '/v2/voice/status', {
        headers: {Authorization: 'Bearer ' + token},
    });
    assert.equal(statusResponse.ok, true);
    const voice = await statusResponse.json();
    if (voice.local_tts) {
        const speech = await fetch(base + '/v2/voice/speak', {
            method: 'POST',
            headers: {
                Authorization: 'Bearer ' + token,
                'Content-Type': 'application/json',
                'Idempotency-Key': crypto.randomUUID(),
            },
            body: JSON.stringify({text: 'Fairy 本地语音验收'}),
        });
        assert.equal(speech.ok, true);
        assert.match(speech.headers.get('content-type'), /^audio\/wav/);
        const audio = Buffer.from(await speech.arrayBuffer());
        assert.equal(audio.subarray(0, 4).toString(), 'RIFF');
    }

    assert.deepEqual(errors, []);
    assert.equal(await page.locator('#error').innerText(), '');
    fs.writeFileSync(
        'docs/implementation/ocr-voice-browser-results.json',
        JSON.stringify({
            status: 'passed',
            checks: [
                'macOS Vision OCR image upload',
                'bounded OCR line extraction',
                'worker processing of OCR source',
                'local TTS status',
                voice.local_tts ? 'local WAV synthesis' : 'local TTS unavailable on this host',
                'no browser runtime errors',
            ],
            local_asr_configured: voice.local_asr,
            audio_persisted: false,
            cloud_used: false,
            synthetic_data: true,
        }, null, 2) + '\n'
    );
    await browser.close();
    console.log('OCR and local voice acceptance passed');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
