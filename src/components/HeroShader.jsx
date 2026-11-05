/**
 * HeroShader.jsx — Componente React del shader WebGL hero.
 * Reutilizable en cualquier repo React.
 * <HeroShader colorA="#0ea5e9" colorB="#7c3aed" />
 */
import React, { useEffect, useRef } from 'react';

export default function HeroShader({ colorA = '#0ea5e9', colorB = '#7c3aed' }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const instance = window.initHeroShader?.('hero-canvas', colorA, colorB);

    return () => {
      if (instance && typeof instance.destroy === 'function') {
        instance.destroy();
      }
    };
  }, [colorA, colorB]);

  return (
    <div className="relative w-full h-[600px] min-h-[400px]">
      <canvas id="hero-canvas" className="absolute inset-0 w-full h-full block -z-10" />
      <div className="absolute inset-0 bg-gradient-to-b from-black/20 via-transparent to-black/10" />
    </div>
  );
}

HeroShader.displayName = 'HeroShader';
