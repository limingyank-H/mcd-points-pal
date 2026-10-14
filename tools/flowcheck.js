/**
 * UI 流程自检（可选开发工具，不参与 Skill 运行）
 *
 * 用无头 Chrome 把 examples/order-flow.html 的 6 步点击路径真的走一遍，
 * 逐步截图到 .flowcheck/，并在终端打印每一步读到的账目数字，
 * 用来保证「文档里写的路径」和「页面实际行为」一致。
 *
 * 依赖 puppeteer-core（非项目依赖，需自行安装）：
 *   npm i puppeteer-core
 *   NODE_PATH=<你的 node_modules> node tools/flowcheck.js
 */
const puppeteer = require('puppeteer-core');
const path = require('path');

const FILE = 'file://' + path.resolve(__dirname, '../examples/order-flow.html');
const OUT = path.resolve(__dirname, '../.flowcheck');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--allow-file-access-from-files', '--hide-scrollbars'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 430, height: 900, deviceScaleFactor: 2 });

  const shots = [];
  const step = async (name, note) => {
    await new Promise(r => setTimeout(r, 700));
    const p = `${OUT}/${name}.png`;
    await page.screenshot({ path: p });
    shots.push({ name, note });
    console.log(`✓ ${name}  ${note}`);
  };

  await page.goto(FILE, { waitUntil: 'networkidle2' });
  await step('01-home', '首页 · 人气热卖（找顶部积分横幅）');

  // 0. 先点一份主餐：鸡肉汉堡/卷 → 麦辣鸡腿汉堡三件套 → 选规格 → 加入购物车
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('#rail .ritem')].find(b => b.dataset.key === 'c2');
    b.click();
  });
  await new Promise(r => setTimeout(r, 300));
  await page.evaluate(() => document.querySelector('.spec[data-code="9900005456"]').click());
  await new Promise(r => setTimeout(r, 400));
  await page.evaluate(() => document.getElementById('spAdd').click());
  await step('02-meal-added', '麦辣鸡腿汉堡三件套 ¥33.50 加入购物车');

  // 1. 点左侧栏「积分兑换」（rail 第 2 项）
  const railOk = await page.evaluate(() => {
    const items = [...document.querySelectorAll('#rail .ritem')];
    const t = items.find(b => (b.dataset.key === 'pts'));
    if (t) { t.click(); return true; }
    return false;
  });
  console.log('  rail[积分兑换] 找到 =', railOk);
  await step('03-points-list', '积分券列表（9 张）');

  // 2. 点 16.9元2份麦辣鸡翅 (id 17078) 的 +
  const addOk = await page.evaluate(() => {
    const b = document.querySelector('.addbtn[data-pt="17078"]');
    if (b) { b.click(); return true; }
    return false;
  });
  console.log('  券 17078 加入购物车 =', addOk);
  await step('04-added', '加入购物车后 · 底部购物条');

  const barText = await page.evaluate(() => document.getElementById('ct2').textContent);
  console.log('  底部提示 =', barText);

  // 3. 点底部购物条空白处 → 购物车面板
  await page.evaluate(() => document.getElementById('cartbar').click());
  await step('05-cart', '购物车面板 · 这单还能用积分换');

  // 4. 点「去结算」
  await page.evaluate(() => document.getElementById('checkout').click());
  await step('06-checkout', '确认订单 · 四行账');

  const bill = await page.evaluate(() =>
    [...document.querySelectorAll('#prows .brow')].map(r => r.innerText.replace(/\n/g, ' ')));
  console.log('  账目 =', JSON.stringify(bill, null, 0));
  const paySum = await page.evaluate(() => document.getElementById('paySum').textContent);
  console.log('  实付 =', paySum);

  // 5. 提交订单
  await page.evaluate(() => document.getElementById('submitOrder').click());
  await new Promise(r => setTimeout(r, 1600));
  await page.screenshot({ path: `${OUT}/07-success.png` });
  console.log('✓ 06-success  金币雨 + 积分到账 + 下一次目标');

  const succ = await page.evaluate(() => ({
    earn: document.getElementById('earnNum').innerText,
    bal: document.getElementById('balNow').innerText,
    goal: document.getElementById('balGoal').innerText,
    code: document.getElementById('pickCode').innerText,
  }));
  console.log('  到账 =', JSON.stringify(succ, null, 2));

  await browser.close();
  console.log('\n截图目录:', OUT);
})().catch(e => { console.error('FAIL', e); process.exit(1); });
