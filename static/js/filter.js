// Фильтр главной: единое правило для ВСЕХ карточек (.card — и скачиваемые,
// и web). Каждая карточка несёт data-platforms («android windows» / «web»);
// карточка видна, если выбран «Все» или сегмент входит в её data-platforms.
// Первый клик выключает входную анимацию (html.no-anim): дальше переключения
// показывают карточки мгновенно и одинаково для всех.
(function () {
  var bs = document.querySelectorAll('.filter');
  var cs = document.querySelectorAll('.grid .card');
  var e = document.getElementById('empty-state');
  bs.forEach(function (b) {
    b.onclick = function () {
      document.documentElement.classList.add('no-anim');
      bs.forEach(function (x) { x.classList.remove('is-active'); });
      b.classList.add('is-active');
      var f = b.dataset.filter, n = 0;
      cs.forEach(function (c) {
        var ok = f === 'all' ||
          (c.dataset.platforms || '').split(' ').indexOf(f) >= 0;
        c.hidden = !ok;
        if (ok) n++;
      });
      if (e) e.hidden = n > 0;
    };
  });
})();
