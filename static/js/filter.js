// Фильтр главной: Все / Android / Windows / Web.
// В одной сетке .grid лежат оба типа карточек: .card (скачиваемые) и
// .web-card (веб-приложения, идут после скачиваемых). Web-карточки видны
// в сегментах «Все» и «Web» и скрыты под Android/Windows.
(function () {
  var bs = document.querySelectorAll('.filter');
  var ps = document.querySelectorAll('.grid .card');
  var ws = document.querySelectorAll('.grid .web-card');
  var e = document.getElementById('empty-state');
  bs.forEach(function (b) {
    b.onclick = function () {
      bs.forEach(function (x) { x.classList.remove('is-active'); });
      b.classList.add('is-active');
      var f = b.dataset.filter, n = 0;
      ps.forEach(function (c) {
        var ok = f !== 'web' &&
          (f === 'all' || (c.dataset.platforms || '').split(' ').indexOf(f) >= 0);
        c.hidden = !ok;
        if (ok) n++;
      });
      ws.forEach(function (c) {
        var ok = f === 'all' || f === 'web';
        c.hidden = !ok;
        if (ok) n++;
      });
      if (e) e.hidden = n > 0;
    };
  });
})();

// Входной стаггер (card-in + nth-child задержки) — только при первой
// загрузке. После него снимаем анимацию, чтобы переключение фильтров
// показывало карточки сразу и синхронно, без задержки web-карточек.
setTimeout(function () {
  document.documentElement.classList.add('no-anim');
}, 800);
