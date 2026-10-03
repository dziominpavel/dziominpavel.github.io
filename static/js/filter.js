// Фильтр главной: все / Android / Windows / Веб.
// Скачиваемые карточки (.grid .card) фильтруются по data-platforms;
// секция «Веб-приложения» (.web-apps) скрывается целиком под платформенными
// фильтрами и видна под «Все» и «Веб». Счётчик сегмента «Все» включает
// web-карточки, поэтому пустое состояние считает видимое всегда.
(function () {
  var bs = document.querySelectorAll('.filter');
  var cs = document.querySelectorAll('.grid .card');
  var ws = document.querySelectorAll('.web-apps');
  var wc = document.querySelectorAll('.web-card').length;
  var e = document.getElementById('empty-state');
  bs.forEach(function (b) {
    b.onclick = function () {
      bs.forEach(function (x) { x.classList.remove('is-active'); });
      b.classList.add('is-active');
      var f = b.dataset.filter;
      var showWeb = f === 'all' || f === 'web';
      var n = 0;
      ws.forEach(function (s) { s.hidden = !showWeb; });
      cs.forEach(function (c) {
        var ok = f !== 'web' &&
          (f === 'all' || (c.dataset.platforms || '').split(' ').indexOf(f) >= 0);
        c.hidden = !ok;
        if (ok) n++;
      });
      if (showWeb) n += wc;
      if (e) e.hidden = n > 0;
    };
  });
})();
