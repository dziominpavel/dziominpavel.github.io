// Тема витрины: только dark/light (по умолчанию dark), без системного режима
// и без перезагрузки страницы. Выбор хранится в localStorage (устаревшее
// значение 'system' и любое мусорное значение мигрируют в 'dark').
(function () {
  var KEY = 'theme';
  var COLOR = { dark: '#0a0b10', light: '#f4f6fa' };

  function read() {
    var value = null;
    try { value = localStorage.getItem(KEY); } catch (e) { /* приватный режим */ }
    return value === 'light' ? 'light' : 'dark';
  }

  function write(theme) {
    try { localStorage.setItem(KEY, theme); } catch (e) { /* приватный режим */ }
  }

  function syncMeta(theme) {
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', COLOR[theme]);
    document.documentElement.style.colorScheme = theme;
  }

  function syncLabel(button, theme) {
    var word = theme === 'dark' ? 'светлую' : 'тёмную';
    var text = 'Переключить на ' + word + ' тему';
    button.setAttribute('aria-label', text);
    button.setAttribute('title', text);
  }

  var theme = read();
  write(theme); // миграция: system/мусор -> dark
  document.documentElement.dataset.theme = theme;
  syncMeta(theme);

  document.addEventListener('DOMContentLoaded', function () {
    var button = document.getElementById('theme-toggle');
    if (!button) return;
    syncLabel(button, theme);
    button.addEventListener('click', function () {
      theme = theme === 'dark' ? 'light' : 'dark';
      write(theme);
      document.documentElement.dataset.theme = theme;
      syncMeta(theme);
      syncLabel(button, theme);
    });
  });
})();
