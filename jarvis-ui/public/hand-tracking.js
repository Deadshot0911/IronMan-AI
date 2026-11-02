(function () {
  const smooth = {
    scale: 1,
    x: 0,
    y: 0,
    targetScale: 1,
    targetX: 0,
    targetY: 0,
  };
  const state = { minimized: Boolean(window.__jarvisMinimized), active: false, pinching: false };
  let video = null;
  let hands = null;
  let stream = null;
  let trackingTimer = 0;
  let sendingFrame = false;
  let lastVideoTime = -1;
  let calibratedHandSpan = 0;
  let spanSamples = [];
  let missingTwoHandsFrames = 0;
  let filteredHandSpan = 0;
  let lastReportedMessage = "";
  let scriptWaits = 0;

  function report(status, message) {
    if (message === lastReportedMessage) return;
    lastReportedMessage = message;
    window.dispatchEvent(new CustomEvent("jarvisVisionStatus", { detail: { status, message } }));
  }

  function resetGestures() {
    state.pinching = false;
    calibratedHandSpan = 0;
    spanSamples = [];
    missingTwoHandsFrames = 0;
    filteredHandSpan = 0;
    smooth.targetScale = 1;
    smooth.targetX = 0;
    smooth.targetY = 0;
    window.__handPinching = false;
    document.documentElement.style.setProperty("--hand-scale", "1");
    document.documentElement.style.setProperty("--hand-x", "0");
    document.documentElement.style.setProperty("--hand-y", "0");
  }

  function ensureVideo() {
    if (video) return video;
    video = document.createElement("video");
    video.id = "hand-preview";
    video.setAttribute("playsinline", "");
    video.muted = true;
    video.style.cssText = "position:fixed;width:1px;height:1px;left:-10px;top:-10px;opacity:0;pointer-events:none";
    document.body.appendChild(video);
    return video;
  }

  function stopCamera(message) {
    state.active = false;
    window.clearTimeout(trackingTimer);
    trackingTimer = 0;
    sendingFrame = false;
    resetGestures();

    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    if (video) video.srcObject = null;
    if (hands) {
      try {
        hands.close();
      } catch (error) {
        console.warn("[Jarvis Vision] Could not close hand tracking:", error);
      }
      hands = null;
    }
    report("OFF", message || "HAND TRACKING · MAXIMIZE TO ENABLE");
  }

  function onHandResults(results) {
    const landmarks = results.multiHandLandmarks || [];
    if (landmarks.length === 2) {
      const firstPalm = landmarks[0][9];
      const secondPalm = landmarks[1][9];
      const span = Math.hypot(firstPalm.x - secondPalm.x, firstPalm.y - secondPalm.y);
      missingTwoHandsFrames = 0;
      if (!calibratedHandSpan) {
        spanSamples.push(span);
        if (spanSamples.length >= 8) {
          calibratedHandSpan = spanSamples.reduce((sum, value) => sum + value, 0) / spanSamples.length;
          filteredHandSpan = calibratedHandSpan;
        }
      } else {
        filteredHandSpan += (span - filteredHandSpan) * 0.3;
        const zoomRatio = filteredHandSpan / Math.max(calibratedHandSpan, 0.08);
        smooth.targetScale = Math.max(0.5, Math.min(2.4, Math.pow(zoomRatio, 1.45)));
      }
    } else {
      spanSamples = [];
      missingTwoHandsFrames += 1;
      if (missingTwoHandsFrames > 45) {
        calibratedHandSpan = 0;
        filteredHandSpan = 0;
        smooth.targetScale = 1;
      }
    }

    let pinch = null;
    for (const hand of landmarks) {
      const thumb = hand[4];
      const index = hand[8];
      if (Math.hypot(thumb.x - index.x, thumb.y - index.y) < 0.075) {
        pinch = { x: (thumb.x + index.x) / 2, y: (thumb.y + index.y) / 2 };
        break;
      }
    }

    state.pinching = pinch !== null;
    window.__handPinching = state.pinching;
    if (pinch) {
      smooth.targetX = (0.5 - pinch.x) * 2;
      smooth.targetY = (pinch.y - 0.5) * 2;
      report("ACTIVE", "CAMERA ACTIVE · MOVE HANDS APART/TOGETHER TO ZOOM · PINCH TO MOVE");
    } else {
      smooth.targetX = 0;
      smooth.targetY = 0;
      report("ACTIVE", landmarks.length ? "CAMERA ACTIVE · MOVE HANDS APART/TOGETHER TO ZOOM · PINCH TO MOVE" : "CAMERA ACTIVE · SHOW YOUR HANDS");
    }
  }

  function updateSmoothMotion() {
    if (!state.active) return;
    smooth.scale += (smooth.targetScale - smooth.scale) * 0.18;
    smooth.x += (smooth.targetX - smooth.x) * 0.22;
    smooth.y += (smooth.targetY - smooth.y) * 0.22;

    document.documentElement.style.setProperty("--hand-scale", smooth.scale.toFixed(3));
    document.documentElement.style.setProperty("--hand-x", smooth.x.toFixed(3));
    document.documentElement.style.setProperty("--hand-y", smooth.y.toFixed(3));
    requestAnimationFrame(updateSmoothMotion);
  }

  async function trackFrames() {
    if (!state.active || !video || !hands) return;
    if (video.readyState >= 2 && video.currentTime !== lastVideoTime && !sendingFrame) {
      lastVideoTime = video.currentTime;
      sendingFrame = true;
      try {
        await hands.send({ image: video });
      } catch (error) {
        console.error("[Jarvis Vision] Hand tracking failed:", error);
        stopCamera("HAND TRACKING ERROR · REOPEN THE UI");
        return;
      } finally {
        sendingFrame = false;
      }
    }
    if (state.active) trackingTimer = window.setTimeout(trackFrames, 33);
  }

  function startCamera() {
    if (state.active || state.minimized || document.hidden) return;
    if (typeof window.Hands !== "function") {
      scriptWaits += 1;
      if (scriptWaits >= 24) {
        report("ERROR", "HAND TRACKING FAILED TO LOAD · CHECK INTERNET");
        return;
      }
      report("LOADING", "LOADING HAND TRACKING");
      window.setTimeout(startCamera, 500);
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      report("ERROR", "CAMERA ACCESS IS NOT AVAILABLE");
      return;
    }

    state.active = true;
    report("LOADING", "REQUESTING CAMERA ACCESS");
    navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30, max: 30 } },
    }).then(async (cameraStream) => {
      if (!state.active || state.minimized || document.hidden) {
        cameraStream.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = cameraStream;
      const cameraVideo = ensureVideo();
      cameraVideo.srcObject = stream;
      await cameraVideo.play();

      hands = new window.Hands({
        locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`,
      });
      hands.setOptions({
        maxNumHands: 2,
        modelComplexity: 0,
        minDetectionConfidence: 0.6,
        minTrackingConfidence: 0.55,
      });
      hands.onResults(onHandResults);
      resetGestures();
      report("ACTIVE", "CAMERA ACTIVE · MOVE HANDS APART/TOGETHER TO ZOOM · PINCH TO MOVE");
      requestAnimationFrame(updateSmoothMotion);
      void trackFrames();
    }).catch((error) => {
      console.warn("[Jarvis Vision] Camera access failed:", error);
      if (state.minimized || document.hidden) {
        state.active = false;
        return;
      }
      const message = error && error.name === "NotAllowedError"
        ? "CAMERA BLOCKED · ALLOW CAMERA ACCESS"
        : error && error.name === "NotFoundError"
        ? "NO CAMERA FOUND"
        : "CAMERA UNAVAILABLE · CHECK DEVICE PERMISSIONS";
      stopCamera(message);
    });
  }

  function updateWindowState(event) {
    const detail = event && event.detail;
    if (!detail || typeof detail.mini !== "boolean") return;
    state.minimized = detail.mini;
    if (state.minimized) stopCamera("HAND TRACKING · MAXIMIZE TO ENABLE");
    else startCamera();
  }

  window.addEventListener("jarvisState", updateWindowState);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stopCamera("HAND TRACKING · UI NOT VISIBLE");
    else if (!state.minimized) startCamera();
  });

  if (state.minimized) report("OFF", "HAND TRACKING · MAXIMIZE TO ENABLE");
  else startCamera();
})();
