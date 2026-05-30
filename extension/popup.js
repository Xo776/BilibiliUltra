// popup.js — 控制面板逻辑

const $ = (id) => document.getElementById(id);
const btnAnalyze = $('btnAnalyze');
const bvInput = $('bvInput');
const statusEl = $('status');
const toggleAutoSkip = $('toggleAutoSkip');
const toggleHeatmap = $('toggleHeatmap');
const toggleTooltip = $('toggleTooltip');

// === 加载保存的设置 ===
chrome.storage.local.get(['autoSkip', 'heatmap', 'tooltip'], (data) => {
  toggleAutoSkip.checked = data.autoSkip !== false;     // 默认开
  toggleHeatmap.checked = data.heatmap !== false;
  toggleTooltip.checked = data.tooltip === true;         // 默认关
});

// === 开关事件 ===
[toggleAutoSkip, toggleHeatmap, toggleTooltip].forEach(el => {
  el.addEventListener('change', () => {
    const config = {
      autoSkip: toggleAutoSkip.checked,
      heatmap: toggleHeatmap.checked,
      tooltip: toggleTooltip.checked,
    };
    chrome.storage.local.set(config);
    // 通知 content script 更新
    sendToContent({ action: 'configUpdate', config });
  });
});

// === 分析按钮 ===
btnAnalyze.addEventListener('click', async () => {
  const input = bvInput.value.trim();
  if (!input) { setStatus('请输入 BV 号或视频链接', 'error'); return; }

  // 提取 BV 号
  const match = input.match(/BV[a-zA-Z0-9]{10}/);
  if (!match) { setStatus('无效的 BV 号', 'error'); return; }

  const bvid = match[0];
  setStatus(`正在分析 ${bvid}...`, 'loading');
  btnAnalyze.disabled = true;

  try {
    // 告诉 content script 开始分析
    const resp = await sendToContent({ action: 'analyze', bvid });
    if (resp && resp.ok) {
      setStatus(`分析完成！${resp.segments} 个片段`, 'ok');
    } else {
      setStatus(resp?.error || '分析失败', 'error');
    }
  } catch (e) {
    setStatus(`通信失败: ${e.message}`, 'error');
  } finally {
    btnAnalyze.disabled = false;
  }
});

// === 状态 ===
function setStatus(msg, type) {
  statusEl.textContent = msg;
  statusEl.style.color = type === 'error' ? '#ff6b6b' :
                         type === 'ok' ? '#51cf66' :
                         type === 'loading' ? '#ffd43b' : '#888';
}

// === 与 content script 通信 ===
async function sendToContent(msg) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url.includes('bilibili.com/video')) {
    setStatus('请在 B站视频页面使用', 'error');
    return null;
  }
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tab.id, msg, (response) => {
      resolve(response || { ok: false, error: '无响应' });
    });
  });
}

// === 监听来自 content script 的状态更新 ===
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === 'analysisProgress') {
    setStatus(msg.text, 'loading');
  } else if (msg.action === 'analysisDone') {
    setStatus(`完成: ${msg.segments}片段`, 'ok');
    btnAnalyze.disabled = false;
  }
});
