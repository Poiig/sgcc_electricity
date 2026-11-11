// =============================================================================
// 95598 交费记录列表专项提取（payLists 挂在组件实例上，不在 $data）
// =============================================================================
// 页面：https://95598.cn/osgweb/paymentRecord（与登录同域，勿用 www）
//
// 已验证字段（2026-11）：
//   页级：begin / ending / pageNo / recordNum / count / callpay / payLists
//   单条：payDate / ymd / ym / rcvAmt / payMode / payModeName
//         typeCode / typeName / chanCls / chanName / remark
//         consNo / consName / elecAddr / penalty / withholdStatus
//         meterList / repAmtList / repDedList
//
// 用法：交费记录页已刷出卡片 → Console 整段粘贴 → 回车
// =============================================================================
(function () {
  var root = document.querySelector('#app');
  root = root && root.__vue__;
  if (!root) return JSON.stringify({ error: 'no vue' });

  var hit = null;
  function walk(c, depth) {
    if (!c || depth > 10 || hit) return;
    var d = c.$data || {};
    var ks = Object.keys(d);
    if (ks.indexOf('recordNum') >= 0 || ks.indexOf('begin') >= 0) {
      hit = {
        begin: c.begin,
        ending: c.ending,
        pageNo: c.pageNo,
        recordNum: c.recordNum,
        count: c.count,
        callpay: c.callpay,
        error: c.error,
        consNo_dst: c.electric && c.electric.consNo_dst,
        payLists: c.payLists || null,
        payList: c.payList || null,
        instanceKeys: Object.keys(c).filter(function (k) {
          return /pay|list|count|rcv|amt/i.test(k) && k.charAt(0) !== '_' && k.charAt(0) !== '$';
        })
      };
      return;
    }
    (c.$children || []).forEach(function (ch) { walk(ch, depth + 1); });
  }
  walk(root, 0);

  var result = JSON.stringify(hit, null, 2);
  window.__payment_pay_lists__ = result;
  var box = document.getElementById('__payment_dump_box__');
  if (!box) {
    box = document.createElement('textarea');
    box.id = '__payment_dump_box__';
    box.style.cssText = 'position:fixed;left:0;bottom:0;width:100%;height:260px;z-index:2147483647;font:12px/1.4 monospace;background:#111;color:#0f0;';
    document.body.appendChild(box);
  }
  box.value = result;
  return result;
})();
