/**
 * background.js
 * Drop this script at the bottom of <body> (or import it).
 * It handles:
 *   1. Animated dot-wave canvas background
 *   2. Verdict-aware custom cursor glow
 *
 * Verdict colour map  →  buy: green | hold: yellow | sell/short: red
 * The cursor colour transitions smoothly between verdicts as you hover cards.
 */

(function () {
  'use strict';

  /* ─────────────── COLOUR MAP ─────────────── */
  const VERDICT_COLORS = {
    buy:   { r: 0,   g: 230, b: 118 },   // --green
    hold:  { r: 255, g: 214, b: 0   },   // --yellow
    sell:  { r: 255, g: 23,  b: 68  },   // --red
    short: { r: 255, g: 23,  b: 68  },   // --red
    default: { r: 0, g: 230, b: 118 },   // fallback green
  };

  /* ─────────────── DOT WAVE CANVAS ─────────────── */
  function initDotWave () {
    const canvas = document.createElement('canvas');
    canvas.id = 'dot-wave-canvas';
    document.body.prepend(canvas);

    const ctx = canvas.getContext('2d');

    /* grid config */
    const COLS       = 80;   // dots per row
    const ROWS       = 32;   // rows
    const DOT_BASE_R = 1.1;  // base dot radius px
    const WAVE_AMP   = 26;   // vertical wave amplitude px
    const WAVE_SPEED = 0.0008;
    const WAVE_FREQ_X = 0.35;
    const WAVE_FREQ_Z = 0.55; // secondary wave
    const DEPTH_SCALE = 0.55; // perspective-ish scale at back vs front

    let W, H, colGap, rowGap, offsetX, offsetY;

    function resize () {
      W = canvas.width  = window.innerWidth;
      H = canvas.height = window.innerHeight;
      colGap  = W / (COLS - 1);
      rowGap  = H * 0.55 / (ROWS - 1);
      offsetX = 0;
      offsetY = H * 0.22;   // vertical centre of wave field
    }

    resize();
    window.addEventListener('resize', resize, { passive: true });

    let t = 0;

    /* mouse influence — subtle ripple toward cursor */
    let mx = W / 2, my = H / 2;
    window.addEventListener('mousemove', e => { mx = e.clientX; my = e.clientY; }, { passive: true });

    function draw () {
      ctx.clearRect(0, 0, W, H);

      t += WAVE_SPEED;

      for (let row = 0; row < ROWS; row++) {
        /* depth: 0 = back, 1 = front */
        const depth = row / (ROWS - 1);
        const scale = DEPTH_BASE + (1 - DEPTH_BASE) * depth;   // size perspective

        for (let col = 0; col < COLS; col++) {
          const bx = col * colGap;
          const by = offsetY + row * rowGap;

          /* wave height — two overlapping sine waves */
          const waveY =
            Math.sin(col * WAVE_FREQ_X * 0.18 + t * 7 + row * 0.25)  * WAVE_AMP * (1 - depth * 0.3) +
            Math.sin(col * WAVE_FREQ_Z * 0.14 - t * 5 + row * 0.18)  * WAVE_AMP * 0.45 * (1 - depth * 0.2);

          const x = bx;
          const y = by + waveY;

          /* mouse proximity ripple */
          const dx = x - mx, dy = y - my;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const ripple = dist < 120 ? Math.sin((1 - dist / 120) * Math.PI) * 6 : 0;

          /* dot size: smaller at back, bigger at front, ripple boost */
          const r = DOT_BASE_R * (DEPTH_SCALE + (1 - DEPTH_SCALE) * depth) + ripple * 0.6;

          /* dot opacity: fade at back */
          const alpha = 0.18 + depth * 0.55 + (dist < 120 ? (1 - dist / 120) * 0.35 : 0);

          ctx.beginPath();
          ctx.arc(x, y + ripple, Math.max(r, 0.3), 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255,255,255,${Math.min(alpha, 1)})`;
          ctx.fill();
        }
      }

      requestAnimationFrame(draw);
    }

    const DEPTH_BASE = 0.3;
    draw();
  }

  /* ─────────────── CUSTOM CURSOR ─────────────── */
  function initCursor () {
    /* build DOM */
    const glow = document.createElement('div');
    glow.id = 'cursor-glow';
    glow.innerHTML = '<div class="cursor-halo"></div><div class="cursor-core"></div>';
    document.body.appendChild(glow);

    let cx = -200, cy = -200;           // cursor position
    let targetR = 0, targetG = 230, targetB = 118;   // target colour
    let curR = 0,   curG = 230, curB = 118;           // current interpolated colour
    const LERP = 0.06;                  // colour transition speed

    const root = document.documentElement;

    function setColor (r, g, b) { targetR = r; targetG = g; targetB = b; }
    function applyColor () {
      curR = lerp(curR, targetR, LERP);
      curG = lerp(curG, targetG, LERP);
      curB = lerp(curB, targetB, LERP);
      root.style.setProperty('--cursor-r', Math.round(curR));
      root.style.setProperty('--cursor-g', Math.round(curG));
      root.style.setProperty('--cursor-b', Math.round(curB));
    }

    function lerp (a, b, t) { return a + (b - a) * t; }

    /* track mouse */
    window.addEventListener('mousemove', e => {
      cx = e.clientX;
      cy = e.clientY;
    }, { passive: true });

    /* detect card verdict on hover */
    document.addEventListener('mouseover', e => {
      const card = e.target.closest('.card');
      if (!card) return;

      document.body.classList.add('hovering-card');

      /* find verdict badge inside card */
      const badge = card.querySelector('.verdict');
      if (!badge) return;

      let verdict = 'default';
      badge.classList.forEach(cls => {
        const m = cls.match(/^verdict-(.+)$/);
        if (m) verdict = m[1];
      });

      const col = VERDICT_COLORS[verdict] || VERDICT_COLORS.default;
      setColor(col.r, col.g, col.b);

      /* also update card's --cursor-r/g/b for inner glow */
      card.style.setProperty('--cursor-r', col.r);
      card.style.setProperty('--cursor-g', col.g);
      card.style.setProperty('--cursor-b', col.b);
    });

    document.addEventListener('mouseout', e => {
      if (!e.target.closest('.card')) return;
      const card = e.target.closest('.card');
      /* reset only when leaving the card entirely */
      if (card && !card.contains(e.relatedTarget)) {
        document.body.classList.remove('hovering-card');
        setColor(
          VERDICT_COLORS.default.r,
          VERDICT_COLORS.default.g,
          VERDICT_COLORS.default.b
        );
      }
    });

    /* animation loop for smooth colour lerp + position */
    let rafX = cx, rafY = cy;
    const POS_LERP = 0.18;

    function tick () {
      rafX = lerp(rafX, cx, POS_LERP);
      rafY = lerp(rafY, cy, POS_LERP);
      glow.style.left = rafX + 'px';
      glow.style.top  = rafY + 'px';
      applyColor();
      requestAnimationFrame(tick);
    }

    tick();
  }

  /* ─────────────── CARD MOUSE-FOLLOW INNER GLOW ─────────────── */
  function initCardGlow () {
    document.addEventListener('mousemove', e => {
      const card = e.target.closest?.('.card');
      if (!card) return;
      const rect = card.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width  * 100).toFixed(1) + '%';
      const y = ((e.clientY - rect.top)  / rect.height * 100).toFixed(1) + '%';
      card.style.setProperty('--mouse-x', x);
      card.style.setProperty('--mouse-y', y);
    }, { passive: true });
  }

  /* ─────────────── BOOT ─────────────── */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  function boot () {
    initDotWave();
    initCursor();
    initCardGlow();
  }

})();