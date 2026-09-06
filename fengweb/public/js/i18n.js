/* 宪法册八 · i18n：[data-i18n] 键翻译，localStorage.feng_lang 切换（zh-CN 默认 / en） */
(function () {
  var DICT = {
    'nav.home': 'Home', 'nav.research': 'Research', 'nav.reports': 'Reports', 'nav.holdings': 'Holdings',
    'nav.portfolio': 'Portfolio', 'nav.alerts': 'Alerts', 'nav.watch': 'Watch',
    'nav.knowledge': 'Knowledge', 'nav.market': 'Market', 'nav.sector': 'Sectors',
    'nav.rollover': 'Rollover', 'nav.journal': 'Journal', 'nav.system': 'Architecture',
    'nav.workspace': 'Workspace', 'nav.spec': 'Spec Wallet', 'nav.discuss': 'Discussions',
  };
  var REMOTE = null;
  function load(lang) {
    return fetch('/locales/' + (lang === 'en' ? 'en' : 'zh-CN') + '.json')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { REMOTE = j; })
      .catch(function () { REMOTE = null; });
  }
  function t(key, fallback) {
    return (REMOTE && REMOTE[key]) || DICT[key] || fallback;
  }
  function apply(lang) {
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      if (lang === 'en') el.textContent = t(key, el.textContent); // 中文是源语言，不回译
    });
  }
  window.FengI18n = {
    apply: apply,
    toggle: function () {
      var cur = localStorage.getItem('feng_lang') === 'en' ? 'zh-CN' : 'en';
      localStorage.setItem('feng_lang', cur);
      load(cur).then(function () { apply(cur); });
      var btn = document.getElementById('langBtn');
      if (btn) btn.textContent = cur === 'en' ? '中' : 'EN';
    },
    init: function () {
      var lang = localStorage.getItem('feng_lang') || 'zh-CN';
      if (lang === 'en') load('en').then(function () { apply('en'); }); else apply('zh-CN');
      var btn = document.getElementById('langBtn');
      if (btn) {
        btn.textContent = (localStorage.getItem('feng_lang') || 'zh-CN') === 'en' ? '中' : 'EN';
        btn.addEventListener('click', window.FengI18n.toggle);
      }
    },
  };
  document.addEventListener('DOMContentLoaded', window.FengI18n.init);
})();
