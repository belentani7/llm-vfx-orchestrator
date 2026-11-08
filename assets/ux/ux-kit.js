/* ux-kit.js v1 — motor de mejora progresiva para el ecosistema belentani7.
   Requiere: nada. Aprovecha si están: GSAP + ScrollTrigger + SplitText,
   Lenis, lucide. Sin red → fallback a IntersectionObserver + scroll nativo.
   Respeta prefers-reduced-motion. Todos los bloques en try/catch: nunca rompe. */
(function () {
  'use strict';
  var w = window, d = document;
  var RM = w.matchMedia && w.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var FINE = w.matchMedia && w.matchMedia('(hover: hover) and (pointer: fine)').matches;

  function ready(fn) {
    if (d.readyState !== 'loading') fn();
    else d.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    var hasGSAP = typeof w.gsap !== 'undefined';
    var hasST = hasGSAP && typeof w.ScrollTrigger !== 'undefined';
    if (hasST && w.gsap.registerPlugin) w.gsap.registerPlugin(w.ScrollTrigger);

    /* 1 ─ Lenis smooth scroll (solo con movimiento permitido) */
    var lenis = null;
    try {
      if (!RM && typeof w.Lenis === 'function' && !d.documentElement.classList.contains('ux-no-smooth')) {
        lenis = new w.Lenis({ duration: 1.1 });
        if (hasST) {
          lenis.on('scroll', w.ScrollTrigger.update);
          w.gsap.ticker.add(function (t) { lenis.raf(t * 1000); });
          w.gsap.ticker.lagSmoothing(0);
        } else {
          (function raf(t) { lenis.raf(t); w.requestAnimationFrame(raf); })(0);
        }
        d.documentElement.classList.add('ux-smooth');
        d.addEventListener('click', function (e) {
          var a = e.target && e.target.closest && e.target.closest('a[href^="#"]');
          if (!a) return;
          var id = a.getAttribute('href');
          if (id.length > 1 && d.getElementById(id.slice(1))) {
            e.preventDefault();
            lenis.scrollTo(id, { offset: -84 });
            history.replaceState(null, '', id);
          }
        });
      }
    } catch (e) { lenis = null; }

    /* 2 ─ Revelado de secciones [data-ux-reveal] */
    try {
      var els = [].slice.call(d.querySelectorAll('[data-ux-reveal]'));
      if (els.length) {
        if (!RM && hasST) {
          els.forEach(function (el) {
            var dir = el.getAttribute('data-ux-reveal');
            var from = { opacity: 0, duration: .85, ease: 'power3.out',
              scrollTrigger: { trigger: el, start: 'top 88%', once: true },
              onComplete: function () { el.classList.add('ux-in'); } };
            if (dir === 'left')  from.x = -32; else if (dir === 'right') from.x = 32;
            else if (dir === 'zoom') { from.scale = .94; } else from.y = 28;
            w.gsap.from(el, from);
          });
        } else if ('IntersectionObserver' in w) {
          if (RM) {
            els.forEach(function (el) { el.classList.add('ux-in'); });
          } else {
            var io = new IntersectionObserver(function (entries) {
              entries.forEach(function (en) {
                if (en.isIntersecting) { en.target.classList.add('ux-in'); io.unobserve(en.target); }
              });
            }, { rootMargin: '0px 0px -8% 0px', threshold: .05 });
            els.forEach(function (el) { io.observe(el); });
          }
        } else {
          els.forEach(function (el) { el.classList.add('ux-in'); });
        }
      }
    } catch (e) {}

    /* 3 ─ Parallax suave [data-ux-parallax="0.2"] (GSAP only) */
    try {
      if (!RM && hasST) {
        [].slice.call(d.querySelectorAll('[data-ux-parallax]')).forEach(function (el) {
          var pct = parseFloat(el.getAttribute('data-ux-parallax')) || 20;
          w.gsap.to(el, {
            yPercent: -pct, ease: 'none',
            scrollTrigger: { trigger: el.parentElement || el, start: 'top bottom', end: 'bottom top', scrub: true }
          });
        });
      }
    } catch (e) {}

    /* 4 ─ Hero timeline con SplitText (solo landings marcadas) */
    try {
      var hero = d.querySelector('[data-ux-hero]');
      if (hero) {
        var title = hero.querySelector('[data-ux-hero-title]');
        var done = function () { hero.classList.add('ux-hero-in'); };
        if (!RM && hasGSAP && title && typeof w.SplitText !== 'undefined' && w.gsap.registerPlugin) {
          w.gsap.registerPlugin(w.SplitText);
          var split = w.SplitText.create(title, { type: 'lines,words', mask: 'lines' });
          var tl = w.gsap.timeline({ defaults: { ease: 'power3.out', duration: .8 }, onComplete: done });
          tl.from(split.words, { yPercent: 118, stagger: .04 }, .15)
            .from(hero.querySelectorAll('[data-ux-hero-badge]'), { y: -12, opacity: 0 }, '-=.65')
            .from(hero.querySelectorAll('[data-ux-hero-sub]'), { y: 22, opacity: 0 }, '-=.5')
            .from(hero.querySelectorAll('[data-ux-hero-cta] > *'), { y: 14, opacity: 0, stagger: .09 }, '-=.5')
            .from(hero.querySelectorAll('[data-ux-hero-meta] > *'), { y: 10, opacity: 0, stagger: .06 }, '-=.4');
        } else {
          done(); /* sin GSAP: CSS (.ux-hero-in) muestra todo con transición suave */
        }
      }
    } catch (e) {
      var h = d.querySelector('[data-ux-hero]');
      if (h) h.classList.add('ux-hero-in');
    }

    /* 5 ─ Contadores [data-ux-count="1234"] (+ [data-ux-count-suffix]) */
    try {
      [].slice.call(d.querySelectorAll('[data-ux-count]')).forEach(function (el) {
        var target = parseFloat(el.getAttribute('data-ux-count')) || 0;
        var suf = el.getAttribute('data-ux-count-suffix') || '';
        var dec = (String(el.getAttribute('data-ux-count')).split('.')[1] || '').length;
        if (RM || !hasGSAP) { el.textContent = target.toFixed(dec) + suf; return; }
        var obj = { v: 0 };
        var run = function () {
          w.gsap.to(obj, {
            v: target, duration: 1.6, ease: 'power2.out',
            scrollTrigger: { trigger: el, start: 'top 92%', once: true },
            onUpdate: function () { el.textContent = obj.v.toFixed(dec) + suf; }
          });
        };
        run();
      });
    } catch (e) {}

    /* 6 ─ Menú móvil accesible [data-ux-menu-btn] + [data-ux-menu] */
    try {
      var btn = d.querySelector('[data-ux-menu-btn]');
      var menu = d.querySelector('[data-ux-menu]');
      if (btn && menu) {
        var setMenu = function (open) {
          btn.setAttribute('aria-expanded', String(open));
          menu.classList.toggle('ux-open', open);
          menu.setAttribute('aria-hidden', String(!open));
          if (open) {
            var first = menu.querySelector('a, button');
            first && first.focus();
          }
        };
        btn.addEventListener('click', function () {
          setMenu(btn.getAttribute('aria-expanded') !== 'true');
        });
        d.addEventListener('keydown', function (e) {
          if (e.key === 'Escape' && btn.getAttribute('aria-expanded') === 'true') { setMenu(false); btn.focus(); }
        });
        menu.addEventListener('click', function (e) {
          if (e.target.closest && e.target.closest('a')) setMenu(false);
        });
      }
    } catch (e) {}

    /* 7 ─ Tema claro/oscuro [data-ux-theme-toggle] */
    try {
      [].slice.call(d.querySelectorAll('[data-ux-theme-toggle]')).forEach(function (btn) {
        var root = d.documentElement;
        var theme = root.getAttribute('data-theme') ||
          (w.matchMedia && w.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        var apply = function (t, persist) {
          root.setAttribute('data-theme', t);
          btn.setAttribute('aria-pressed', String(t === 'dark'));
          btn.setAttribute('aria-label', t === 'dark' ? 'Activar tema claro' : 'Activar tema oscuro');
          if (persist) { try { localStorage.setItem('ux-theme', t); } catch (e) {} }
        };
        apply(theme, false);
        btn.addEventListener('click', function () {
          apply(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark', true);
        });
      });
    } catch (e) {}

    /* 8 ─ Botones magnéticos [data-ux-magnet] (solo puntero fino) */
    try {
      if (FINE && !RM) {
        [].slice.call(d.querySelectorAll('[data-ux-magnet]')).forEach(function (el) {
          var strength = parseFloat(el.getAttribute('data-ux-magnet')) || 6;
          el.addEventListener('pointermove', function (ev) {
            var r = el.getBoundingClientRect();
            var x = (ev.clientX - r.left - r.width / 2) / (r.width / 2);
            var y = (ev.clientY - r.top - r.height / 2) / (r.height / 2);
            el.style.transform = 'translate(' + (x * strength) + 'px,' + (y * strength * .7) + 'px)';
          });
          el.addEventListener('pointerleave', function () { el.style.transform = ''; });
        });
      }
    } catch (e) {}

    /* 9 ─ Año automático [data-ux-year] */
    try {
      var y = String(new Date().getFullYear());
      [].slice.call(d.querySelectorAll('[data-ux-year]')).forEach(function (el) { el.textContent = y; });
    } catch (e) {}

    /* 10 ─ Iconos lucide si están cargados */
    try { if (w.lucide && w.lucide.createIcons) w.lucide.createIcons(); } catch (e) {}

    /* 11 ─ Barra de progreso de lectura [data-ux-progress] */
    try {
      var bar = d.querySelector('[data-ux-progress]');
      if (bar) {
        var upd = function () {
          var h = d.documentElement;
          var max = h.scrollHeight - h.clientHeight;
          bar.style.transform = 'scaleX(' + (max > 0 ? h.scrollTop / max : 0) + ')';
        };
        w.addEventListener('scroll', upd, { passive: true });
        upd();
      }
    } catch (e) {}
  });
})();
