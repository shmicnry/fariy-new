const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.FAIRY_TEST_URL || 'http://127.0.0.1:18860';
const token = process.env.FAIRY_TOKEN;
const output = process.env.FAIRY_UI_AUDIT_DIR || '/private/tmp/fairy-ui-audit';
const routes = [
    'overview',
    'mind',
    'world',
    'memories',
    'models',
    'learning',
    'assessments',
    'evolution',
    'skills',
    'mac',
    'flows',
    'pet',
    'cards',
    'approvals',
    'chat',
];

async function inspect(page, route, viewport) {
    await page.evaluate(nextRoute => {
        location.hash = nextRoute;
    }, route);
    await page.waitForTimeout(250);
    const result = await page.evaluate(() => {
        const visible = element => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none'
                && style.visibility !== 'hidden'
                && rect.width > 0
                && rect.height > 0;
        };
        const accessibleName = element => {
            const explicit = element.getAttribute('aria-label');
            if (explicit) return explicit.trim();
            const label = element.labels?.[0]?.innerText?.trim();
            if (label) return label;
            const placeholder = element.getAttribute('placeholder');
            if (placeholder) return placeholder.trim();
            return element.textContent?.trim() || element.getAttribute('title')?.trim() || '';
        };
        const controls = [...document.querySelectorAll('main button, main input, main select, main textarea')]
            .filter(visible);
        const invalid = element => element.matches(':invalid');
        const info = element => {
            const target = element.matches('input[type="checkbox"], input[type="radio"]')
                ? element.closest('label') || element.labels?.[0] || element
                : element;
            const rect = target.getBoundingClientRect();
            const style = getComputedStyle(element);
            return {
                tag: element.tagName.toLowerCase(),
                type: element.getAttribute('type'),
                name: accessibleName(element),
                width: Math.round(rect.width * 10) / 10,
                height: Math.round(rect.height * 10) / 10,
                fontSize: style.fontSize,
                borderColor: style.borderColor,
                background: style.backgroundColor,
                color: style.color,
                disabled: Boolean(element.disabled),
                invalid: invalid(element),
                clipped: element.scrollWidth > element.clientWidth + 1,
            };
        };
        return {
            route: location.hash.slice(1),
            heading: document.querySelector('header h1')?.innerText || '',
            controlCount: controls.length,
            unnamed: controls.filter(control => !accessibleName(control)).map(info),
            tooSmall: controls.filter(control => {
                const target = control.matches('input[type="checkbox"], input[type="radio"]')
                    ? control.closest('label') || control.labels?.[0] || control
                    : control;
                const rect = target.getBoundingClientRect();
                const minimum = innerWidth <= 780 ? 44 : 28;
                return rect.width < minimum - 0.5 || rect.height < minimum - 0.5;
            }).map(info),
            clipped: controls.filter(control => control.scrollWidth > control.clientWidth + 1).map(info),
            details: controls.map(info),
            activeCurrent: [...document.querySelectorAll('nav a.active')]
                .every(link => link.getAttribute('aria-current') === 'page'),
            horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
            runtimeError: document.querySelector('#error')?.innerText || '',
        };
    });
    let dialog = null;
    if (route === 'mind' && await page.locator('.star').count()) {
        await page.locator('.star').first().click();
        const detail = page.locator('#detailDialog');
        await detail.waitFor({state: 'visible'});
        await page.waitForTimeout(220);
        dialog = await detail.evaluate(element => {
            const surface = element.querySelector('.dialog-surface');
            const rect = surface.getBoundingClientRect();
            return {
                open: element.open,
                title: element.querySelector('#dialogTitle')?.textContent,
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                backdrop: getComputedStyle(element, '::backdrop').backgroundColor,
            };
        });
        await page.screenshot({
            path: path.join(output, `${viewport}-dialog.png`),
            fullPage: false,
        });
        await detail.getByRole('button', {name: '关闭详情'}).click();
    }
    await page.screenshot({
        path: path.join(output, `${viewport}-${route}.png`),
        fullPage: true,
    });
    return {...result, dialog};
}

(async () => {
    fs.mkdirSync(output, {recursive: true});
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
    const requestHeaders = {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'Idempotency-Key': 'ui-audit-material-v1',
    };
    const api = page.context().request;
    const materialResponse = await api.post(`${base}/v2/learning/materials`, {
        headers: requestHeaders,
        data: {
            title: 'UI 审计材料',
            text: 'Fairy 会把审阅后的记忆与原文来源分开显示。',
        },
    });
    if (!materialResponse.ok()) {
        throw new Error(`failed to seed UI audit material: ${materialResponse.status()} ${await materialResponse.text()}`);
    }
    const material = await materialResponse.json();
    const memoryResponse = await api.post(`${base}/v2/memories`, {
        headers: {...requestHeaders, 'Idempotency-Key': 'ui-audit-memory-v1'},
        data: {
            text: 'Fairy 会把审阅后的记忆与原文来源分开显示。',
            source_ids: [material.material.id],
        },
    });
    if (!memoryResponse.ok()) {
        throw new Error(`failed to seed UI audit memory: ${memoryResponse.status()} ${await memoryResponse.text()}`);
    }

    const results = [];
    for (const route of routes) {
        results.push(await inspect(page, route, 'desktop'));
    }
    await page.setViewportSize({width: 390, height: 844});
    for (const route of routes) {
        results.push(await inspect(page, route, 'iphone'));
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.emulateMedia({colorScheme: 'dark'});
    for (const route of ['models', 'learning', 'evolution', 'chat']) {
        results.push(await inspect(page, route, 'dark'));
    }

    const unnamed = results.reduce((total, item) => total + item.unnamed.length, 0);
    const tooSmall = results.reduce((total, item) => total + item.tooSmall.length, 0);
    const clipped = results.reduce((total, item) => total + item.clipped.length, 0);
    const overflows = results.filter(item => item.horizontalOverflow);
    const runtimeErrors = results.filter(item => item.runtimeError);
    const dialogs = results.filter(item => item.dialog?.open);
    const report = {
        status: errors.length === 0
            && unnamed === 0
            && tooSmall === 0
            && clipped === 0
            && overflows.length === 0
            && runtimeErrors.length === 0
            && dialogs.length === 2
            && results.every(item => item.activeCurrent)
            ? 'passed'
            : 'failed',
        routes: results,
        browserErrors: errors,
    };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({
        output,
        pages: results.length,
        browserErrors: errors,
        unnamed,
        tooSmall,
        clipped,
        dialogs: dialogs.length,
        overflows: overflows.map(item => `${item.route}:${item.heading}`),
        runtimeErrors: runtimeErrors.map(item => ({
            route: item.route,
            error: item.runtimeError,
        })),
    }, null, 2));
    if (report.status !== 'passed') process.exitCode = 1;
    await browser.close();
})().catch(error => {
    console.error(error);
    process.exit(1);
});
