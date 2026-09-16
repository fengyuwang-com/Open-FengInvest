/* 宪法册八 · i18n：[data-i18n] 键翻译，localStorage.feng_lang 切换（zh-CN 默认 / en）
 * 中文是源语言：首次翻译前把原文存进 data-i18n-orig，切回中文即时还原。
 * 支持：data-i18n="key"（textContent）、data-i18n-ph="key"（placeholder）、
 *       data-i18n-tt="key"（title/aria-label）。
 * 动态插入的带键节点由 MutationObserver 自动翻译（仅英文态）。
 * 内联脚本生成动态文案可用 window.FengI18n.t('key', '中文兜底')。 */
(function () {
  var DICT = {
    'nav.home': 'Home', 'nav.research': 'Research', 'nav.reports': 'Reports', 'nav.holdings': 'Holdings',
    'nav.portfolio': 'Portfolio', 'nav.alerts': 'Alerts', 'nav.watch': 'Watch',
    'nav.knowledge': 'Knowledge', 'nav.market': 'Market', 'nav.sector': 'Sectors',
    'nav.rollover': 'Rollover', 'nav.journal': 'Journal', 'nav.system': 'Architecture',
    'nav.workspace': 'Workspace', 'nav.spec': 'Spec Wallet', 'nav.discuss': 'Discussions',
    'nav.ledger': 'Discipline Ledger', 'nav.masters': 'Masters',
    'group.core': 'Core', 'group.ext': 'Extended',
  };
  var REMOTE = null;
  var CUR = 'zh-CN';
  function load(lang) {
    return fetch('/locales/' + (lang === 'en' ? 'en' : 'zh-CN') + '.json')
      .then(function (r) {
        // fail-loud（2026-09-13 有声失败审计 P3）：语言包拉不到时静默退回内置词表，
        // 用户切语言"没反应"必须留声
        if (!r.ok) { console.warn('[i18n] 语言包 ' + lang + ' 返回 HTTP ' + r.status + '，退回内置词表'); return null; }
        return r.json();
      })
      .then(function (j) { if (j) REMOTE = Object.assign(REMOTE || {}, j); })
      .catch(function (e) { console.warn('[i18n] 语言包 ' + lang + ' 加载失败，退回内置词表:', e); });
  }
  function t(key, fallback) {
    return (REMOTE && REMOTE[key]) || DICT[key] || fallback;
  }
  function setAttr(el, attr, key, lang) {
    var origKey = 'data-i18n-' + attr + '-orig';
    if (lang === 'en') {
      if (!el.getAttribute(origKey)) el.setAttribute(origKey, el.getAttribute(attr) || '');
      var v = t(key, el.getAttribute(origKey));
      if (v != null) el.setAttribute(attr, v);
    } else if (el.getAttribute(origKey) != null) {
      el.setAttribute(attr, el.getAttribute(origKey));
    }
  }
  function applyOne(el, lang) {
    var key = el.getAttribute('data-i18n');
    if (key) {
      if (lang === 'en') {
        if (!el.getAttribute('data-i18n-orig')) el.setAttribute('data-i18n-orig', el.textContent);
        el.textContent = t(key, el.getAttribute('data-i18n-orig'));
      } else if (el.getAttribute('data-i18n-orig')) {
        el.textContent = el.getAttribute('data-i18n-orig');
      }
    }
    var ph = el.getAttribute('data-i18n-ph');
    if (ph) setAttr(el, 'placeholder', ph, lang);
    var tt = el.getAttribute('data-i18n-tt');
    if (tt) { setAttr(el, 'title', tt, lang); setAttr(el, 'aria-label', tt, lang); }
  }
  // 表格卡片化标签：把 thead 表头文字同步到各 td 的 data-label（≤640px 卡片模式用）
  // 语言切换时 apply() 会整体重刷，动态插入的表由 MutationObserver 兜底。
  function relabelOne(tb) {
    var headThs = tb.querySelectorAll('thead th');
    var thRow = headThs.length ? null : (tb.rows[0] && tb.rows[0].querySelector('th') ? tb.rows[0] : null);
    var src = headThs.length ? headThs : (thRow ? thRow.querySelectorAll('th') : []);
    if (!src.length) return;
    var labels = Array.prototype.map.call(src, function (th) { return th.textContent.trim(); });
    Array.prototype.forEach.call(tb.rows, function (tr) {
      if (tr.querySelector('th')) return;
      Array.prototype.forEach.call(tr.cells, function (td, i) {
        if (labels[i]) td.setAttribute('data-label', labels[i]);
      });
    });
    tb.setAttribute('data-labeled', '1');
  }
  function relabelTables() {
    document.querySelectorAll('table.holdings-table, table.data-table, table.mkt-table').forEach(relabelOne);
  }

  function apply(lang) {
    CUR = lang === 'en' ? 'en' : 'zh-CN';
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.querySelectorAll('[data-i18n],[data-i18n-ph],[data-i18n-tt]').forEach(function (el) {
      applyOne(el, CUR);
    });
    relabelTables();
  }
  window.FengI18n = {
    apply: apply,
    t: t,
    toggle: function () {
      var cur = localStorage.getItem('feng_lang') === 'en' ? 'zh-CN' : 'en';
      localStorage.setItem('feng_lang', cur);
      load(cur).then(function () { apply(cur); });
      var btn = document.getElementById('langBtn');
      if (btn) btn.textContent = cur === 'en' ? '中' : 'EN';
    },
    init: function () {
      if (typeof MutationObserver !== 'undefined' && !window.__tableLabelMO) {
        window.__tableLabelMO = new MutationObserver(function () {
          document.querySelectorAll('table.holdings-table:not([data-labeled]), table.data-table:not([data-labeled]), table.mkt-table:not([data-labeled])').forEach(relabelOne);
        });
        window.__tableLabelMO.observe(document.documentElement, { childList: true, subtree: true });
      }
      var lang = localStorage.getItem('feng_lang') || 'zh-CN';
      CUR = lang === 'en' ? 'en' : 'zh-CN';
      if (lang === 'en') load('en').then(function () { apply('en'); }); else apply('zh-CN');
      var btn = document.getElementById('langBtn');
      if (btn) {
        btn.textContent = (localStorage.getItem('feng_lang') || 'zh-CN') === 'en' ? '中' : 'EN';
        btn.addEventListener('click', window.FengI18n.toggle);
      }
    },
  };
  document.addEventListener('DOMContentLoaded', function () {
    window.FengI18n.init();
    // 动态插入的带键节点也翻译（如表格行、弹窗内容）
    new MutationObserver(function (muts) {
      if (CUR !== 'en') return;
      muts.forEach(function (m) {
        m.addedNodes.forEach(function (n) {
          if (n.nodeType !== 1) return;
          if (n.getAttribute && (n.getAttribute('data-i18n') || n.getAttribute('data-i18n-ph') || n.getAttribute('data-i18n-tt'))) applyOne(n, 'en');
          if (n.querySelectorAll) n.querySelectorAll('[data-i18n],[data-i18n-ph],[data-i18n-tt]').forEach(function (el) { applyOne(el, 'en'); });
        });
      });
    }).observe(document.body, { childList: true, subtree: true });
  });
})();
