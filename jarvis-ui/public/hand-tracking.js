(function () {
  const smooth = {
    scale: 1,
    x: 0,
    y: 0,
    targetScale: 1,
    targetX: 0,
    targetY: 0,
  };
  const state = {
    minimized: Boolean(window.__jarvisMinimized),
    authenticated: Boolean(window.__jarvisAuthenticated),
    active: false,
    pinching: false,
  };
  let video = null;
  let hands = null;
  let stream = null;
  let trackingTimer = 0;
  let motionFrame = 0;
  let lastMotionTime = 0;
  let sendingFrame = false;
  let lastVideoTime = -1;
  let calibratedHandSpan = 0;
  let spanSamples = [];
  let missingHandFrames = 0;
  let filteredHandSpan = 0;
  let zoomMode = "";
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
    missingHandFrames = 0;
    filteredHandSpan = 0;
    zoomMode = "";
    smooth.scale = 1;
    smooth.x = 0;
    smooth.y = 0;
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

  async function requestCamera() {
    const constraints = {
      audio: false,
      video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30, max: 30 } },
    };
    try {
      return await navigator.mediaDevices.getUserMedia(constraints);
    } catch (initialError) {
      if (!initialError || !["NotReadableError", "AbortError", "OverconstrainedError"].includes(initialError.name)) {
        throw initialError;
      }

      let devices;
      try {
        devices = await navigator.mediaDevices.enumerateDevices();
      } catch (enumerationError) {
        console.warn("[Jarvis Vision] Could not enumerate cameras:", enumerationError);
        throw initialError;
      }

      const cameras = devices.filter((device) => device.kind === "videoinput" && device.deviceId);
      for (const camera of cameras) {
        try {
          return await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: { deviceId: { exact: camera.deviceId } },
          });
        } catch (error) {
          console.warn(`[Jarvis Vision] Could not open camera ${camera.label || camera.deviceId}:`, error);
        }
      }
      throw initialError;
    }
  }

  function stopCamera(message) {
    state.active = false;
    window.clearTimeout(trackingTimer);
    trackingTimer = 0;
    if (motionFrame) {
      window.cancelAnimationFrame(motionFrame);
      motionFrame = 0;
      lastMotionTime = 0;
    }
    sendingFrame = false;
    resetGestures();

    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    if (video) video.srcObject = null;
    if (hands) {
      try {
        const closing = hands.close();
        if (closing && typeof closing.catch === "function") {
          closing.catch((error) => console.warn("[Jarvis Vision] Could not close hand tracking:", error));
        }
      } catch (error) {
        console.warn("[Jarvis Vision] Could not close hand tracking:", error);
      }
      hands = null;
    }
    report("OFF", message || "HAND TRACKING · MAXIMIZE TO ENABLE");
  }

  function onHandResults(results) {
    const landmarks = results.multiHandLandmarks || [];
    if (landmarks.length) {
      const mode = landmarks.length > 1 ? "two-hands" : "one-hand";
      const span = mode === "two-hands"
        ? Math.hypot(landmarks[0][9].x - landmarks[1][9].x, landmarks[0][9].y - landmarks[1][9].y)
        : Math.sqrt(
          Math.hypot(
            landmarks[0][0].x - landmarks[0][9].x,
            landmarks[0][0].y - landmarks[0][9].y,
            (landmarks[0][0].z - landmarks[0][9].z) * 0.65,
          ) *
          Math.hypot(
            landmarks[0][5].x - landmarks[0][17].x,
            landmarks[0][5].y - landmarks[0][17].y,
            (landmarks[0][5].z - landmarks[0][17].z) * 0.65,
          ),
        );
      if (mode !== zoomMode) {
        zoomMode = mode;
        spanSamples = [];
        calibratedHandSpan = 0;
        filteredHandSpan = 0;
        smooth.targetScale = 1;
      }
      missingHandFrames = 0;
      if (!calibratedHandSpan) {
        spanSamples.push(span);
        if (spanSamples.length >= 8) {
          const orderedSamples = [...spanSamples].sort((a, b) => a - b);
          calibratedHandSpan = (orderedSamples[3] + orderedSamples[4]) / 2;
          filteredHandSpan = calibratedHandSpan;
        }
      } else {
        filteredHandSpan += (span - filteredHandSpan) * 0.3;
        const zoomRatio = filteredHandSpan / Math.max(calibratedHandSpan, 0.08);
        smooth.targetScale = Math.max(0.45, Math.min(2.5, Math.pow(zoomRatio, 1.5)));
      }
    } else {
      missingHandFrames += 1;
      if (missingHandFrames > 45) {
        calibratedHandSpan = 0;
        spanSamples = [];
        filteredHandSpan = 0;
        zoomMode = "";
        smooth.targetScale = 1;
      }
    }

    let pinch = null;
    const pinchThreshold = state.pinching ? 0.085 : 0.065;
    for (const hand of landmarks) {
      const thumb = hand[4];
      const index = hand[8];
      if (Math.hypot(thumb.x - index.x, thumb.y - index.y) < pinchThreshold) {
        pinch = { x: (thumb.x + index.x) / 2, y: (thumb.y + index.y) / 2 };
        break;
      }
    }

    state.pinching = pinch !== null;
    window.__handPinching = state.pinching;
    if (pinch) {
      smooth.targetX = (0.5 - pinch.x) * 2;
      smooth.targetY = (pinch.y - 0.5) * 2;
      report("ACTIVE", "CAMERA ACTIVE · PINCH TO MOVE · MOVE HAND CLOSER/FARTHER OR BOTH HANDS APART TO ZOOM");
    } else {
      smooth.targetX = 0;
      smooth.targetY = 0;
      const gestureHelp = landmarks.length > 1
        ? "CAMERA ACTIVE · PINCH TO MOVE · MOVE HANDS APART/TOGETHER TO ZOOM"
        : "CAMERA ACTIVE · PINCH TO MOVE · MOVE ONE HAND CLOSER/FARTHER TO ZOOM";
      report("ACTIVE", landmarks.length ? gestureHelp : "CAMERA ACTIVE · SHOW YOUR HANDS");
    }
  }

  function updateSmoothMotion(timestamp) {
    if (!state.active) return;
    const delta = lastMotionTime ? Math.min((timestamp - lastMotionTime) / 1000, 0.1) : 1 / 60;
    lastMotionTime = timestamp;
    const scaleEase = 1 - Math.exp(-delta / 0.11);
    const positionEase = 1 - Math.exp(-delta / 0.075);
    smooth.scale += (smooth.targetScale - smooth.scale) * scaleEase;
    smooth.x += (smooth.targetX - smooth.x) * positionEase;
    smooth.y += (smooth.targetY - smooth.y) * positionEase;

    document.documentElement.style.setProperty("--hand-scale", smooth.scale.toFixed(3));
    document.documentElement.style.setProperty("--hand-x", smooth.x.toFixed(3));
    document.documentElement.style.setProperty("--hand-y", smooth.y.toFixed(3));
    motionFrame = window.requestAnimationFrame(updateSmoothMotion);
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
    if (state.active) trackingTimer = window.setTimeout(trackFrames, 24);
  }

  function startCamera() {
    if (state.active || !state.authenticated || state.minimized || document.hidden) return;
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
    requestCamera().then(async (cameraStream) => {
      if (!state.active || state.minimized || document.hidden) {
        cameraStream.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = cameraStream;
      const cameraVideo = ensureVideo();
      cameraVideo.srcObject = stream;
      await cameraVideo.play();

      hands = new window.Hands({
        locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands@0.4.1675469240/${file}`,
      });
      hands.setOptions({
        maxNumHands: 2,
        modelComplexity: 0,
        minDetectionConfidence: 0.6,
        minTrackingConfidence: 0.55,
      });
      hands.onResults(onHandResults);
      resetGestures();
      report("ACTIVE", "CAMERA ACTIVE · PINCH TO MOVE · MOVE HAND CLOSER/FARTHER OR BOTH HANDS APART TO ZOOM");
      if (!motionFrame) motionFrame = window.requestAnimationFrame(updateSmoothMotion);
      void trackFrames();
    }).catch((error) => {
      console.warn("[Jarvis Vision] Camera access failed:", error);
      if (state.minimized || document.hidden) {
        state.active = false;
        return;
      }
      const errorName = error && error.name;
      const message = errorName === "NotAllowedError" || errorName === "PermissionDeniedError"
        ? "CAMERA BLOCKED · ALLOW CAMERA ACCESS FOR JARVIS"
        : errorName === "NotFoundError" || errorName === "DevicesNotFoundError"
        ? "NO CAMERA FOUND · CONNECT A CAMERA"
        : errorName === "NotReadableError" || errorName === "AbortError"
        ? "CAMERA BUSY · CLOSE OTHER APPS USING THE CAMERA"
        : errorName === "OverconstrainedError"
        ? "CAMERA SETTINGS UNSUPPORTED · CHECK CAMERA DEVICE"
        : "CAMERA ERROR · " + (errorName || "UNKNOWN ERROR") + " · REOPEN THE UI";
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

  function updateAuthState(event) {
    const detail = event && event.detail;
    state.authenticated = Boolean(detail && detail.user && !detail.required && !detail.gender_required);
    if (state.authenticated) startCamera();
    else stopCamera("HAND TRACKING · SIGN IN TO ENABLE");
  }

  window.addEventListener("jarvisCameraPermissionReady", function () {
    if (!state.authenticated || state.minimized || document.hidden) return;
    if (state.active) stopCamera("RETRYING CAMERA ACCESS");
    startCamera();
  });
  window.addEventListener("jarvisAuth", updateAuthState);
  window.addEventListener("jarvisState", updateWindowState);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stopCamera("HAND TRACKING · UI NOT VISIBLE");
    else if (!state.minimized) startCamera();
  });

  if (!state.authenticated) report("OFF", "HAND TRACKING · SIGN IN TO ENABLE");
  else if (state.minimized) report("OFF", "HAND TRACKING · MAXIMIZE TO ENABLE");
  else startCamera();
})();
