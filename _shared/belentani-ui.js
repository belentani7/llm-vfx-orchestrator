/* belentani-ui.js — Bundle compartido del ecosistema (ampliación 2026-11-10) */
(function () {
  'use strict';
  // Año dinámico en footers
  document.querySelectorAll('[data-year]').forEach(function (el) {
    el.textContent = new Date().getFullYear();
  });
  // Marcar nav activa según pathname
  var path = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-links a').forEach(function (a) {
    var href = a.getAttribute('href');
    if (href === path) { a.setAttribute('aria-current', 'page'); a.style.color = 'var(--hero-color-a)'; }
  });
  // Revelado suave de tarjetas de recursos
  var cards = document.querySelectorAll('.res-card');
  if ('IntersectionObserver' in window && cards.length) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.style.opacity = 1; e.target.style.transform = 'none'; io.unobserve(e.target); }
      });
    }, { threshold: 0.1 });
    cards.forEach(function (c) {
      c.style.opacity = 0; c.style.transform = 'translateY(12px)';
      c.style.transition = 'opacity .5s ease, transform .5s ease';
      io.observe(c);
    });
  }
})();
