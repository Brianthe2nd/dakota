// background.js
let uploadPort = null;

chrome.runtime.onConnect.addListener((port) => {
  if (port.name === 'frame-uploader') {
    uploadPort = port;
    console.log('Content script connected (JPEG mode)');

    port.onMessage.addListener(async (message) => {
      if (message.type === 'UPLOAD_FRAME') {
        const { frameData, timestamp } = message.payload;
        
        try {
          const fetchResponse = await fetch(frameData);
          const blob = await fetchResponse.blob();
          
          const formData = new FormData();
          formData.append('video_chunk', blob, `frame_${timestamp}.jpg`);
          
          const res = await fetch('http://localhost:5000/upload-frame', {
            method: 'POST',
            body: formData,
            mode: 'cors',
          });
          
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
        } catch (err) {
          console.error('Upload failed:', err);
        }
      }
    });

    port.onDisconnect.addListener(() => {
      console.log('Content script disconnected');
      uploadPort = null;
    });
  }
});