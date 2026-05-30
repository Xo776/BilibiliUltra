/**
 * content.js — B站内容密度分析器 前端
 * 
 * 功能:
 *  1. 进度条上方渲染信息密度热力图 (Canvas)
 *  2. 自动跳过检测到的广告段
 *  3. 鼠标悬停显示片段摘要
 *  4. 与 popup 双向通信
 */

// ============================================================
// 状态管理
// ============================================================

const STATE = {
  bvid: null,
  analysis: null,       // analysis.json 数据
  video: null,          // <video> 元素
  canvas: null,         // 热力图 Canvas
  autoSkip: true,
  heatmap: true,
  tooltip: false,
  skippedAds: new Set(),
  observer: null,
};

// ============================================================
// 初始化
// ============================================================

function init() {
  loadSettings();
  extractBvid();
  waitForPlayer();
  listenPopup();
  observeUrlChange();
}

// === 加载设置 ===
function loadSettings() {
  chrome.storage.local.get(['autoSkip', 'heatmap', 'tooltip'], (data) => {
    STATE.autoSkip = data.autoSkip !== false;
    STATE.heatmap = data.heatmap !== false;
    STATE.tooltip = data.tooltip === true;
    if (STATE.analysis) renderHeatmap();
  });
}

// === 提取 BV号 ===
function extractBvid() {
  const m = location.pathname.match(/BV[a-zA-Z0-9]{10}/);
  STATE.bvid = m ? m[0] : null;
}

// === 等待播放器加载 ===
function waitForPlayer() {
  const check = () => {
    const video = document.querySelector('video');
    const progress = document.querySelector('.bui-progress-wrap');
    if (video && progress) {
      STATE.video = video;
      setupAutoSkip();
      requestAnimationFrame(() => renderHeatmap());
      return;
    }
    setTimeout(check, 1000);
  };
  check();
}

// ============================================================
// 热力图渲染 (Canvas on Progress Bar)
// ============================================================

function renderHeatmap() {
  if (!STATE.heatmap || !STATE.analysis) return;

  const progressWrap = document.querySelector('.bui-progress-wrap');
  if (!progressWrap) { setTimeout(renderHeatmap, 500); return; }

  // 移除旧 Canvas
  if (STATE.canvas) STATE.canvas.remove();

  const rect = progressWrap.getBoundingClientRect();
  const canvas = document.createElement('canvas');
  canvas.style.cssText = `
    position: absolute; top: -14px; left: 0;
    width: 100%; height: 12px;
    border-radius: 6px; z-index: 999;
    pointer-events: auto; cursor: pointer;
  `;
  canvas.width = rect.width;
  canvas.height = 12;

  // 插入到进度条容器
  progressWrap.style.position = 'relative';
  progressWrap.insertBefore(canvas, progressWrap.firstChild);
  STATE.canvas = canvas;

  // 绘制
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  const dur = STATE.analysis.meta.duration || 60;
  const segs = STATE.analysis.segments || [];

  for (const seg of segs) {
    const x = (seg.start / dur) * w;
    const segW = Math.max(1, ((seg.end - seg.start) / dur) * w);

    if (seg.is_ad) {
      // 广告 → 红色
      ctx.fillStyle = 'rgba(255, 80, 80, 0.85)';
    } else {
      // 信息密度 → 绿(高) → 灰(低)
      const d = seg.density || 5;
      const r = Math.round(80 - d * 6);        // 密度高 → 绿色多
      const g = Math.round(40 + d * 18);
      const b = 40;
      ctx.fillStyle = `rgb(${r},${g},${b})`;
    }
    ctx.fillRect(x, 0, segW, h);
  }

  // 边框圆角
  ctx.strokeStyle = 'rgba(255,255,255,0.3)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(0, 0, w, h, 6);
  ctx.stroke();

  // 图例
  ctx.fillStyle = '#fff';
  ctx.font = '8px system-ui';
  ctx.fillText('高密度', 4, 9);
  ctx.fillStyle = '#ff5050';
  ctx.fillText('广告', w - 30, 9);

  // 交互: 点击热力图跳转
  canvas.addEventListener('click', (e) => {
    if (!STATE.video) return;
    const ratio = e.offsetX / w;
    STATE.video.currentTime = ratio * dur;
  });

  // 悬停提示
  if (STATE.tooltip) {
    canvas.title = '';
    canvas.addEventListener('mousemove', (e) => {
      const ratio = e.offsetX / w;
      const time = ratio * dur;
      const seg = segs.find(s => time >= s.start && time < s.end);
      canvas.title = seg
        ? `${fmtTime(seg.start)}-${fmtTime(seg.end)} | 密度:${seg.density} | ${seg.summary || ''}${seg.is_ad ? ' ⚠广告' : ''}`
        : fmtTime(time);
    });
  }
}

// ============================================================
// 自动跳过广告
// ============================================================

function setupAutoSkip() {
  if (!STATE.video) return;

  STATE.video.addEventListener('timeupdate', () => {
    if (!STATE.autoSkip || !STATE.analysis) return;

    const t = STATE.video.currentTime;
    const adSegs = STATE.analysis.ad_segments || [];

    for (const ad of adSegs) {
      const key = `${ad.start}-${ad.end}`;
      if (t >= ad.start && t < ad.end && !STATE.skippedAds.has(key)) {
        STATE.skippedAds.add(key);
        console.log(`[密度分析器] 自动跳过广告: ${fmtTime(ad.start)} → ${fmtTime(ad.end)}`);
        STATE.video.currentTime = ad.end + 0.1;

        // 显示跳过提示
        showSkipToast(ad);
        break;
      }
    }
  });
}

// === 提示浮层 ===
function showSkipToast(ad) {
  const toast = document.createElement('div');
  toast.textContent = `⏭ 已跳过广告 (${fmtTime(ad.start)}~${fmtTime(ad.end)})`;
  toast.style.cssText = `
    position: fixed; top: 80px; right: 24px;
    background: rgba(0,0,0,0.85); color: #00d4ff;
    padding: 10px 18px; border-radius: 8px; z-index: 99999;
    font-size: 14px; transition: opacity .5s;
  `;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 500);
  }, 2500);
}

// ============================================================
// 通信: 接收 popup 指令
// ============================================================

function listenPopup() {
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === 'configUpdate') {
      STATE.autoSkip = msg.config.autoSkip;
      STATE.heatmap = msg.config.heatmap;
      STATE.tooltip = msg.config.tooltip;
      if (STATE.heatmap && STATE.analysis) renderHeatmap();
      if (!STATE.heatmap && STATE.canvas) {
        STATE.canvas.remove();
        STATE.canvas = null;
      }
      sendResponse({ ok: true });
      return true;
    }

    if (msg.action === 'analyze') {
      runAnalysis(msg.bvid).then(result => {
        sendResponse(result);
      });
      return true;  // 异步响应
    }
  });
}

// ============================================================
// 分析流程 (调 Python 后端 或 本地缓存)
// ============================================================

async function runAnalysis(bvid) {
  console.log('[密度分析器] 开始分析:', bvid);

  // 先查本地缓存
  const cached = await getCachedAnalysis(bvid);
  if (cached) {
    console.log('[密度分析器] 使用缓存');
    applyAnalysis(cached);
    return { ok: true, segments: cached.segments?.length, cached: true };
  }

  // 调 Python 后端 (需要本地运行 python server)
  try {
    const resp = await fetch(`http://localhost:8765/analyze?bvid=${bvid}`, {
      signal: AbortSignal.timeout(120000),
    });
    if (resp.ok) {
      const data = await resp.json();
      await cacheAnalysis(bvid, data);
      applyAnalysis(data);
      return { ok: true, segments: data.segments?.length };
    }
  } catch (e) {
    console.log('[密度分析器] 后端不可用, 尝试本地分析...');
  }

  // 回退: 在当前页面采集数据并分析
  return { ok: false, error: '需要先运行 Python 后端: python server.py' };
}

// === 应用分析结果 ===
function applyAnalysis(data) {
  STATE.analysis = data;
  STATE.skippedAds.clear();
  setupAutoSkip();
  renderHeatmap();
}

// === 缓存 ===
const CACHE_PREFIX = 'bili_analysis_';

async function getCachedAnalysis(bvid) {
  return new Promise(resolve => {
    chrome.storage.local.get([CACHE_PREFIX + bvid], (result) => {
      const data = result[CACHE_PREFIX + bvid];
      if (data && (Date.now() - data.cachedAt < 86400000)) {  // 24h
        resolve(data);
      } else {
        resolve(null);
      }
    });
  });
}

async function cacheAnalysis(bvid, data) {
  data.cachedAt = Date.now();
  chrome.storage.local.set({ [CACHE_PREFIX + bvid]: data });
}

// ============================================================
// URL 变化监听 (B站 SPA)
// ============================================================

function observeUrlChange() {
  let lastBvid = STATE.bvid;
  STATE.observer = new MutationObserver(() => {
    const newBvid = location.pathname.match(/BV[a-zA-Z0-9]{10}/)?.[0];
    if (newBvid && newBvid !== lastBvid) {
      lastBvid = newBvid;
      STATE.bvid = newBvid;
      STATE.analysis = null;
      STATE.skippedAds.clear();
      if (STATE.canvas) { STATE.canvas.remove(); STATE.canvas = null; }
      waitForPlayer();
    }
  });
  STATE.observer.observe(document.body, { childList: true, subtree: true });
}

// ============================================================
// 工具函数
// ============================================================

function fmtTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, '0')}`;
}

// 不依赖扩展 API 的演示数据 (开发用)
function demoData() {
  return {
    meta: { bvid: STATE.bvid, title: "演示", duration: 120, total_segments: 4 },
    segments: [
      { start: 0, end: 30, density: 8, ad_probability: 0, summary: "核心内容", is_ad: false },
      { start: 30, end: 55, density: 2, ad_probability: 9, summary: "三连广告", is_ad: true },
      { start: 55, end: 90, density: 7, ad_probability: 1, summary: "继续干货", is_ad: false },
      { start: 90, end: 120, density: 4, ad_probability: 0, summary: "结束语", is_ad: false },
    ],
    ad_segments: [{ start: 30, end: 55 }],
  };
}

// === 启动 ===
init();
console.log('[密度分析器] 已加载 | 自动跳过:' + STATE.autoSkip + ' | 热力图:' + STATE.heatmap);
