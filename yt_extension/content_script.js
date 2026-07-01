// content_script.js
let liveRecorderActive = false;
let syncInterval = null;
let captureInterval = null;
let uploadPort = null;

function stopLiveAutomation() {
  if (syncInterval) clearInterval(syncInterval);
  if (captureInterval) clearInterval(captureInterval);
  if (uploadPort) uploadPort.disconnect();
  liveRecorderActive = false;
  console.log('Live automation stopped');
}

async function startLiveAutomation() {
  if (liveRecorderActive) return;

  const videoElem = document.querySelector('video');
  if (!videoElem) {
    alert('No video element found on this page.');
    return;
  }

  uploadPort = chrome.runtime.connect({ name: 'frame-uploader' });
  uploadPort.onDisconnect.addListener(stopLiveAutomation);

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');

  // Capture exactly 1 frame per second
  captureInterval = setInterval(() => {
    if (!videoElem.videoWidth || !videoElem.videoHeight) return;
    
    canvas.width = videoElem.videoWidth;
    canvas.height = videoElem.videoHeight;
    ctx.drawImage(videoElem, 0, 0, canvas.width, canvas.height);
    
    canvas.toBlob((blob) => {
      if (!blob || blob.size < 1000) return;
      
      const reader = new FileReader();
      reader.readAsDataURL(blob);
      reader.onloadend = () => {
        if (uploadPort) {
          uploadPort.postMessage({
            type: 'UPLOAD_FRAME',
            payload: {
              frameData: reader.result,
              timestamp: Date.now()
            }
          });
        }
      };
    }, 'image/jpeg', 0.8);
  }, 1000); 

  // Keep player synced to the live edge
  syncInterval = setInterval(() => {
    const liveButton = document.querySelector('.ytp-live-badge');
    if (liveButton && liveButton.getAttribute('aria-disabled') !== 'true') {
      liveButton.click();
    }
  }, 1000);

  liveRecorderActive = true;
  console.log('Canvas capture active: 1 frame per second.');
  
  window.addEventListener('beforeunload', () => {
    if (liveRecorderActive) stopLiveAutomation();
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === 'start') {
    startLiveAutomation();
    sendResponse({ success: true });
  } else if (message.action === 'stop') {
    stopLiveAutomation();
    sendResponse({ success: true });
  }
});