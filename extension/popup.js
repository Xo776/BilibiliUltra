// popup.js — API设置 + 功能开关

const $ = id => document.getElementById(id);

// === DOM 引用 ===
const groqKeyEl = $('groqKey');
const llmProviderEl = $('llmProvider');
const llmKeyEl = $('llmKey');
const llmBaseUrlEl = $('llmBaseUrl');
const llmModelEl = $('llmModel');
const btnSave = $('btnSave');
const savedMsg = $('savedMsg');
const statusEl = $('status');
const toggleAutoSkip = $('toggleAutoSkip');
const toggleHeatmap = $('toggleHeatmap');
const toggleTooltip = $('toggleTooltip');

// === 加载保存的配置 ===
chrome.storage.local.get([
  'groqKey', 'llmProvider', 'llmKey', 'llmBaseUrl', 'llmModel',
  'autoSkip', 'heatmap', 'tooltip',
], (data) => {
  if (data.groqKey) groqKeyEl.value = data.groqKey;
  if (data.llmProvider) llmProviderEl.value = data.llmProvider;
  if (data.llmKey) llmKeyEl.value = data.llmKey;
  llmBaseUrlEl.value = data.llmBaseUrl || 'https://api.deepseek.com';
  llmModelEl.value = data.llmModel || 'deepseek-v4-flash';

  toggleAutoSkip.checked = data.autoSkip !== false;
  toggleHeatmap.checked = data.heatmap !== false;
  toggleTooltip.checked = data.tooltip === true;

  updateStatus();
});

// === 保存 ===
btnSave.addEventListener('click', () => {
  const config = {
    groqKey: groqKeyEl.value.trim(),
    llmProvider: llmProviderEl.value,
    llmKey: llmKeyEl.value.trim(),
    llmBaseUrl: llmBaseUrlEl.value.trim() || 'https://api.deepseek.com',
    llmModel: llmModelEl.value.trim() || 'deepseek-chat',
  };
  chrome.storage.local.set(config, () => {
    savedMsg.style.display = 'block';
    setTimeout(() => { savedMsg.style.display = 'none'; }, 2000);
    updateStatus();
  });
});

// === 开关事件 → 保存 + 通知 content script ===
[toggleAutoSkip, toggleHeatmap, toggleTooltip].forEach(el => {
  el.addEventListener('change', () => {
    const settings = {
      autoSkip: toggleAutoSkip.checked,
      heatmap: toggleHeatmap.checked,
      tooltip: toggleTooltip.checked,
    };
    chrome.storage.local.set(settings);
    notifyContent({ action: 'configUpdate', config: settings });
  });
});

// === 从当前页获取 BV号 显示状态 ===
async function updateStatus() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const isBili = tab?.url?.includes('bilibili.com/video');
  const hasGroq = !!groqKeyEl.value.trim();
  const hasLlm = !!llmKeyEl.value.trim();

  if (!isBili) {
    statusEl.textContent = '请在 B站视频页面打开';
    statusEl.style.color = '#888';
  } else if (!hasGroq || !hasLlm) {
    statusEl.textContent = '⚠ 请先设置 API Key 并保存';
    statusEl.style.color = '#ffd43b';
  } else {
    const bvid = tab.url.match(/BV[a-zA-Z0-9]{10}/)?.[0] || '?';
    statusEl.textContent = `当前: ${bvid} | 已配置 ✓`;
    statusEl.style.color = '#51cf66';
  }
}

// === 与 content script 通信 ===
async function notifyContent(msg) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.url?.includes('bilibili.com/video')) {
    chrome.tabs.sendMessage(tab.id, msg);
  }
}
