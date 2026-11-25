import { useEffect, useRef, useState } from "react";

export interface HeroShaderProps {
  title?: string;
  subtitle?: string;
  colorA?: string;
  colorB?: string;
  colorC?: string;
  paused?: boolean;
  compact?: boolean;
  className?: string;
}

const VERT_SRC = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
  v_uv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}
`;

const FRAG_SRC = `
precision mediump float;
varying vec2 v_uv;
uniform vec2 u_res;
uniform float u_time;
uniform vec2 u_mouse;
uniform vec3 u_colA;
uniform vec3 u_colB;
uniform vec3 u_colC;

float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash21(i), hash21(i + vec2(1.0, 0.0)), u.x),
    mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), u.x),
    u.y
  );
}

float fbm(vec2 p) {
  float v = 0.55 * noise(p);
  p = mat2(0.8, -0.6, 0.6, 0.8) * p * 2.02;
  v += 0.30 * noise(p);
  return v;
}

void main() {
  float aspect = u_res.x / max(u_res.y, 1.0);
  vec2 p = (v_uv - 0.5) * vec2(aspect, 1.0);
  vec2 mp = (u_mouse - 0.5) * vec2(aspect, 1.0);
  float t = u_time * 0.24;

  vec2 flow = vec2(fbm(p * 1.7 + vec2(t, -t * 0.6)), fbm(p * 1.7 - vec2(t * 0.5, t)));
  float plume = fbm(p * 2.2 + flow * 0.85 - mp * 0.22);
  float streakY = p.y - mp.y * 0.25 + sin(p.x * 2.5 + t * 1.4) * 0.03;
  float anamorphic = exp(-abs(streakY) * 14.0) * (0.45 + 0.55 * plume);
  float core = exp(-dot(p - mp * 0.32, p - mp * 0.32) * 3.1);

  vec3 col = vec3(0.020, 0.012, 0.039);
  col += u_colA * (plume * 0.38 + anamorphic * 0.58);
  col += u_colB * (core * 0.36 + anamorphic * 0.26);
  col += u_colC * (pow(plume, 3.0) * 0.24);
  col = col / (1.0 + col);
  gl_FragColor = vec4(col, 1.0);
}
`;

function hexToRgb01(
  hex: string,
  fallback: [number, number, number],
): [number, number, number] {
  const clean = hex.trim().replace("#", "");
  const normalized =
    clean.length === 3
      ? `${clean[0]}${clean[0]}${clean[1]}${clean[1]}${clean[2]}${clean[2]}`
      : clean;
  if (normalized.length !== 6) return fallback;
  const parsed = Number.parseInt(normalized, 16);
  if (Number.isNaN(parsed)) return fallback;
  return [
    ((parsed >> 16) & 255) / 255,
    ((parsed >> 8) & 255) / 255,
    (parsed & 255) / 255,
  ];
}

function compileShader(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

export function deriveLightingPalette(lightingText: string): {
  colorA: string;
  colorB: string;
  colorC: string;
} {
  const lower = lightingText.toLowerCase();
  if (
    lower.includes("amber") ||
    lower.includes("tungsten") ||
    lower.includes("gold")
  ) {
    return { colorA: "#4de8e0", colorB: "#d4af37", colorC: "#ff5a36" };
  }
  if (
    lower.includes("sodium") ||
    lower.includes("red") ||
    lower.includes("crimson")
  ) {
    return { colorA: "#ff073a", colorB: "#d4af37", colorC: "#4de8e0" };
  }
  if (
    lower.includes("cyan") ||
    lower.includes("blue") ||
    lower.includes("steel")
  ) {
    return { colorA: "#4de8e0", colorB: "#5ea3ff", colorC: "#d4af37" };
  }
  return { colorA: "#4de8e0", colorB: "#d4af37", colorC: "#ff073a" };
}

export default function HeroShader({
  title,
  subtitle,
  colorA = "#4de8e0",
  colorB = "#d4af37",
  colorC = "#ff073a",
  paused: initialPaused = false,
  compact = false,
  className = "",
}: HeroShaderProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [userPaused, setUserPaused] = useState(initialPaused);
  const [renderMode, setRenderMode] = useState<"webgl" | "canvas2d" | "css">(
    "webgl",
  );

  useEffect(() => {
    setUserPaused(initialPaused);
  }, [initialPaused]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const rgbA = hexToRgb01(colorA, [0.302, 0.91, 0.878]);
    const rgbB = hexToRgb01(colorB, [0.831, 0.686, 0.216]);
    const rgbC = hexToRgb01(colorC, [1.0, 0.027, 0.227]);

    const mediaQuery =
      typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-reduced-motion: reduce)")
        : null;
    let prefersReduced = Boolean(mediaQuery?.matches);
    let tabVisible = !document.hidden;
    let inViewport = true;
    let rafId = 0;
    let disposed = false;
    const pointer = { x: 0.56, y: 0.45, tx: 0.56, ty: 0.45 };

    const syncSize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(1, Math.round((rect.width || 480) * dpr));
      const height = Math.max(1, Math.round((rect.height || 160) * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
    };

    syncSize();

    let gl: WebGLRenderingContext | null = null;
    try {
      gl =
        (canvas.getContext("webgl", {
          alpha: false,
          antialias: false,
          depth: false,
          stencil: false,
          powerPreference: "low-power",
        }) as WebGLRenderingContext | null) ??
        (canvas.getContext(
          "experimental-webgl",
        ) as WebGLRenderingContext | null);
    } catch {
      gl = null;
    }

    let program: WebGLProgram | null = null;
    let buffer: WebGLBuffer | null = null;

    if (gl) {
      const vs = compileShader(gl, gl.VERTEX_SHADER, VERT_SRC);
      const fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAG_SRC);
      if (vs && fs) {
        const candidate = gl.createProgram();
        if (candidate) {
          gl.attachShader(candidate, vs);
          gl.attachShader(candidate, fs);
          gl.linkProgram(candidate);
          if (gl.getProgramParameter(candidate, gl.LINK_STATUS)) {
            program = candidate;
          } else {
            gl.deleteProgram(candidate);
          }
        }
      }
      if (vs) gl.deleteShader(vs);
      if (fs) gl.deleteShader(fs);
    }

    let activeMode: "webgl" | "canvas2d" | "css" = "css";
    let ctx2d: CanvasRenderingContext2D | null = null;

    if (gl && program) {
      activeMode = "webgl";
      buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(
        gl.ARRAY_BUFFER,
        new Float32Array([-1, -1, 3, -1, -1, 3]),
        gl.STATIC_DRAW,
      );
      const aPos = gl.getAttribLocation(program, "a_pos");
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
    } else {
      try {
        ctx2d = canvas.getContext("2d");
      } catch {
        ctx2d = null;
      }
      activeMode = ctx2d ? "canvas2d" : "css";
    }

    setRenderMode(activeMode);

    const uRes = gl && program ? gl.getUniformLocation(program, "u_res") : null;
    const uTime =
      gl && program ? gl.getUniformLocation(program, "u_time") : null;
    const uMouse =
      gl && program ? gl.getUniformLocation(program, "u_mouse") : null;
    const uColA =
      gl && program ? gl.getUniformLocation(program, "u_colA") : null;
    const uColB =
      gl && program ? gl.getUniformLocation(program, "u_colB") : null;
    const uColC =
      gl && program ? gl.getUniformLocation(program, "u_colC") : null;

    const startTime = performance.now();

    const drawFrame = (nowMs: number) => {
      if (disposed) return;
      syncSize();
      if (activeMode === "webgl" && gl && program) {
        pointer.x += (pointer.tx - pointer.x) * 0.08;
        pointer.y += (pointer.ty - pointer.y) * 0.08;
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.useProgram(program);
        gl.uniform2f(uRes, canvas.width, canvas.height);
        gl.uniform1f(uTime, (nowMs - startTime) * 0.001);
        gl.uniform2f(uMouse, pointer.x, pointer.y);
        gl.uniform3f(uColA, rgbA[0], rgbA[1], rgbA[2]);
        gl.uniform3f(uColB, rgbB[0], rgbB[1], rgbB[2]);
        gl.uniform3f(uColC, rgbC[0], rgbC[1], rgbC[2]);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      } else if (activeMode === "canvas2d" && ctx2d) {
        const w = canvas.width;
        const h = canvas.height;
        ctx2d.fillStyle = "#05030a";
        ctx2d.fillRect(0, 0, w, h);
        const grad = ctx2d.createRadialGradient(
          w * pointer.tx,
          h * pointer.ty,
          0,
          w * pointer.tx,
          h * pointer.ty,
          Math.max(w, h) * 0.65,
        );
        grad.addColorStop(0, `${colorA}44`);
        grad.addColorStop(0.55, `${colorB}22`);
        grad.addColorStop(1, "#05030a00");
        ctx2d.fillStyle = grad;
        ctx2d.fillRect(0, 0, w, h);
      }
    };

    const shouldAnimate = () =>
      !disposed &&
      activeMode === "webgl" &&
      !prefersReduced &&
      !userPaused &&
      tabVisible &&
      inViewport;

    const stopLoop = () => {
      if (rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
      }
    };

    const loop = (now: number) => {
      rafId = 0;
      if (!shouldAnimate()) return;
      drawFrame(now);
      rafId = window.requestAnimationFrame(loop);
    };

    const syncLoop = () => {
      if (shouldAnimate()) {
        if (!rafId) rafId = window.requestAnimationFrame(loop);
      } else {
        stopLoop();
      }
    };

    const handleVisibility = () => {
      tabVisible = !document.hidden;
      syncLoop();
    };

    const handlePointer = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      pointer.tx = Math.min(
        1,
        Math.max(0, (event.clientX - rect.left) / rect.width),
      );
      pointer.ty = Math.min(
        1,
        Math.max(0, 1 - (event.clientY - rect.top) / rect.height),
      );
      if (!shouldAnimate() && activeMode !== "css") {
        drawFrame(startTime + 1800);
      }
    };

    const handleMotionChange = (event: MediaQueryListEvent) => {
      prefersReduced = event.matches;
      if (prefersReduced) {
        stopLoop();
        drawFrame(startTime + 1800);
      } else {
        syncLoop();
      }
    };

    let observer: IntersectionObserver | null = null;
    if (typeof IntersectionObserver !== "undefined") {
      observer = new IntersectionObserver(
        (entries) => {
          if (entries[0]) {
            inViewport = entries[0].isIntersecting;
            syncLoop();
          }
        },
        { threshold: 0.02 },
      );
      observer.observe(canvas);
    }

    document.addEventListener("visibilitychange", handleVisibility);
    canvas.addEventListener("pointermove", handlePointer, { passive: true });
    mediaQuery?.addEventListener?.("change", handleMotionChange);

    drawFrame(startTime + 1800);
    syncLoop();

    return () => {
      disposed = true;
      stopLoop();
      document.removeEventListener("visibilitychange", handleVisibility);
      canvas.removeEventListener("pointermove", handlePointer);
      mediaQuery?.removeEventListener?.("change", handleMotionChange);
      observer?.disconnect();
      if (gl && program) {
        if (buffer) gl.deleteBuffer(buffer);
        gl.deleteProgram(program);
      }
    };
  }, [colorA, colorB, colorC, userPaused]);

  return (
    <div
      className={`shader-stage ${compact ? "shader-stage--compact" : ""} ${className}`.trim()}
      data-render-mode={renderMode}
      style={
        renderMode === "css"
          ? {
              background: `radial-gradient(circle at 58% 42%, ${colorA}33, ${colorB}1c 46%, #05030a 82%)`,
            }
          : undefined
      }
    >
      <canvas
        ref={canvasRef}
        className="shader-stage__canvas"
        aria-hidden="true"
      />
      <div className="shader-stage__overlay">
        <div className="shader-stage__meta">
          {title ? (
            <strong className="shader-stage__title">{title}</strong>
          ) : null}
          {subtitle ? (
            <span className="shader-stage__subtitle">{subtitle}</span>
          ) : null}
        </div>
        <button
          type="button"
          className="button shader-stage__toggle"
          aria-pressed={userPaused}
          onClick={() => setUserPaused((current) => !current)}
        >
          {userPaused ? "Resume GPU preview" : "Pause GPU preview"}
        </button>
      </div>
    </div>
  );
}
