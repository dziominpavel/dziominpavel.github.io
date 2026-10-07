// Фильтр главной: единое правило для ВСЕХ карточек (.card — и скачиваемые,
// и web). Каждая карточка несёт data-platforms («android windows» / «web»);
// карточка видна, если выбран «Все» или сегмент входит в её data-platforms.
//
// Анимация при переключении — та же волна, что при первой загрузке: ВСЕ
// видимые карточки перезапускают card-in с задержкой от позиции в сетке
// (шаг STEP = 45 мс, как у nth-child в style.css). Перезапуск обязателен:
// без него волна от загрузки или прошлого клика продолжала бы идти
// параллельно с новой (карточки, оставшиеся видимыми, её не теряли), и
// выезд шёл не по порядку. Inline-задержка пересчитывается для каждой
// видимой карточки каждый раз — устаревших не бывает.
(function () {
  var STEP = 45;
  var bs = document.querySelectorAll('.filter');
  var cs = document.querySelectorAll('.grid .card');
  var e = document.getElementById('empty-state');
  bs.forEach(function (b) {
    b.onclick = function () {
      bs.forEach(function (x) { x.classList.remove('is-active'); });
      b.classList.add('is-active');
      var f = b.dataset.filter, n = 0, visible = [];
      cs.forEach(function (c) {
        var ok = f === 'all' ||
          (c.dataset.platforms || '').split(' ').indexOf(f) >= 0;
        c.hidden = !ok;
        c.style.animation = 'none';      // гасим текущую/незавершённую волну
        c.style.animationDelay = '';     // и прошлую inline-задержку
        if (ok) { n++; visible.push(c); }
      });
      // Один форс-рефлоу: без него браузер не увидит снятие card-in между
      // двумя записями стиля и анимация не перезапустится.
      void document.body.offsetHeight;
      // Волна слева направо по (отфильтрованной) сетке: задержка = позиция.
      visible.forEach(function (c, i) {
        c.style.animation = '';
        c.style.animationDelay = (i * STEP) + 'ms';
      });
      if (e) e.hidden = n > 0;
    };
  });
})();
