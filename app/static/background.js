/**
 * background.js
 * 1. Animated dot-wave canvas — full viewport coverage, subtle motion
 * 2. Verdict-aware ambient glow that follows the mouse (NOT a fake cursor)
 *    — native cursor is fully preserved
 */

(function () {
  'use strict';

  const VERDICT_COLORS = {
    buy:     { r: 0,   g: 230, b: 118 },
    hold:    { r: 255, g: 214, b: 0   },
    sell:    { r: 255, g: 23,  b: 68  },
    short:   { r: 255, g: 23,  b: 68  },
    default: { r: 255, g: 255, b: 255 },
  };

  /* ─────────────── DOT WAVE CANVAS ─────────────── */
  function initDotWave () {
    const canvas = document.createElement('canvas');
    canvas.id = 'dot-wave-canvas';
    document.body.prepend(canvas);

    const ctx = canvas.getContext('2d');

    const COLS        = 72;
    const ROWS        = 40;
    const DOT_BASE_R  = 1.0;
    const WAVE_AMP    = 15;     // subtle (was 26)
    const WAVE_SPEED  = 0.0004; // slow drift (was 0.0008) both of which were too fast ^^^
    const WAVE_FREQ_X = 0.22;
    const WAVE_FREQ_Z = 0.30;
    const DEPTH_BASE  = 0.3;

    const RIPPLE_RADIUS = 80;
    const RIPPLE_LIFT   = 2.5;
    const RIPPLE_ALPHA  = 0.15;

    let W, H, colGap, rowGap;

    function resize () {
      W = canvas.width  = window.innerWidth;
      H = canvas.height = window.innerHeight;
      colGap = W / (COLS - 1);
      rowGap = H / (ROWS - 1); // full height coverage
    }

    resize();
    window.addEventListener('resize', resize, { passive: true });

    let t = 0;
    let mx = W / 2, my = H / 2;
    window.addEventListener('mousemove', e => { mx = e.clientX; my = e.clientY; }, { passive: true });

    function draw () {
      ctx.clearRect(0, 0, W, H);
      t += WAVE_SPEED;

      for (let row = 0; row < ROWS; row++) {
        const depth = row / (ROWS - 1);

        for (let col = 0; col < COLS; col++) {
          const bx = col * colGap;
          const by = row * rowGap;

          const waveY =
            Math.sin(col * WAVE_FREQ_X * 0.18 + t * 5 + row * 0.2) * WAVE_AMP * (0.6 + depth * 0.4) +
            Math.sin(col * WAVE_FREQ_Z * 0.13 - t * 3.5 + row * 0.15) * WAVE_AMP * 0.35;

          const x = bx;
          const y = by + waveY;

          const dx = x - mx, dy = y - my;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const proximity = dist < RIPPLE_RADIUS ? (1 - dist / RIPPLE_RADIUS) : 0;
          const ripple = proximity > 0 ? Math.sin(proximity * Math.PI) * RIPPLE_LIFT : 0;

          const r = DOT_BASE_R * (DEPTH_BASE + (1 - DEPTH_BASE) * depth) + ripple * 0.4;
          const alpha = 0.1 + depth * 0.45 + proximity * RIPPLE_ALPHA;

          ctx.beginPath();
          ctx.arc(x, y + ripple, Math.max(r, 0.3), 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255,255,255,${Math.min(alpha, 0.75)})`;
          ctx.fill();
        }
      }

      requestAnimationFrame(draw);
    }

    draw();
  }

  /* ─────────────── AMBIENT VERDICT GLOW ─────────────── */
  function initAmbientGlow () {
    const blob = document.createElement('div');
    blob.id = 'verdict-ambient';
    Object.assign(blob.style, {
      position:      'fixed',
      pointerEvents: 'none',
      zIndex:        '0',
      width:         '320px',
      height:        '320px',
      borderRadius:  '50%',
      transform:     'translate(-50%, -50%)',
      mixBlendMode:  'screen',
      opacity:       '0',
      transition:    'opacity 0.4s ease',
    });
    document.body.appendChild(blob);

    let cx = -999, cy = -999;
    let bx = cx,   by = cy;
    let targetR = 255, targetG = 255, targetB = 255;
    let curR = 255,   curG = 255,   curB = 255;
    let visible = false;

    function lerp (a, b, t) { return a + (b - a) * t; }

    window.addEventListener('mousemove', e => {
      cx = e.clientX; cy = e.clientY;
      if (!visible) { blob.style.opacity = '1'; visible = true; }
    }, { passive: true });

    document.addEventListener('mouseover', e => {
      const card = e.target.closest('.card');
      if (!card) return;
      const badge = card.querySelector('.verdict');
      if (!badge) return;
      let verdict = 'default';
      badge.classList.forEach(cls => {
        const m = cls.match(/^verdict-(.+)$/);
        if (m) verdict = m[1];
      });
      const col = VERDICT_COLORS[verdict] || VERDICT_COLORS.default;
      targetR = col.r; targetG = col.g; targetB = col.b;
      card.style.setProperty('--cursor-r', col.r);
      card.style.setProperty('--cursor-g', col.g);
      card.style.setProperty('--cursor-b', col.b);
    });

    document.addEventListener('mouseout', e => {
      const card = e.target.closest('.card');
      if (!card || card.contains(e.relatedTarget)) return;
      targetR = VERDICT_COLORS.default.r;
      targetG = VERDICT_COLORS.default.g;
      targetB = VERDICT_COLORS.default.b;
    });

    // seed card colour vars on boot
    document.querySelectorAll('.card').forEach(card => {
      const badge = card.querySelector('.verdict');
      if (!badge) return;
      let verdict = 'default';
      badge.classList.forEach(cls => {
        const m = cls.match(/^verdict-(.+)$/);
        if (m) verdict = m[1];
      });
      const col = VERDICT_COLORS[verdict] || VERDICT_COLORS.default;
      card.style.setProperty('--cursor-r', col.r);
      card.style.setProperty('--cursor-g', col.g);
      card.style.setProperty('--cursor-b', col.b);
    });

    const POS_LERP   = 0.08;
    const COLOR_LERP = 0.04;

    function tick () {
      bx = lerp(bx, cx, POS_LERP);
      by = lerp(by, cy, POS_LERP);
      blob.style.left = bx + 'px';
      blob.style.top  = by + 'px';

      curR = lerp(curR, targetR, COLOR_LERP);
      curG = lerp(curG, targetG, COLOR_LERP);
      curB = lerp(curB, targetB, COLOR_LERP);

      const r = Math.round(curR), g = Math.round(curG), b = Math.round(curB);
      blob.style.background =
        `radial-gradient(circle, rgba(${r},${g},${b},0.09) 0%, transparent 70%)`;

      const root = document.documentElement;
      root.style.setProperty('--cursor-r', r);
      root.style.setProperty('--cursor-g', g);
      root.style.setProperty('--cursor-b', b);

      requestAnimationFrame(tick);
    }

    tick();
  }

  /* ─────────────── BOOT ─────────────── */
  function boot () {
    initDotWave();
    initAmbientGlow();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

})();