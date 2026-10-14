/**
 * 重生成 README 首页的四张截图（可选开发工具，不参与 Skill 运行）
 *
 * 用无头 Chrome 打开 examples/order-flow.html，按固定视口（430×932 @2x = 860×1864）
 * 把四个关键状态截图到 assets/。视口与文件名和线上 README 一致，替换后版式不变。
 *
 * 依赖 puppeteer-core（非项目依赖，需自行安装）：
 *   npm i puppeteer-core
 *   NODE_PATH=<你的 node_modules> node tools/shots.js
 */
const puppeteer = require('puppeteer-core');
const path = require('path');

const FILE = 'file://' + path.resolve(__dirname, '../examples/order-flow.html');
const OUT = path.resolve(__dirname, '../assets');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const wait = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--allow-file-access-from-files', '--hide-scrollbars'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 430, height: 932, deviceScaleFactor: 2 });

  const shot = async (name, note) => {
    await wait(800);
    await page.screenshot({ path: `${OUT}/${name}.png` });
    console.log(`✓ ${name}.png  ${note}`);
  };

  await page.goto(FILE, { waitUntil: 'networkidle2' });

  // 1. 先加一份主餐，让账目有正常点单金额
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#rail .ritem')].find(b => b.dataset.key === 'c2');
    if (b) b.click();
  });
  await wait(300);
  await page.evaluate(() => document.querySelector('.spec[data-code="9900005456"]').click());
  await wait(400);
  await page.evaluate(() => document.getElementById('spAdd').click());
  await wait(400);

  // 2. 进「积分兑换」分类 —— 券作为分类长在菜单里
  await page.evaluate(() => {
    const t = [...document.querySelectorAll('#rail .ritem')].find(b => b.dataset.key === 'pts');
    if (t) t.click();
  });
  await shot('01-coupons-in-menu', '积分券作为分类长在菜单里');

  // 3. 加一张券 → 打开购物车面板（这单还能用积分换）
  await page.evaluate(() => {
    const b = document.querySelector('.addbtn[data-pt="17078"]');
    if (b) b.click();
  });
  await wait(400);
  await page.evaluate(() => document.getElementById('cartbar').click());
  await shot('02-cart', '购物车 · 这单还能用积分换');

  // 4. 去结算 → 确认订单四行账
  await page.evaluate(() => document.getElementById('checkout').click());
  await shot('03-checkout', '确认订单 · 四行账');

  // 5. 提交订单 → 金币雨 + 积分到账
  await page.evaluate(() => document.getElementById('submitOrder').click());
  await wait(1500);
  await page.screenshot({ path: `${OUT}/04-points-rain.png` });
  console.log('✓ 04-points-rain.png  金币雨 + 积分到账 + 下一次目标');

  const sanity = await page.evaluate(() => ({
    store: (document.querySelector('.sn') || {}).innerText || '',
    dist: (document.querySelector('.dist') || {}).innerText || '',
  }));
  console.log('  页面门店 =', JSON.stringify(sanity));
  console.log('  门店名不应出现真实店名（应为「示例门店」）');

  await browser.close();
  console.log('\n输出目录:', OUT);
})().catch(e => { console.error('FAIL', e); process.exit(1); });
