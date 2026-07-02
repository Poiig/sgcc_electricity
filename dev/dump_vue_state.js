// =============================================================================
// 95598 Vue state 调试提取脚本
// =============================================================================
// 用途：在 95598 网站账户余额页(userAcc)等页面，从浏览器 Console 提取 Vue 组件
//       的真实数据字段，用于核对 data_fetcher / vue_state.py 抽取的字段名是否正确。
//
// 用法：
//   1. 登录 95598 → 进入账户余额页 (userAcc?partNo=P02021704)
//   2. 切换到目标户号（如住宅 / 电动车）
//   3. F12 → Console → 粘贴本文件全部内容 → 回车
//   4. 控制台打印 JSON，同时复制到剪贴板，粘贴到记事本保存为 .txt 给开发者
//
// 说明：
//   - Vue 生产模式禁用了 devtools，本脚本通过 __vue__ 直接读 $data 绕过
//   - 安全序列化：跳过循环引用(_renderProxy 等)、Vue 内部属性($/_ 前缀)、
//     函数、DOM 节点，限深 5 层防爆栈
//   - 只收含余额/户号/电量相关字段的组件，过滤噪音
// =============================================================================
(function () {
  // 安全序列化：遇到循环引用 / 函数 / DOM 节点跳过
  var seen = new WeakSet();
  function safe(obj, depth) {
    depth = depth || 0;
    if (depth > 5) return '[depth-limit]';
    if (obj === null || typeof obj !== 'object') return obj;
    if (typeof (obj && obj.tagName) === 'string') return '[dom]';
    if (seen.has(obj)) return '[circular]';
    seen.add(obj);
    if (Array.isArray(obj)) return obj.slice(0, 50).map(function (v) { return safe(v, depth + 1); });
    var out = {};
    Object.keys(obj).forEach(function (k) {
      // 跳过 Vue 内部属性($ / _ / __ 前缀) —— 循环引用来源
      if (k.charAt(0) === '_' || k.charAt(0) === '$') return;
      var v = obj[k];
      if (typeof v === 'function') return;
      try { out[k] = safe(v, depth + 1); } catch (e) { out[k] = '[err]'; }
    });
    return out;
  }

  var root = document.querySelector('#app');
  root = root && root.__vue__;
  if (!root) { console.log('❌ 未找到 #app 的 Vue 实例'); return; }

  var out = [];
  function walk(c, depth) {
    depth = depth || 0;
    if (depth > 8 || !c) return;
    var d = c.$data || {};
    var ks = Object.keys(d);
    // 只收含余额 / 户号 / 电量相关字段的组件
    if (ks.some(function (k) { return /consNo|amt|bal|money|owe|余|elecItem|YuE|totalPq|prepay/i.test(k); })) {
      out.push(safe(d));
    }
    (c.$children || []).forEach(function (ch) { walk(ch, depth + 1); });
  }
  walk(root);

  var result = JSON.stringify(out, null, 2);
  console.log(result);
  try {
    copy(result);
    console.log('✅ 已复制到剪贴板，粘贴到记事本保存为 vue_state.txt');
  } catch (e) {
    console.log('（剪贴板复制不可用，请手动复制上方控制台输出）');
  }
})();
