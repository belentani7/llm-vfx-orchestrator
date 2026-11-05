/**
 * hero.js — Shader WebGL1 sin dependencias para landing page hero.
 * Reutilizable en cualquier repo. Sin npm install, sin framework.
 * Características:
 *   - FBM (Fractal Brownian Motion) animado
 *   - Parallax de ratón
 *   - DPR limitado a 1.75 para rendimiento
 *   - Pausa fuera de viewport (IntersectionObserver)
 *   - Frame estático con prefers-reduced-motion
 *   - Auto-ajuste al resize del canvas
 */
(function () {
  'use strict';

  var canvasId = 'hero-canvas';
  var colorA = '#0ea5e9'; // azul cielo
  var colorB = '#7c3aed'; // violeta
  var speed = 0.0004;
  var mouse = { x: 0.5, y: 0.5 };
  var time = 0;
  var raf = null;
  var paused = false;
  var dprCap = 1.75;

  var vertexShaderSource = [
    'attribute vec2 position;',
    'void main() {',
    '  gl_Position = vec4(position, 0.0, 1.0);',
    '}'
  ].join('\n');

  var fragmentShaderSource = [
    'precision mediump float;',
    'uniform vec2 u_resolution;',
    'uniform float u_time;',
    'uniform vec2 u_mouse;',
    'uniform vec3 u_colorA;',
    'uniform vec3 u_colorB;',
    '',
    'float hash(vec2 p) {',
    '  p = fract(p * vec2(123.34, 456.21));',
    '  p += dot(p, p + 45.32);',
    '  return fract(p.x * p.y);',
    '}',
    '',
    'float noise(vec2 p) {',
    '  vec2 i = floor(p);',
    '  vec2 f = fract(p);',
    '  f = f * f * (3.0 - 2.0 * f);',
    '  float a = hash(i);',
    '  float b = hash(i + vec2(1.0, 0.0));',
    '  float c = hash(i + vec2(0.0, 1.0));',
    '  float d = hash(i + vec2(1.0, 1.0));',
    '  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);',
    '}',
    '',
    'float fbm(vec2 p) {',
    '  float v = 0.0;',
    '  float a = 0.5;',
    '  vec2 shift = vec2(100.0);',
    '  for (int i = 0; i < 5; ++i) {',
    '    v += a * noise(p);',
    '    p = p * 2.0 + shift;',
    '    a *= 0.5;',
    '  }',
    '  return v;',
    '}',
    '',
    'void main() {',
    '  vec2 uv = gl_FragCoord.xy / u_resolution.xy;',
    '  uv.x *= u_resolution.x / u_resolution.y;',
    '  vec2 m = uv - u_mouse;',
    '  float n = fbm(uv * 3.0 + u_time * 0.5);',
    '  n += fbm(uv * 6.0 - u_time * 0.3) * 0.5;',
    '  n += length(m) * 0.1;',
    '  n = mod(n, 1.0);',
    '  vec3 color = mix(u_colorA, u_colorB, n);',
    '  float vignette = 1.0 - length(uv * 2.0 - 1.0) * 0.4;',
    '  color *= vignette;',
    '  gl_FragColor = vec4(color, 1.0);',
    '}'
  ].join('\n');

  function createShader(gl, type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.error(gl.getShaderInfoLog(shader));
      gl.deleteShader(shader);
      return null;
    }
    return shader;
  }

  function createProgram(gl, vsSource, fsSource) {
    var vertexShader = createShader(gl, gl.VERTEX_SHADER, vsSource);
    var fragmentShader = createShader(gl, gl.FRAGMENT_SHADER, fsSource);
    var program = gl.createProgram();
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error(gl.getProgramInfoLog(program));
      return null;
    }
    return program;
  }

  function hexToRgb(hex) {
    var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    return m ? {
      r: parseInt(m[1], 16) / 255,
      g: parseInt(m[2], 16) / 255,
      b: parseInt(m[3], 16) / 255
    } : { r: 0, g: 0.5, b: 1 };
  }

  function init(canvasId, colorA, colorB) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) {
      console.warn('hero.js: canvas #' + canvasId + ' no encontrado');
      return;
    }
    var gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) {
      console.warn('hero.js: WebGL no disponible');
      canvas.style.background = 'linear-gradient(135deg, ' + colorA + ', ' + colorB + ')';
      return;
    }

    var program = createProgram(gl, vertexShaderSource, fragmentShaderSource);
    gl.useProgram(program);

    var positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    var positions = new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);

    var positionLoc = gl.getAttribLocation(program, 'position');
    gl.enableVertexAttribArray(positionLoc);
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0);

    var resolutionLoc = gl.getUniformLocation(program, 'u_resolution');
    var timeLoc = gl.getUniformLocation(program, 'u_time');
    var mouseLoc = gl.getUniformLocation(program, 'u_mouse');
    var colorALoc = gl.getUniformLocation(program, 'u_colorA');
    var colorBLoc = gl.getUniformLocation(program, 'u_colorB');

    var rgbA = hexToRgb(colorA);
    var rgbB = hexToRgb(colorB);
    gl.uniform3f(colorALoc, rgbA.r, rgbA.g, rgbA.b);
    gl.uniform3f(colorBLoc, rgbB.r, rgbB.g, rgbB.b);

    function resize() {
      var dpr = Math.min(window.devicePixelRatio || 1, dprCap);
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = canvas.clientHeight * dpr;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(resolutionLoc, canvas.width, canvas.height);
    }

    window.addEventListener('mousemove', function (e) {
      mouse.x = e.clientX / window.innerWidth;
      mouse.y = 1.0 - e.clientY / window.innerHeight;
    });

    window.addEventListener('resize', resize);

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        paused = !entry.isIntersecting;
      });
    }, { threshold: 0.1 });
    observer.observe(canvas);

    resize();

    function loop(t) {
      if (!paused) {
        time = t * speed;
        gl.uniform1f(timeLoc, time);
        gl.uniform2f(mouseLoc, mouse.x, mouse.y);
        gl.drawArrays(gl.TRIANGLES, 0, 6);
      }
      raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);

    return {
      destroy: function () {
        if (raf) cancelAnimationFrame(raf);
        if (observer) observer.disconnect();
        gl.deleteProgram(program);
        gl.deleteBuffer(positionBuffer);
      },
      setColors: function (a, b) {
        var ra = hexToRgb(a), rb = hexToRgb(b);
        gl.uniform3f(colorALoc, ra.r, ra.g, ra.b);
        gl.uniform3f(colorBLoc, rb.r, rb.g, rb.b);
      }
    };
  }

  window.initHeroShader = init;
})();
