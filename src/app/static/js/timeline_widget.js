(function () {
  const instances = new Map();

  function hashString(s) {
    let h = 0;
    for (let i = 0; i < s.length; i += 1) h = ((h << 5) - h) + s.charCodeAt(i);
    return Math.abs(h);
  }

  function formatMs(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  function tooltipSpanText(span) {
    const payload = {
      ...span,
      duration_ms: Math.max(0, (span.end_ms || 0) - (span.start_ms || 0)),
      start_hhmmss: formatMs(span.start_ms || 0),
      end_hhmmss: formatMs(span.end_ms || 0),
    };
    return JSON.stringify(payload, null, 2);
  }

  function colorFor(track, label) {
    const hue = hashString(`${track}|${label}`) % 360;
    return `hsl(${hue}, 65%, 52%)`;
  }

  function ensureInstance(rootId) {
    if (instances.has(rootId)) return instances.get(rootId);

    const root = document.getElementById(rootId);
    if (!root) return null;

    const canvas = root.querySelector('canvas');
    const tooltip = root.querySelector('[data-role="tooltip"]');
    const empty = root.querySelector('[data-role="empty"]');
    if (!canvas || !tooltip || !empty) return null;

    const ctx = canvas.getContext('2d');
    const state = {
      root,
      canvas,
      ctx,
      tooltip,
      empty,
      payload: null,
      tracks: [],
      visibleTrackSet: null,
      pxPerMs: 0.02,
      minPxPerMs: 0.0005,
      maxPxPerMs: 0.5,
      initialPxPerMs: 0.02,
      offsetMs: 0,
      playheadMs: 0,
      hovered: null,
      scrubbing: false,
      suppressClickSeek: false,
      dragStartX: 0,
      raf: null,
      rects: [],
      dpr: window.devicePixelRatio || 1,
      eventTargetId: rootId,
      videoElementId: null,
    };

    function queueDraw() {
      if (state.raf) return;
      state.raf = requestAnimationFrame(() => {
        state.raf = null;
        draw();
      });
    }

    function resizeCanvas() {
      const w = state.root.clientWidth || 900;
      const h = Math.max(180, 48 + (state.tracks.length * 28));
      state.canvas.style.width = `${w}px`;
      state.canvas.style.height = `${h}px`;
      state.canvas.width = Math.floor(w * state.dpr);
      state.canvas.height = Math.floor(h * state.dpr);
      state.ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
      queueDraw();
    }

    function contentWidth() {
      return Math.max(1, state.canvas.clientWidth - 100);
    }

    function maxTimelineMs() {
      if (!state.payload) return 1;
      const videoMs = Math.max(1, state.payload.video && state.payload.video.duration_ms ? state.payload.video.duration_ms : 1);
      const spanMax = (state.payload.spans || []).reduce((m, s) => Math.max(m, s.end_ms || 0), 0);
      return Math.max(videoMs, spanMax, 1);
    }

    function clampOffset() {
      if (!state.payload) return;
      const duration = maxTimelineMs();
      const viewportMs = contentWidth() / state.pxPerMs;
      const maxOffset = Math.max(0, duration - viewportMs);
      state.offsetMs = Math.max(0, Math.min(state.offsetMs, maxOffset));
    }

    function xToMs(x) {
      return state.offsetMs + (Math.max(0, x - 100) / state.pxPerMs);
    }

    function msToX(ms) {
      return 100 + ((ms - state.offsetMs) * state.pxPerMs);
    }

    function visibleTracks() {
      if (!state.visibleTrackSet || state.visibleTrackSet.size === 0) return state.tracks;
      return state.tracks.filter((t) => state.visibleTrackSet.has(t));
    }

    function draw() {
      const { ctx, canvas } = state;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);

      if (!state.payload || !state.payload.spans || state.payload.spans.length === 0) {
        state.empty.style.display = 'block';
        return;
      }
      state.empty.style.display = 'none';

      const rowH = 24;
      const topPad = 24;
      const leftPad = 100;
      const tracks = visibleTracks();
      state.rects = [];

      ctx.fillStyle = '#f3f4f6';
      ctx.fillRect(0, 0, w, h);

      ctx.strokeStyle = '#e5e7eb';
      ctx.lineWidth = 1;
      for (let i = 0; i <= tracks.length; i += 1) {
        const y = topPad + i * rowH;
        ctx.beginPath();
        ctx.moveTo(leftPad, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      ctx.fillStyle = '#111827';
      ctx.font = '12px sans-serif';
      tracks.forEach((track, i) => {
        ctx.fillText(track, 8, topPad + i * rowH + 16);
      });

      const startMs = state.offsetMs;
      const endMs = xToMs(w);

      const spans = state.payload.spans;
      for (let i = 0; i < spans.length; i += 1) {
        const s = spans[i];
        if (!tracks.includes(s.track)) continue;
        if (s.end_ms < startMs || s.start_ms > endMs) continue;
        const row = tracks.indexOf(s.track);
        const y = topPad + row * rowH + 4;
        const x = Math.max(leftPad, msToX(s.start_ms));
        const x2 = Math.min(w, msToX(s.end_ms));
        const bw = Math.max(2, x2 - x);
        const color = colorFor(s.track, s.label);
        ctx.fillStyle = color;
        ctx.fillRect(x, y, bw, rowH - 8);
        if (bw > 42) {
          ctx.fillStyle = '#ffffff';
          ctx.fillText(s.label || s.id, x + 4, y + 14);
        }
        state.rects.push({ x, y, w: bw, h: rowH - 8, span: s });
      }

      const px = msToX(state.playheadMs);
      if (px >= leftPad && px <= w) {
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(px, topPad - 8);
        ctx.lineTo(px, h);
        ctx.stroke();
      }

      ctx.fillStyle = '#111827';
      ctx.fillText(`Window: ${formatMs(startMs)} - ${formatMs(endMs)}`, leftPad, 14);
    }

    function hitTest(x, y) {
      for (let i = state.rects.length - 1; i >= 0; i -= 1) {
        const r = state.rects[i];
        if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) return r.span;
      }
      return null;
    }

    function emitSeek(timeMs, span) {
      const safeMs = Math.max(0, Math.floor(timeMs));
      if (state.videoElementId) {
        const player = document.getElementById(state.videoElementId);
        if (player && Number.isFinite(player.duration)) {
          player.currentTime = safeMs / 1000;
        }
      }
      if (window.nicegui && window.nicegui.send_event) {
        window.nicegui.send_event(state.eventTargetId || rootId, 'timeline_seek', { time_ms: safeMs, span_id: span ? span.id : null });
      }
    }

    function trackAtY(y) {
      const rowH = 24;
      const topPad = 24;
      const tracks = visibleTracks();
      const idx = Math.floor((y - topPad) / rowH);
      if (idx < 0 || idx >= tracks.length) return null;
      return tracks[idx];
    }

    function firstSpanStartForTrack(trackName) {
      if (!state.payload || !trackName) return null;
      let minStart = null;
      const spans = state.payload.spans || [];
      for (let i = 0; i < spans.length; i += 1) {
        const s = spans[i];
        if (s.track !== trackName) continue;
        const start = Math.max(0, s.start_ms || 0);
        if (minStart === null || start < minStart) minStart = start;
      }
      return minStart;
    }

    canvas.addEventListener('mousemove', (ev) => {
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;

      if (state.scrubbing) {
        const span = hitTest(x, y);
        const timeMs = span ? span.start_ms : xToMs(x);
        emitSeek(timeMs, span);
      }

      const span = hitTest(x, y);
      if (!span) {
        tooltip.style.display = 'none';
        state.hovered = null;
        return;
      }
      state.hovered = span;
      tooltip.style.display = 'block';
      tooltip.style.left = `${x + 12}px`;
      tooltip.style.top = `${y + 12}px`;
      tooltip.textContent = tooltipSpanText(span);
      if (window.nicegui && window.nicegui.send_event) {
        window.nicegui.send_event(state.eventTargetId || rootId, 'timeline_hover', { span_id: span.id });
      }
    });

    canvas.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
      state.scrubbing = false;
    });

    canvas.addEventListener('mousedown', (ev) => {
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      state.dragStartX = x;
      state.scrubbing = true;
      state.suppressClickSeek = false;
      const span = hitTest(x, y);
      const timeMs = span ? span.start_ms : xToMs(x);
      emitSeek(timeMs, span);
    });

    canvas.addEventListener('mouseup', (ev) => {
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const wasScrubbing = state.scrubbing;
      state.scrubbing = false;
      if (wasScrubbing && Math.abs(x - state.dragStartX) > 1) {
        state.suppressClickSeek = true;
      }
    });

    canvas.addEventListener('click', (ev) => {
      if (state.suppressClickSeek) {
        state.suppressClickSeek = false;
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      const span = hitTest(x, y);
      let timeMs = span ? span.start_ms : xToMs(x);
      if (!span) {
        const trackName = trackAtY(y);
        const trackStart = firstSpanStartForTrack(trackName);
        if (trackStart !== null) timeMs = trackStart;
      }
      emitSeek(timeMs, span);
    });

    window.addEventListener('resize', resizeCanvas);

    const api = {
      setData(payload) {
        state.payload = payload;
        state.tracks = [...new Set((payload.spans || []).map((s) => s.track || 'default'))].sort();
        state.visibleTrackSet = new Set(state.tracks);
        state.initialPxPerMs = payload.ui && payload.ui.initial_zoom ? payload.ui.initial_zoom : 0.02;
        state.pxPerMs = state.initialPxPerMs;
        state.minPxPerMs = payload.ui && payload.ui.min_zoom_ms_per_px ? payload.ui.min_zoom_ms_per_px : 0.0005;
        state.maxPxPerMs = payload.ui && payload.ui.max_zoom_ms_per_px ? payload.ui.max_zoom_ms_per_px : 0.5;
        state.offsetMs = 0;
        state.eventTargetId = (payload.ui && payload.ui.event_target_id) ? payload.ui.event_target_id : rootId;
        state.videoElementId = (payload.ui && payload.ui.video_element_id) ? payload.ui.video_element_id : null;
        resizeCanvas();
      },
      setPlayhead(timeMs) {
        state.playheadMs = Math.max(0, timeMs || 0);
        queueDraw();
      },
      zoomIn() {},
      zoomOut() {},
      reset() {},
      setTracks(tracks) {
        state.visibleTrackSet = new Set(tracks || []);
        queueDraw();
      },
      debug() {
        return {
          hasPayload: !!state.payload,
          payloadSpanCount: state.payload && state.payload.spans ? state.payload.spans.length : 0,
          trackCount: state.tracks.length,
          visibleTrackCount: state.visibleTrackSet ? state.visibleTrackSet.size : 0,
          rootId,
          eventTargetId: state.eventTargetId,
        };
      }
    };

    resizeCanvas();
    instances.set(rootId, api);
    return api;
  }

  window.timelineWidget = {
    init(rootId, payload) {
      const inst = ensureInstance(rootId);
      if (!inst) return false;
      inst.setData(payload);
      return true;
    },
    initWithRetry(rootId, payload, attempts = 12, delayMs = 50) {
      let count = 0;
      const tryInit = () => {
        const ok = window.timelineWidget.init(rootId, payload);
        if (ok) return;
        count += 1;
        if (count < attempts) setTimeout(tryInit, delayMs);
      };
      tryInit();
    },
    debug(rootId) {
      const inst = ensureInstance(rootId);
      if (!inst || !inst.debug) return { ready: false, rootId };
      return { ready: true, ...inst.debug() };
    },
    setPlayhead(rootId, timeMs) {
      const inst = ensureInstance(rootId);
      if (!inst) return;
      inst.setPlayhead(timeMs);
    },
    zoomIn(rootId) {
      const inst = ensureInstance(rootId);
      if (!inst) return;
      inst.zoomIn();
    },
    zoomOut(rootId) {
      const inst = ensureInstance(rootId);
      if (!inst) return;
      inst.zoomOut();
    },
    reset(rootId) {
      const inst = ensureInstance(rootId);
      if (!inst) return;
      inst.reset();
    },
    setTracks(rootId, tracks) {
      const inst = ensureInstance(rootId);
      if (!inst) return;
      inst.setTracks(tracks);
    }
  };
})();
