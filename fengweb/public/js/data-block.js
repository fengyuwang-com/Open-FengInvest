/* ============================================================
   FengInvest 宪法册二 · 五态数据容器组件
   用法：
     <div class="data-block" data-url="/api/xxx"
          data-render="myRenderFn" data-empty="暂无数据">初始占位</div>
   FengData.fetchAll() 扫描页面上所有 .data-block[data-url]：
     loading → 请求中；ok → 调 window[data-render](data, el)；
     empty → 显示 data-empty 文案；error → 非2xx/{error} 显示错误；
     stale → 响应带 _stale:true 时加黄条。
   ============================================================ */
(function () {
  'use strict';

  function setState(el, state) { el.setAttribute('data-state', state); }

  function ensureBanners(el) {
    var T = (window.FengI18n && window.FengI18n.t) || function (k, fb) { return fb; };
    if (!el.querySelector('.db-stale-banner')) {
      var b = document.createElement('div');
      b.className = 'db-stale-banner';
      b.textContent = T('common.stale', '数据已过期 —— 正在尝试后台刷新');
      el.insertBefore(b, el.firstChild);
    }
    if (!el.querySelector('.db-error')) {
      var e = document.createElement('div');
      e.className = 'db-error';
      el.insertBefore(e, el.firstChild);
    }
    if (!el.querySelector('.db-empty')) {
      var m = document.createElement('div');
      m.className = 'db-empty';
      // i18n：data-empty-key 提供键，data-empty 中文为源语言兜底
      m.textContent = T(el.getAttribute('data-empty-key') || 'common.noData', el.getAttribute('data-empty') || '暂无数据');
      el.insertBefore(m, el.firstChild);
    }
  }

  async function fetchOne(el) {
    setState(el, 'loading');
    ensureBanners(el);
    var errEl = el.querySelector('.db-error');
    var emptyEl = el.querySelector('.db-empty');
    var staleEl = el.querySelector('.db-stale-banner');
    errEl.style.display = 'none';
    emptyEl.style.display = 'none';
    staleEl.style.display = 'none';
    var body = el.querySelector('.db-body') || (() => {
      var d = document.createElement('div'); d.className = 'db-body'; el.appendChild(d); return d;
    })();
    body.style.display = '';

    try {
      var res = await fetch(el.getAttribute('data-url'), { headers: { 'Accept': 'application/json' } });
      var data = null;
      try { data = await res.json(); } catch (e) { /* non-JSON */ }
      if (!res.ok) {
        body.style.display = 'none';
        errEl.textContent = (data && (data.error || data.detail)) || (T('common.reqFailed', '请求失败') + ' (' + res.status + ')');
        errEl.style.display = 'block';
        setState(el, 'error');
        return;
      }
      if (data && data.error) { // 约定：Python 工具 JSON 内含 error 键 = 上游失败
        body.style.display = 'none';
        errEl.textContent = data.detail || data.error;
        errEl.style.display = 'block';
        setState(el, 'error');
        return;
      }
      if (data === null || data === undefined ||
          (Array.isArray(data) && data.length === 0) ||
          (typeof data === 'object' && !Array.isArray(data) &&
           Object.keys(data).length === 0)) {
        body.style.display = 'none';
        emptyEl.style.display = 'block';
        setState(el, 'empty');
        return;
      }
      if (data._stale) staleEl.style.display = 'block';
      var fn = el.getAttribute('data-render');
      if (fn && typeof window[fn] === 'function') window[fn](data, body);
      else if (fn) { body.textContent = T('common.renderMissing', '渲染函数未定义: ') + fn; }
      setState(el, 'ok');
    } catch (e) {
      body.style.display = 'none';
      errEl.textContent = T('common.netError2', '网络错误: ') + e.message;
      errEl.style.display = 'block';
      setState(el, 'error');
    }
  }

  window.FengData = {
    fetchAll: function (root) {
      (root || document).querySelectorAll('.data-block[data-url]').forEach(fetchOne);
    },
    fetchOne: fetchOne,
  };

  document.addEventListener('DOMContentLoaded', function () { window.FengData.fetchAll(); });
})();
