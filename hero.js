/**
 * hero.js — Motor WebGL cinematográfico para LLM VFX Orchestrator.
 *
 * Características:
 * - Shader GLSL ES 1.00 propio: transporte volumétrico de luz anamórfica + bokeh espectral.
 * - Geometría de 1 triángulo fullscreen (3 vértices, cero costuras diagonales).
 * - Presupuesto GPU 60 fps: DPR limitado a 1.5, bucle FBM de 2 octavas sin ramificaciones pesadas.
 * - Degradación elegante en 3 niveles: WebGL -> Canvas 2D -> CSS puro.
 * - Respeta prefers-reduced-motion: renderiza 1 fotograma estático sin bucle rAF.
 * - Pausa real (cancelAnimationFrame) en pestaña oculta (visibilitychange) y fuera de viewport (IntersectionObserver).
 */
(function (global) {
  "use strict";

  var VERT_SRC = [
    "attribute vec2 a_pos;",
    "varying vec2 v_uv;",
    "void main() {",
    "  v_uv = a_pos * 0.5 + 0.5;",
    "  gl_Position = vec4(a_pos, 0.0, 1.0);",
    "}"
  ].join("\n");

  var FRAG_SRC = [
    "precision mediump float;",
    "varying vec2 v_uv;",
    "uniform vec2 u_res;",
    "uniform float u_time;",
    "uniform vec2 u_mouse;",
    "uniform vec3 u_colA;",
    "uniform vec3 u_colB;",
    "uniform vec3 u_colC;",
    "uniform float u_intensity;",
    "",
    "float hash21(vec2 p) {",
    "  p = fract(p * vec2(123.34, 456.21));",
    "  p += dot(p, p + 45.32);",
    "  return fract(p.x * p.y);",
    "}",
    "",
    "float noise(vec2 p) {",
    "  vec2 i = floor(p);",
    "  vec2 f = fract(p);",
    "  vec2 u = f * f * (3.0 - 2.0 * f);",
    "  float a = hash21(i);",
    "  float b = hash21(i + vec2(1.0, 0.0));",
    "  float c = hash21(i + vec2(0.0, 1.0));",
    "  float d = hash21(i + vec2(1.0, 1.0));",
    "  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);",
    "}",
    "",
    "float fbm(vec2 p) {",
    "  float v = 0.55 * noise(p);",
    "  p = mat2(0.8, -0.6, 0.6, 0.8) * p * 2.02;",
    "  v += 0.30 * noise(p);",
    "  return v;",
    "}",
    "",
    "void main() {",
    "  vec2 uv = v_uv;",
    "  float aspect = u_res.x / max(u_res.y, 1.0);",
    "  vec2 p = (uv - 0.5) * vec2(aspect, 1.0);",
    "  vec2 mp = (u_mouse - 0.5) * vec2(aspect, 1.0);",
    "  float t = u_time * 0.22;",
    "",
    "  vec2 flow = vec2(fbm(p * 1.6 + vec2(t, -t * 0.6)), fbm(p * 1.6 - vec2(t * 0.5, t)));",
    "  float plume = fbm(p * 2.1 + flow * 0.85 - mp * 0.22);",
    "",
    "  float streakY = p.y - mp.y * 0.28 + sin(p.x * 2.4 + t * 1.5) * 0.035;",
    "  float anamorphic = exp(-abs(streakY) * 14.0) * (0.45 + 0.55 * plume);",
    "  float core = exp(-dot(p - mp * 0.35, p - mp * 0.35) * 3.2);",
    "  float rim = smoothstep(0.18, 0.82, plume) * exp(-length(p * vec2(0.65, 1.15)) * 1.25);",
    "",
    "  vec3 base = vec3(0.020, 0.012, 0.039);",
    "  vec3 col = base;",
    "  col += u_colA * (rim * 0.42 + anamorphic * 0.55);",
    "  col += u_colB * (core * 0.34 + anamorphic * 0.28);",
    "  col += u_colC * (pow(plume, 3.0) * 0.24);",
    "",
    "  float vig = smoothstep(1.35, 0.22, length(p * vec2(0.78, 1.08)));",
    "  col *= mix(0.35, 1.0, vig) * u_intensity;",
    "  col = col / (1.0 + col);",
    "  gl_FragColor = vec4(col, 1.0);",
    "}"
  ].join("\n");

  function hexToRgb01(hex, fallback) {
    if (!hex || typeof hex !== "string") return fallback;
    var clean = hex.trim().replace("#", "");
    if (clean.length === 3) {
      clean = clean[0] + clean[0] + clean[1] + clean[1] + clean[2] + clean[2];
    }
    if (clean.length !== 6) return fallback;
    var num = parseInt(clean, 16);
    if (isNaN(num)) return fallback;
    return [
      ((num >> 16) & 255) / 255,
      ((num >> 8) & 255) / 255,
      (num & 255) / 255
    ];
  }

  function compileShader(gl, type, source) {
    var shader = gl.createShader(type);
    if (!shader) return null;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  function drawCanvas2DFallback(canvas, colors, mouseX, mouseY) {
    var ctx = null;
    try {
      ctx = canvas.getContext("2d");
    } catch (_e) {
      ctx = null;
    }
    if (!ctx) return false;
    var w = Math.max(1, canvas.width);
    var h = Math.max(1, canvas.height);
    ctx.fillStyle = "#05030a";
    ctx.fillRect(0, 0, w, h);

    var cx = w * mouseX;
    var cy = h * mouseY;
    var gradA = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(w, h) * 0.62);
    gradA.addColorStop(0, "rgba(" + Math.round(colors.a[0] * 255) + "," + Math.round(colors.a[1] * 255) + "," + Math.round(colors.a[2] * 255) + ",0.28)");
    gradA.addColorStop(0.55, "rgba(" + Math.round(colors.b[0] * 255) + "," + Math.round(colors.b[1] * 255) + "," + Math.round(colors.b[2] * 255) + ",0.12)");
    gradA.addColorStop(1, "rgba(5,3,10,0)");
    ctx.fillStyle = gradA;
    ctx.fillRect(0, 0, w, h);

    var streak = ctx.createLinearGradient(0, cy - h * 0.08, 0, cy + h * 0.08);
    streak.addColorStop(0, "rgba(77,232,224,0)");
    streak.addColorStop(0.5, "rgba(" + Math.round(colors.a[0] * 255) + "," + Math.round(colors.a[1] * 255) + "," + Math.round(colors.a[2] * 255) + ",0.22)");
    streak.addColorStop(1, "rgba(77,232,224,0)");
    ctx.fillStyle = streak;
    ctx.fillRect(0, cy - h * 0.08, w, h * 0.16);
    return true;
  }

  function applyCssFallback(canvas) {
    canvas.setAttribute("data-shader-mode", "css");
    canvas.style.background =
      "radial-gradient(circle at 60% 42%, rgba(77, 232, 224, 0.22), rgba(212, 175, 55, 0.10) 42%, #05030a 78%)";
  }

  function initHeroShader(target, opts) {
    var options = opts || {};
    var canvas =
      typeof target === "string" ? document.getElementById(target) : target;
    if (!canvas || typeof canvas.getContext !== "function") {
      return {
        mode: "none",
        isRunning: function () { return false; },
        pause: function () {},
        resume: function () {},
        destroy: function () {}
      };
    }

    var colors = {
      a: hexToRgb01(options.colorA || "#4de8e0", [0.302, 0.91, 0.878]),
      b: hexToRgb01(options.colorB || "#d4af37", [0.831, 0.686, 0.216]),
      c: hexToRgb01(options.colorC || "#ff073a", [1.0, 0.027, 0.227])
    };
    var intensity = typeof options.intensity === "number" ? options.intensity : 0.92;
    var maxDpr = typeof options.maxDpr === "number" ? options.maxDpr : 1.5;

    var reducedMotionQuery =
      global.matchMedia ? global.matchMedia("(prefers-reduced-motion: reduce)") : null;
    var prefersReduced = Boolean(reducedMotionQuery && reducedMotionQuery.matches);
    var userPaused = Boolean(options.paused);
    var inViewport = true;
    var tabVisible = typeof document !== "undefined" ? !document.hidden : true;
    var destroyed = false;
    var rafId = 0;
    var mouse = { x: 0.56, y: 0.44, tx: 0.56, ty: 0.44 };

    function syncSize() {
      var dpr = Math.min(global.devicePixelRatio || 1, maxDpr);
      var rect = canvas.getBoundingClientRect();
      var w = Math.max(1, Math.round((rect.width || canvas.clientWidth || 640) * dpr));
      var h = Math.max(1, Math.round((rect.height || canvas.clientHeight || 360) * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
    }

    syncSize();

    var gl = null;
    try {
      gl =
        canvas.getContext("webgl", {
          alpha: false,
          antialias: false,
          depth: false,
          stencil: false,
          powerPreference: "low-power",
          preserveDrawingBuffer: false
        }) || canvas.getContext("experimental-webgl");
    } catch (_err) {
      gl = null;
    }

    var mode = "webgl";
    var program = null;
    var buffer = null;
    var locs = null;

    if (gl) {
      var vs = compileShader(gl, gl.VERTEX_SHADER, VERT_SRC);
      var fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAG_SRC);
      if (vs && fs) {
        program = gl.createProgram();
        gl.attachShader(program, vs);
        gl.attachShader(program, fs);
        gl.linkProgram(program);
        gl.deleteShader(vs);
        gl.deleteShader(fs);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
          gl.deleteProgram(program);
          program = null;
        }
      }
      if (program) {
        buffer = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(
          gl.ARRAY_BUFFER,
          new Float32Array([-1, -1, 3, -1, -1, 3]),
          gl.STATIC_DRAW
        );
        var aPos = gl.getAttribLocation(program, "a_pos");
        gl.enableVertexAttribArray(aPos);
        gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
        locs = {
          res: gl.getUniformLocation(program, "u_res"),
          time: gl.getUniformLocation(program, "u_time"),
          mouse: gl.getUniformLocation(program, "u_mouse"),
          colA: gl.getUniformLocation(program, "u_colA"),
          colB: gl.getUniformLocation(program, "u_colB"),
          colC: gl.getUniformLocation(program, "u_colC"),
          intensity: gl.getUniformLocation(program, "u_intensity")
        };
        canvas.setAttribute("data-shader-mode", "webgl");
      } else {
        gl = null;
      }
    }

    if (!gl) {
      if (drawCanvas2DFallback(canvas, colors, mouse.x, mouse.y)) {
        mode = "canvas2d";
        canvas.setAttribute("data-shader-mode", "canvas2d");
      } else {
        mode = "css";
        applyCssFallback(canvas);
      }
    }

    var startTime = (global.performance && global.performance.now) ? global.performance.now() : Date.now();

    function renderFrame(nowMs) {
      if (destroyed) return;
      syncSize();
      if (mode === "webgl" && gl && program && locs) {
        mouse.x += (mouse.tx - mouse.x) * 0.06;
        mouse.y += (mouse.ty - mouse.y) * 0.06;
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.useProgram(program);
        gl.uniform2f(locs.res, canvas.width, canvas.height);
        gl.uniform1f(locs.time, (nowMs - startTime) * 0.001);
        gl.uniform2f(locs.mouse, mouse.x, mouse.y);
        gl.uniform3f(locs.colA, colors.a[0], colors.a[1], colors.a[2]);
        gl.uniform3f(locs.colB, colors.b[0], colors.b[1], colors.b[2]);
        gl.uniform3f(locs.colC, colors.c[0], colors.c[1], colors.c[2]);
        gl.uniform1f(locs.intensity, intensity);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      } else if (mode === "canvas2d") {
        drawCanvas2DFallback(canvas, colors, mouse.tx, mouse.ty);
      }
    }

    function shouldAnimate() {
      return !destroyed && mode === "webgl" && !prefersReduced && !userPaused && tabVisible && inViewport;
    }

    function stopLoop() {
      if (rafId) {
        global.cancelAnimationFrame(rafId);
        rafId = 0;
      }
    }

    function tick(now) {
      rafId = 0;
      if (!shouldAnimate()) return;
      renderFrame(now);
      rafId = global.requestAnimationFrame(tick);
    }

    function syncLoop() {
      if (shouldAnimate()) {
        if (!rafId) {
          rafId = global.requestAnimationFrame(tick);
        }
      } else {
        stopLoop();
      }
    }

    function onPointerMove(e) {
      var rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      mouse.tx = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
      mouse.ty = Math.min(1, Math.max(0, 1 - (e.clientY - rect.top) / rect.height));
      if (!shouldAnimate() && mode !== "css") {
        renderFrame(startTime + 2400);
      }
    }

    function onResize() {
      renderFrame((global.performance && global.performance.now) ? global.performance.now() : Date.now());
    }

    function onVisibilityChange() {
      tabVisible = !document.hidden;
      syncLoop();
    }

    function onReducedMotionChange(e) {
      prefersReduced = Boolean(e.matches);
      if (prefersReduced) {
        stopLoop();
        renderFrame(startTime + 2400);
      } else {
        syncLoop();
      }
    }

    function onContextLost(e) {
      e.preventDefault();
      stopLoop();
      applyCssFallback(canvas);
    }

    var observer = null;
    if ("IntersectionObserver" in global) {
      observer = new global.IntersectionObserver(
        function (entries) {
          if (entries[0]) {
            inViewport = entries[0].isIntersecting;
            syncLoop();
          }
        },
        { threshold: 0.02 }
      );
      observer.observe(canvas);
    }

    global.addEventListener("pointermove", onPointerMove, { passive: true });
    global.addEventListener("resize", onResize, { passive: true });
    document.addEventListener("visibilitychange", onVisibilityChange);
    canvas.addEventListener("webglcontextlost", onContextLost, false);
    if (reducedMotionQuery) {
      if (typeof reducedMotionQuery.addEventListener === "function") {
        reducedMotionQuery.addEventListener("change", onReducedMotionChange);
      } else if (typeof reducedMotionQuery.addListener === "function") {
        reducedMotionQuery.addListener(onReducedMotionChange);
      }
    }

    renderFrame(startTime + 2400);
    syncLoop();

    return {
      mode: mode,
      isRunning: function () {
        return rafId !== 0;
      },
      pause: function () {
        userPaused = true;
        stopLoop();
      },
      resume: function () {
        userPaused = false;
        syncLoop();
      },
      setColors: function (nextColors) {
        if (nextColors.colorA) colors.a = hexToRgb01(nextColors.colorA, colors.a);
        if (nextColors.colorB) colors.b = hexToRgb01(nextColors.colorB, colors.b);
        if (nextColors.colorC) colors.c = hexToRgb01(nextColors.colorC, colors.c);
        if (!shouldAnimate()) {
          renderFrame(startTime + 2400);
        }
      },
      destroy: function () {
        destroyed = true;
        stopLoop();
        global.removeEventListener("pointermove", onPointerMove);
        global.removeEventListener("resize", onResize);
        document.removeEventListener("visibilitychange", onVisibilityChange);
        canvas.removeEventListener("webglcontextlost", onContextLost);
        if (reducedMotionQuery) {
          if (typeof reducedMotionQuery.removeEventListener === "function") {
            reducedMotionQuery.removeEventListener("change", onReducedMotionChange);
          }
        }
        if (observer) observer.disconnect();
        if (gl && program) {
          if (buffer) gl.deleteBuffer(buffer);
          gl.deleteProgram(program);
        }
      }
    };
  }

  global.initHeroShader = initHeroShader;
})(typeof window !== "undefined" ? window : globalThis);
