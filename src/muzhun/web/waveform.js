"use strict";
class MuzhunWaveform {
  constructor(canvas, audio, load, seek) {
    this.canvas = canvas; this.audio = audio; this.load = load; this.seek = seek;
    this.data = null; this.range = null; this.span = 30; this.sequence = 0;
    canvas.addEventListener("click", event => {
      if (!this.data) return;
      const box = canvas.getBoundingClientRect(), ratio = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
      this.seek(this.data.start + ratio * (this.data.end - this.data.start));
    });
    canvas.addEventListener("keydown", event => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault(); this.seek(Math.max(0, Math.min(audio.duration || 0, audio.currentTime + (event.key === "ArrowLeft" ? -.1 : .1))));
      }
    });
    audio.addEventListener("timeupdate", () => this.draw());
    new ResizeObserver(() => this.draw()).observe(canvas);
  }
  async focus(start, end, duration) {
    if (!(duration > 0)) return;
    this.range = start === null || end === null ? null : [start, end];
    const center = start === null ? this.audio.currentTime : (start + end) / 2;
    const span = Math.min(duration, this.span), lo = Math.max(0, Math.min(duration - span, center - span / 2));
    const sequence = ++this.sequence;
    try {
      const data = await this.load(lo, lo + span);
      if (sequence !== this.sequence) return;
      this.data = data; this.draw();
    } catch { if (sequence === this.sequence) { this.data = null; this.draw(); } }
  }
  draw() {
    const canvas = this.canvas, box = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(box.width * dpr); canvas.height = Math.round(96 * dpr);
    const c = canvas.getContext("2d"); c.scale(dpr, dpr);
    const width = box.width, height = 96, data = this.data;
    c.fillStyle = "#f7f9fc"; c.fillRect(0, 0, width, height);
    if (!data?.peaks.length) { c.fillStyle = "#687078"; c.font = "13px sans-serif"; c.fillText("波形暂不可用，可用播放器与起止按钮定位", 14, 52); return; }
    const x = time => (time - data.start) / (data.end - data.start) * width;
    if (this.range) { c.fillStyle = "#dbeafe"; c.fillRect(Math.max(0, x(this.range[0])), 0, Math.min(width, x(this.range[1])) - Math.max(0, x(this.range[0])), height); }
    c.fillStyle = "#6684a6";
    data.peaks.forEach((peak, index) => { const h = Math.max(1, peak * 58); c.fillRect(index / data.peaks.length * width, (height - h) / 2, Math.max(1, width / data.peaks.length), h); });
    c.strokeStyle = "#2563eb"; c.lineWidth = 1.5; c.beginPath(); c.moveTo(x(this.audio.currentTime), 5); c.lineTo(x(this.audio.currentTime), 82); c.stroke();
    c.fillStyle = "#55606e"; c.font = "11px sans-serif"; c.fillText(data.start.toFixed(1) + " s", 8, 92); c.fillText(data.end.toFixed(1) + " s", Math.max(8, width - 60), 92);
  }
}
window.MuzhunWaveform = MuzhunWaveform;
