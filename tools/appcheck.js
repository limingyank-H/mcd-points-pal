const puppeteer = require('puppeteer-core');
const path = require('path');

const BASE = process.env.PAL_URL || 'http://127.0.0.1:8787';
const OUT = path.resolve(__dirname, '../.flowcheck');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-proxy-server', '--hide-scrollbars', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 430, height: 900, deviceScaleFactor: 2 });

  const fail = [];
  page.on('console', m => { if (m.type() === 'error') fail.push('console: ' + m.text()); });
  page.on('pageerror', e => fail.push('pageerror: ' + e.message));
  page.on('requestfailed', r => fail.push('requestfailed: ' + r.url() + ' ' + (r.failure() || {}).errorText));

  const shot = async (name) => {
    await new Promise(r => setTimeout(r, 600));
    await page.screenshot({ path: `${OUT}/${name}.png` });
    console.log('  ✓ ' + name);
  };
  const waitFor = async (fn, label, timeout = 45000) => {
    await page.waitForFunction(fn, { timeout, polling: 400 })
      .catch(() => { throw new Error('等待超时：' + label) });
    console.log('  · ' + label);
  };

  console.log('打开 ' + BASE);
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });

  // ---- 1. 首屏：状态条 + 门店搜索面板 ----
  await waitFor(() => document.getElementById('statusText') &&
    document.getElementById('statusText').textContent.indexOf('正在连接') === -1, '状态条就绪');
  const status = await page.$eval('#statusText', e => e.textContent);
  console.log('    状态条 =', status);
  await shot('r01-boot');

  const storeSheetOpen = await page.$eval('#storeSheet', e => e.classList.contains('on'));
  console.log('    门店面板自动打开 =', storeSheetOpen);

  // ---- 2. 搜索真实门店并选第一家 ----
  if (storeSheetOpen) {
    await waitFor(() => document.getElementById('btnFind'), '门店面板渲染');
    await page.click('#btnFind');
    await waitFor(() => document.querySelector('.scard'), '搜到门店');
    const stores = await page.$$eval('.scard .sn2', els => els.map(e => e.innerText.trim()));
    console.log('    门店 =', stores.slice(0, 4).join(' | '));
    await shot('r02-stores');
    await page.click('.scard');
  }

  // ---- 3. 目录加载完成 ----
  await waitFor(() => document.querySelectorAll('#rail .ritem').length > 3, '菜单与券加载完成');
  const header = await page.evaluate(() => ({
    store: document.getElementById('storeName').textContent,
    meta: document.getElementById('storeMeta').textContent,
    balance: document.getElementById('ptBalance').textContent,
    rail: document.querySelectorAll('#rail .ritem').length,
    cards: document.querySelectorAll('#list .pcard').length,
  }));
  console.log('    门店 =', header.store, '|', header.meta, '|', header.balance);
  console.log('    侧栏', header.rail, '项 · 首屏商品卡', header.cards, '张');
  await shot('r03-menu');

  // ---- 4. 积分兑换分类 ----
  await page.evaluate(() => document.querySelector('#rail .ritem[data-key="pts"]').click());
  await waitFor(() => document.querySelectorAll('#list .pcard.pt').length > 0, '券列表渲染');
  const coupons = await page.$$eval('#list .pcard.pt .pname', els => els.map(e => e.innerText.trim()));
  console.log('    券 =', coupons.length, '张，前 3：', coupons.slice(0, 3).join(' | '));
  await shot('r04-coupons');

  // ---- 5. 加一张券 ----
  const couponAdd = await page.evaluate(() => {
    const b = document.querySelector('#list .addbtn[data-pt]');
    if (!b) return null;
    const card = b.closest('.pcard');
    const name = card.querySelector('.pname').innerText.trim();
    b.click();
    return name;
  });
  console.log('    加入券 =', couponAdd);
  await shot('r05-coupon-added');

  // ---- 6. 加一份主餐（回到第一个分类）----
  await page.evaluate(() => document.querySelector('#rail .ritem[data-key="c0"]').click());
  await waitFor(() => document.querySelector('#list .pcard'), '餐品列表');
  const mealAdd = await page.evaluate(() => {
    const b = document.querySelector('#list .addbtn[data-code]');
    if (!b) return null;
    const card = b.closest('.pcard');
    const name = card.querySelector('.pname').innerText.trim();
    b.click();
    return name;
  });
  console.log('    加入主餐 =', mealAdd);
  await waitFor(() => document.getElementById('cnt').textContent === '2', '购物车 2 件');
  await shot('r06-cartbar');

  // ---- 7. 购物车面板 ----
  await page.click('#cartbar');
  await waitFor(() => document.querySelector('#crows .crow'), '购物车明细');
  const recText = await page.evaluate(() => {
    const r = document.querySelector('#crows .rec');
    return r ? r.innerText.replace(/\n+/g, ' / ').slice(0, 160) : '(无推荐)';
  });
  console.log('    推荐区 =', recText);
  await shot('r07-cart');

  // ---- 8. 确认订单 ----
  await page.click('#checkout');
  await waitFor(() => document.querySelector('#prows .billbox'), '四行账');
  const bill = await page.$$eval('#prows .brow', els => els.map(e => e.innerText.replace(/\n/g, ' ')));
  console.log('    账目 =', JSON.stringify(bill));
  await shot('r08-checkout');

  // ---- 9. 官方核价 ----
  await page.click('#btnQuote');
  await waitFor(() => {
    const q = document.getElementById('quoteBox');
    return q && q.innerText.indexOf('正在向麦当劳') === -1 && q.innerText.length > 10;
  }, '官方核价返回', 60000);
  const quote = await page.$eval('#quoteBox', e => e.innerText.replace(/\n+/g, ' / ').slice(0, 220));
  console.log('    核价 =', quote);
  await shot('r09-quote');

  // ---- 10. 积分到账预览 ----
  await page.click('#submitOrder');
  await waitFor(() => document.getElementById('success').classList.contains('on'), '成功页');
  await new Promise(r => setTimeout(r, 1700));
  const succ = await page.evaluate(() => ({
    earn: document.getElementById('earnNum').innerText,
    bal: document.getElementById('balNow').innerText,
    goal: document.getElementById('balGoal').innerText,
    rows: document.querySelectorAll('#sdetail .drow').length,
  }));
  console.log('    到账预览 =', JSON.stringify(succ, null, 0));
  await shot('r10-success');

  await browser.close();

  if (fail.length){
    console.log('\n⚠️  页面报错 ' + fail.length + ' 条：');
    [...new Set(fail)].slice(0, 10).forEach(f => console.log('   - ' + f));
    process.exitCode = 1;
  } else {
    console.log('\n✅ 全流程无页面报错，截图在 ' + OUT);
  }
})().catch(e => { console.error('\n❌ ' + e.message); process.exit(1); });
