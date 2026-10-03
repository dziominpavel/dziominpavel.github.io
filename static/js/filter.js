// Фильтр главной: единое правило для ВСЕХ карточек (.card — и скачиваемые,
// и web). Каждая карточка несёт data-platforms («android windows» / «web»);
// карточка видна, если выбран «Все» или сегмент входит в её data-platforms.
//
// Анимация при переключении: появляются только бывшие hidden карточки, и их
// задержка считается от ВИДИМОГО порядка (а не от nth-child позиции в общем
// списке, как было раньше): сегмент Web выезжает за 0+45 мс, а не через
// позиции 8–9 (315/360 мс). STEP должен совпадать со стаггером в style.css.
(function () {
  var STEP = 45;
  var bs = document.querySelectorAll('.filter');
  var cs = document.querySelectorAll('.grid .card');
  var e = document.getElementById('empty-state');
  bs.forEach(function (b) {
    b.onclick = function () {
      bs.forEach(function (x) { x.classList.remove('is-active'); });
      b.classList.add('is-active');
      var f = b.dataset.filter, n = 0, shown = [], visible = [];
      cs.forEach(function (c) {
        var ok = f === 'all' ||
          (c.dataset.platforms || '').split(' ').indexOf(f) >= 0;
        if (ok && c.hidden) shown.push(c); // карточка появляется (hidden → видна)
        c.hidden = !ok;
        if (ok) { n++; visible.push(c); }
      });
      // Задержка = позиция в видимом порядке: волна идёт по сетке слева направо,
      // каждая появившаяся карточка ждёт только предыдущих ВИДИМЫЕ соседей.
      shown.forEach(function (c) {
        c.style.animationDelay = (visible.indexOf(c) * STEP) + 'ms';
      });
      if (e) e.hidden = n > 0;
    };
  });
})();
