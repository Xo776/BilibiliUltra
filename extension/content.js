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
  autoAnalyze();   // ← 进页面自动分析, 不需要手动输入 BV
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
    if (video) {
      STATE.video = video;
      console.log('[密度分析器] 播放器就绪');
      // 不要在这里调 setupAutoSkip/ renderHeatmap
      // 等分析数据加载完 applyAnalysis() 再调
      return;
    }
    setTimeout(check, 1000);
  };
  check();
}

// ============================================================
// 热力图渲染 — 浮动叠加在播放器底部
// ============================================================

function renderHeatmap() {
  if (!STATE.heatmap || !STATE.analysis) return;

  // 找播放器容器 (B站新版 bpx 或旧版)
  const player = document.querySelector('.bpx-player-container, #bilibili-player, .bpx-player-video-wrap');
  if (!player) { setTimeout(renderHeatmap, 500); return; }

  // 移除旧 Canvas
  if (STATE.canvas) STATE.canvas.remove();

  const playerRect = player.getBoundingClientRect();
  if (playerRect.width < 100) { setTimeout(renderHeatmap, 1000); return; }

  const canvas = document.createElement('canvas');
  canvas.id = 'biliultra-heatmap';
  canvas.style.cssText = `
    position: fixed;
    left: ${playerRect.left}px;
    bottom: ${window.innerHeight - playerRect.bottom + 42}px;
    width: ${playerRect.width}px; height: 10px;
    border-radius: 5px;
    z-index: 9999;
    pointer-events: auto;
    cursor: pointer;
    opacity: 0.9;
  `;
  canvas.width = playerRect.width;
  canvas.height = 10;

  document.body.appendChild(canvas);
  STATE.canvas = canvas;

  // 绘制
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  const dur = STATE.analysis.meta.duration || 60;
  const segs = STATE.analysis.segments || [];

  ctx.clearRect(0, 0, w, h);
  for (const seg of segs) {
    const x = (seg.start / dur) * w;
    const segW = Math.max(1.5, ((seg.end - seg.start) / dur) * w);

    if (seg.is_ad) {
      ctx.fillStyle = 'rgba(255, 70, 70, 0.9)';
    } else {
      const d = seg.density || 5;
      // 绿(干货) → 黄(普通) → 灰(废话)
      const r = Math.round(80 - d * 5);
      const g = Math.round(50 + d * 17);
      const b = 40;
      ctx.fillStyle = `rgb(${r},${g},${b})`;
    }
    ctx.fillRect(x, 0, segW, h);
  }

  // 播放进度指示线
  if (STATE.video && STATE.video.duration) {
    const px = (STATE.video.currentTime / STATE.video.duration) * w;
    ctx.fillStyle = '#fff';
    ctx.fillRect(px - 1, 0, 2, h);
  }

  // 图例
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(0, 0, 44, h);
  ctx.fillStyle = '#fff';
  ctx.font = '8px system-ui';
  ctx.fillText('干货', 3, 8);
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(w - 26, 0, 26, h);
  ctx.fillStyle = '#ff5050';
  ctx.fillText('广告', w - 23, 8);

  // 点击跳转
  canvas.onclick = (e) => {
    if (!STATE.video) return;
    STATE.video.currentTime = (e.offsetX / w) * dur;
  };

  // 播放进度实时更新
  if (!STATE._progressUpdater) {
    STATE._progressUpdater = setInterval(() => {
      if (!STATE.video || !STATE.canvas) return;
      const ctx2 = STATE.canvas.getContext('2d');
      const px2 = (STATE.video.currentTime / STATE.video.duration) * w;
      // 重绘进度线
      ctx2.clearRect(0, 0, w, h);
      // 重绘所有段
      for (const seg of segs) {
        const x = (seg.start / dur) * w;
        const segW = Math.max(1.5, ((seg.end - seg.start) / dur) * w);
        if (seg.is_ad) ctx2.fillStyle = 'rgba(255, 70, 70, 0.9)';
        else {
          const d = seg.density || 5;
          ctx2.fillStyle = `rgb(${Math.round(80-d*5)},${Math.round(50+d*17)},40)`;
        }
        ctx2.fillRect(x, 0, segW, h);
      }
      // 进度线
      ctx2.fillStyle = '#fff';
      ctx2.fillRect(px2 - 1, 0, 2, h);
      // 图例
      ctx2.fillStyle = 'rgba(0,0,0,0.6)';
      ctx2.fillRect(0, 0, 44, h);
      ctx2.fillStyle = '#fff';
      ctx2.font = '8px system-ui';
      ctx2.fillText('干货', 3, 8);
      ctx2.fillStyle = 'rgba(0,0,0,0.6)';
      ctx2.fillRect(w - 26, 0, 26, h);
      ctx2.fillStyle = '#ff5050';
      ctx2.fillText('广告', w - 23, 8);
    }, 500);
  }

  // 监听播放器尺寸变化 (全屏/窗口切换)
  if (!STATE._resizeObserver) {
    STATE._resizeObserver = new ResizeObserver(() => {
      if (STATE.heatmap && STATE.analysis) renderHeatmap();
    });
    STATE._resizeObserver.observe(player);
  }

  // 监听全屏变化
  if (!STATE._fullscreenHandler) {
    STATE._fullscreenHandler = () => {
      setTimeout(() => { if (STATE.heatmap && STATE.analysis) renderHeatmap(); }, 300);
    };
    document.addEventListener('fullscreenchange', STATE._fullscreenHandler);
  }

  console.log('[密度分析器] 热力图已渲染');
}

// ============================================================
// 自动跳过广告
// ============================================================

function setupAutoSkip() {
  if (!STATE.video) return;

  // 移除旧监听器, 避免重复累加
  if (STATE._skipHandler) {
    STATE.video.removeEventListener('timeupdate', STATE._skipHandler);
  }

  STATE._skipHandler = () => {
    if (!STATE.autoSkip || !STATE.analysis) return;
    const t = STATE.video.currentTime;
    const adSegs = STATE.analysis.ad_segments || [];

    for (const ad of adSegs) {
      const key = `${ad.start}-${ad.end}`;
      if (t >= ad.start && t < ad.end && !STATE.skippedAds.has(key)) {
        STATE.skippedAds.add(key);
        console.log(`[密度分析器] 自动跳过广告: ${fmtTime(ad.start)} → ${fmtTime(ad.end)}`);
        STATE.video.currentTime = ad.end + 0.1;
        showSkipToast(ad);
        break;
      }
    }
  };

  STATE.video.addEventListener('timeupdate', STATE._skipHandler);
  console.log('[密度分析器] 自动跳过已就绪, 广告段:', (STATE.analysis.ad_segments || []).length);
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

// === 自动分析 (进页面即触发) ===
async function autoAnalyze() {
  if (!STATE.bvid) return;
  console.log('[密度分析器] 自动分析:', STATE.bvid);

  // 先检查是否有缓存的 API 配置
  const apiConfig = await new Promise(resolve => {
    chrome.storage.local.get(['groqKey', 'llmKey'], resolve);
  });

  if (!apiConfig.groqKey && !apiConfig.llmKey) {
    // 没配置 API Key → 直接用演示数据展示效果
    console.log('[密度分析器] 未配置API → 演示模式');
    applyAnalysis(demoData());
    return;
  }

  const result = await runAnalysis(STATE.bvid);
  if (!result.ok) {
    console.log('[密度分析器] 后端不可用 → 演示模式');
    applyAnalysis(demoData());
  }
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

  // 先从 storage 读取 API 配置
  const apiConfig = await new Promise(resolve => {
    chrome.storage.local.get([
      'groqKey', 'llmProvider', 'llmKey', 'llmBaseUrl', 'llmModel',
    ], resolve);
  });

  if (!apiConfig.groqKey && !apiConfig.llmKey) {
    console.log('[密度分析器] 未配置 API Key, 显示演示数据');
    return { ok: false, error: '请先在插件弹窗中设置 API Key' };
  }

  // 先查本地缓存
  const cached = await getCachedAnalysis(bvid);
  if (cached) {
    console.log('[密度分析器] 使用缓存');
    applyAnalysis(cached);
    return { ok: true, segments: cached.segments?.length, cached: true };
  }

  // 调 Python 后端, 携带 API 配置
  try {
    const resp = await fetch(`http://localhost:8765/analyze?bvid=${bvid}`, {
      signal: AbortSignal.timeout(300000),
      headers: {
        'X-Groq-Key': apiConfig.groqKey || '',
        'X-LLM-Provider': apiConfig.llmProvider || 'openai',
        'X-LLM-Key': apiConfig.llmKey || '',
        'X-LLM-Base-Url': apiConfig.llmBaseUrl || '',
        'X-LLM-Model': apiConfig.llmModel || '',
      },
    });
    if (resp.ok) {
      const data = await resp.json();
      await cacheAnalysis(bvid, data);
      applyAnalysis(data);
      return { ok: true, segments: data.segments?.length };
    }
    const err = await resp.text();
    console.log('[密度分析器] 后端错误:', err);
    return { ok: false, error: err };
  } catch (e) {
    console.log('[密度分析器] 后端不可用, 显示演示数据');
    return { ok: false, error: '需要先启动 Python 后端: python server.py' };
  }
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
      if (STATE._progressUpdater) { clearInterval(STATE._progressUpdater); STATE._progressUpdater = null; }
      waitForPlayer();
      autoAnalyze();
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
