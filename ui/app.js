const searchButton =
    document.getElementById("searchButton");

const requestInput =
    document.getElementById("request");

const quantityInput =
    document.getElementById("quantity");

const watermarkInput =
    document.getElementById("watermark");

const results =
    document.getElementById("results");

const status =
    document.getElementById("status");

const openTabButton =
    document.getElementById("openTabButton");


let shorts = [];

let downloadedFiles = {};

const BACKEND_URL = (window.location.protocol.startsWith("http") && window.location.port === "5000")
    ? ""
    : "http://127.0.0.1:5000";


// --------------------------------------------------
// UNIVERSAL WEBEXTENSION API (FIREFOX + CHROMIUM)
// --------------------------------------------------

const ext = (typeof browser !== "undefined" && browser.runtime) 
    ? browser 
    : (typeof chrome !== "undefined" && chrome.runtime ? chrome : null);

// --------------------------------------------------
// PERSISTENT STORAGE HELPER
// --------------------------------------------------

const storage = {
    async get(keys) {
        if (ext && ext.storage?.local) {
            return new Promise((resolve) => {
                try {
                    const req = ext.storage.local.get(keys);
                    if (req && typeof req.then === "function") {
                        req.then((res) => resolve(res || {})).catch(() => resolve({}));
                    } else {
                        ext.storage.local.get(keys, (res) => resolve(res || {}));
                    }
                } catch {
                    resolve({});
                }
            });
        }
        const result = {};
        const keyList = Array.isArray(keys) ? keys : [keys];
        for (const k of keyList) {
            const val = localStorage.getItem(`shortbot_${k}`);
            if (val !== null) {
                try {
                    result[k] = JSON.parse(val);
                } catch {
                    result[k] = val;
                }
            }
        }
        return result;
    },

    async set(items) {
        if (ext && ext.storage?.local) {
            return new Promise((resolve) => {
                try {
                    const req = ext.storage.local.set(items);
                    if (req && typeof req.then === "function") {
                        req.then(() => resolve()).catch(() => resolve());
                    } else {
                        ext.storage.local.set(items, () => resolve());
                    }
                } catch {
                    resolve();
                }
            });
        }
        for (const [k, v] of Object.entries(items)) {
            localStorage.setItem(`shortbot_${k}`, JSON.stringify(v));
        }
    },

    async remove(keys) {
        if (ext && ext.storage?.local) {
            return new Promise((resolve) => {
                try {
                    const req = ext.storage.local.remove(keys);
                    if (req && typeof req.then === "function") {
                        req.then(() => resolve()).catch(() => resolve());
                    } else {
                        ext.storage.local.remove(keys, () => resolve());
                    }
                } catch {
                    resolve();
                }
            });
        }
        const keyList = Array.isArray(keys) ? keys : [keys];
        for (const k of keyList) {
            localStorage.removeItem(`shortbot_${k}`);
        }
    }
};

async function sendNativeHostMessage(message) {
    if (!ext || !ext.runtime) return null;
    try {
        // Firefox browser.runtime.sendNativeMessage returns Promise
        if (typeof browser !== "undefined" && browser.runtime?.sendNativeMessage) {
            try {
                return await browser.runtime.sendNativeMessage("com.shortbot.backend", message);
            } catch (e) {
                console.warn("[ShortBot] Firefox native messaging error:", e);
                return null;
            }
        }
        // Chrome / Edge callback-based
        if (typeof chrome !== "undefined" && chrome.runtime?.sendNativeMessage) {
            return await new Promise((resolve) => {
                chrome.runtime.sendNativeMessage("com.shortbot.backend", message, (res) => {
                    if (chrome.runtime.lastError) {
                        console.warn("[ShortBot] Chrome native messaging error:", chrome.runtime.lastError.message);
                    }
                    resolve(res || null);
                });
            });
        }
    } catch (err) {
        console.warn("[ShortBot] sendNativeHostMessage exception:", err);
    }
    return null;
}


// --------------------------------------------------
// PROGRESS TRACKER HELPER
// --------------------------------------------------

class ProgressTracker {
    constructor({ container, fill, percent, stage, timer, detail }) {
        this.containerEl = typeof container === "string" ? document.getElementById(container) : container;
        this.fillEl = typeof fill === "string" ? document.getElementById(fill) : fill;
        this.percentEl = typeof percent === "string" ? document.getElementById(percent) : percent;
        this.stageEl = typeof stage === "string" ? document.getElementById(stage) : stage;
        this.timerEl = typeof timer === "string" ? document.getElementById(timer) : timer;
        this.detailEl = typeof detail === "string" ? document.getElementById(detail) : detail;

        this.intervalId = null;
        this.timerIntervalId = null;
        this.startTime = null;
    }

    start(initialStage = "Starting...", initialPercent = 5) {
        if (this.containerEl) {
            this.containerEl.style.display = "block";
            this.containerEl.classList.remove("error", "completed");
            this.containerEl.classList.add("active");
        }
        this.startTime = performance.now();
        this.update(initialPercent, initialStage, "Initializing...");

        clearInterval(this.timerIntervalId);
        this.timerIntervalId = setInterval(() => {
            const elapsedMs = performance.now() - this.startTime;
            const totalSec = Math.floor(elapsedMs / 1000);
            const mins = String(Math.floor(totalSec / 60)).padStart(2, "0");
            const secs = String(totalSec % 60).padStart(2, "0");
            if (this.timerEl) {
                this.timerEl.textContent = `⏱ ${mins}:${secs}`;
            }
        }, 500);
    }

    update(percent, stage, detail) {
        const clamped = Math.min(100, Math.max(0, Math.round(percent)));
        if (this.fillEl) this.fillEl.style.width = `${clamped}%`;
        if (this.percentEl) this.percentEl.textContent = `${clamped}%`;
        if (stage && this.stageEl) this.stageEl.textContent = stage;
        if (detail !== undefined && this.detailEl) this.detailEl.textContent = detail;
    }

    pollTask(taskId) {
        if (!taskId) return;
        clearInterval(this.intervalId);
        this.intervalId = setInterval(async () => {
            try {
                const ctrl = new AbortController();
                const to = setTimeout(() => ctrl.abort(), 1200);
                const res = await fetch(`${BACKEND_URL}/progress/${taskId}`, { signal: ctrl.signal });
                clearTimeout(to);
                if (res.ok) {
                    const data = await res.json();
                    if (data.success && data.progress) {
                        const p = data.progress;
                        this.update(p.percent, p.stage, p.detail);
                        if (p.status === "completed") {
                            this.complete(p.stage || "Complete! ✓");
                        } else if (p.status === "error") {
                            this.fail(p.detail || "Operation failed");
                        }
                    }
                }
            } catch {
                // Ignore transient network hiccups
            }
        }, 350);
    }

    complete(finalMessage = "Complete! ✓") {
        clearInterval(this.intervalId);
        clearInterval(this.timerIntervalId);
        this.update(100, finalMessage, "Finished successfully.");
        if (this.containerEl) {
            this.containerEl.classList.remove("active");
            this.containerEl.classList.add("completed");
        }
    }

    fail(errorMessage = "Failed") {
        clearInterval(this.intervalId);
        clearInterval(this.timerIntervalId);
        if (this.stageEl) this.stageEl.textContent = "Failed";
        if (this.detailEl) this.detailEl.textContent = errorMessage;
        if (this.containerEl) {
            this.containerEl.classList.remove("active");
            this.containerEl.classList.add("error");
        }
    }

    hide(delayMs = 4000) {
        clearInterval(this.intervalId);
        clearInterval(this.timerIntervalId);
        if (delayMs > 0) {
            setTimeout(() => {
                if (this.containerEl) this.containerEl.style.display = "none";
            }, delayMs);
        } else {
            if (this.containerEl) this.containerEl.style.display = "none";
        }
    }
}


// --------------------------------------------------
// SAVE & RESTORE STATE
// --------------------------------------------------

async function saveAppState() {
    try {
        const watermarkCheckbox = document.getElementById("activeWatermarkCheckbox");
        await storage.set({
            savedRequest: requestInput.value,
            savedQuantity: quantityInput.value,
            savedWatermark: watermarkInput.value,
            savedActiveWatermarkCheckbox: watermarkCheckbox ? watermarkCheckbox.checked : false,
            savedShorts: shorts,
            savedStatusText: status.textContent
        });
    } catch (e) {
        console.warn("Could not save state:", e);
    }
}

async function restoreAppState() {
    try {
        const data = await storage.get([
            "savedRequest",
            "savedQuantity",
            "savedWatermark",
            "savedActiveWatermarkCheckbox",
            "savedShorts",
            "savedStatusText"
        ]);

        if (data.savedRequest && !requestInput.value) {
            requestInput.value = data.savedRequest;
        }
        if (data.savedQuantity) {
            quantityInput.value = data.savedQuantity;
        }
        if (data.savedWatermark && !watermarkInput.value) {
            watermarkInput.value = data.savedWatermark;
        }
        const watermarkCheckbox = document.getElementById("activeWatermarkCheckbox");
        if (watermarkCheckbox && data.savedActiveWatermarkCheckbox !== undefined) {
            watermarkCheckbox.checked = Boolean(data.savedActiveWatermarkCheckbox);
        }

        if (Array.isArray(data.savedShorts) && data.savedShorts.length > 0) {
            if (data.savedStatusText) {
                status.textContent = data.savedStatusText;
            } else {
                status.textContent = `Found ${data.savedShorts.length} relevant Shorts.`;
            }
            renderShorts(data.savedShorts);
        }
    } catch (e) {
        console.warn("Could not restore state:", e);
    }
}

function clearResults() {
    shorts = [];
    downloadedFiles = {};
    document.querySelectorAll(".short-card").forEach((card) => card.remove());
    const oldControls = document.getElementById("selectionControls");
    if (oldControls) {
        oldControls.remove();
    }
    status.textContent = 'Enter a request and click "Find Shorts".';
    storage.remove(["savedShorts", "savedStatusText"]);
}



// --------------------------------------------------
// BACKEND HEALTH & AUTO-START
// --------------------------------------------------

async function checkAndAutoStartBackend() {
    const badge = document.getElementById("serverBadge");
    const badgeText = document.getElementById("serverBadgeText");
    if (!badge || !badgeText) return;

    async function ping() {
        try {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 2500);
            const res = await fetch(`${BACKEND_URL}/health`, { signal: controller.signal });
            clearTimeout(timer);
            return res.ok;
        } catch {
            return false;
        }
    }

    const notice = document.getElementById("engineNotice");
    const btnRetry = document.getElementById("btnRetryEngine");
    if (btnRetry) {
        btnRetry.onclick = () => {
            badge.className = "server-badge checking";
            badgeText.textContent = "Checking...";
            checkAndAutoStartBackend();
        };
    }

    let ok = await ping();
    if (ok) {
        badge.className = "server-badge online";
        badgeText.textContent = "Backend Online";
        if (notice) notice.style.display = "none";
        refreshDownloadedFiles();
        return true;
    }

    // Try starting via native messaging if available
    badge.className = "server-badge starting";
    badgeText.textContent = "Starting Backend...";

    const res = await sendNativeHostMessage({ action: "start" });
    if (res) {
        // Poll for up to 6 seconds
        for (let i = 0; i < 6; i++) {
            await new Promise((r) => setTimeout(r, 1000));
            if (await ping()) {
                badge.className = "server-badge online";
                badgeText.textContent = "Backend Online";
                if (notice) notice.style.display = "none";
                refreshDownloadedFiles();
                return true;
            }
        }
    }

    badge.className = "server-badge offline";
    badgeText.textContent = "Backend Offline (Click to Retry)";
    if (notice) notice.style.display = "block";
    badge.onclick = () => {
        badge.className = "server-badge checking";
        badgeText.textContent = "Checking...";
        checkAndAutoStartBackend();
    };
    return false;
}


// --------------------------------------------------
// ACTIVE YOUTUBE TAB DETECTION & DIRECT DOWNLOAD
// --------------------------------------------------

function extractCleanYouTubeUrl(rawUrl) {
    if (!rawUrl) return null;
    try {
        const parsed = new URL(rawUrl);
        const host = parsed.hostname.toLowerCase();
        
        if (host.includes("youtube.com")) {
            if (parsed.pathname === "/watch" && parsed.searchParams.has("v")) {
                return `https://www.youtube.com/watch?v=${parsed.searchParams.get("v")}`;
            }
            if (parsed.pathname.startsWith("/shorts/")) {
                const parts = parsed.pathname.split("/").filter(Boolean);
                if (parts.length >= 2) {
                    return `https://www.youtube.com/shorts/${parts[1]}`;
                }
            }
            if (parsed.pathname.startsWith("/live/")) {
                const parts = parsed.pathname.split("/").filter(Boolean);
                if (parts.length >= 2) {
                    return `https://www.youtube.com/watch?v=${parts[1]}`;
                }
            }
        } else if (host === "youtu.be") {
            const videoId = parsed.pathname.replace(/^\//, "");
            if (videoId) {
                return `https://www.youtube.com/watch?v=${videoId}`;
            }
        }
    } catch {
        // Fallback to raw URL
    }
    return rawUrl;
}

async function checkActiveYouTubeTab() {
    if (!ext || !ext.tabs?.query) {
        return;
    }

    try {
        let tabs = [];
        const queryPromise = ext.tabs.query({ active: true, currentWindow: true });
        if (queryPromise && typeof queryPromise.then === "function") {
            tabs = await queryPromise;
        } else {
            tabs = await new Promise((resolve) => ext.tabs.query({ active: true, currentWindow: true }, resolve));
        }
        const tab = tabs && tabs[0];
        if (!tab || !tab.url) return;

        const isYouTube = tab.url.includes("youtube.com/watch") || 
                          tab.url.includes("youtube.com/shorts/") ||
                          tab.url.includes("youtu.be/") ||
                          tab.url.includes("youtube.com/live/");
        if (!isYouTube) return;

        const card = document.getElementById("activeVideoCard");
        const titleEl = document.getElementById("activeVideoTitle");
        const btn = document.getElementById("downloadActiveButton");
        const statusEl = document.getElementById("activeVideoStatus");
        const watermarkCheckbox = document.getElementById("activeWatermarkCheckbox");
        const watermarkLabel = document.getElementById("activeWatermarkLabel");

        if (!card || !titleEl || !btn || !statusEl) return;

        function updateWatermarkCheckboxUI() {
            if (!watermarkCheckbox) return;
            const currentWm = getWatermark();
            if (currentWm) {
                watermarkCheckbox.title = watermarkCheckbox.checked 
                    ? `Watermark "${currentWm}" will be added to this video` 
                    : `Check to add watermark "${currentWm}" to this video`;
                if (watermarkLabel) {
                    const displayWm = currentWm.length > 14 ? currentWm.slice(0, 12) + "…" : currentWm;
                    watermarkLabel.textContent = `Watermark (${displayWm})`;
                }
            } else {
                watermarkCheckbox.title = "Add watermark (set watermark handle in the field below)";
                if (watermarkLabel) {
                    watermarkLabel.textContent = "Add watermark";
                }
            }
        }

        if (watermarkCheckbox) {
            storage.get(["savedActiveWatermarkCheckbox"]).then((data) => {
                if (data.savedActiveWatermarkCheckbox !== undefined) {
                    watermarkCheckbox.checked = Boolean(data.savedActiveWatermarkCheckbox);
                } else {
                    watermarkCheckbox.checked = Boolean(getWatermark());
                }
                updateWatermarkCheckboxUI();
            });

            watermarkCheckbox.onchange = () => {
                storage.set({ savedActiveWatermarkCheckbox: watermarkCheckbox.checked });
                updateWatermarkCheckboxUI();
            };
        }

        if (watermarkInput) {
            watermarkInput.addEventListener("input", updateWatermarkCheckboxUI);
        }

        const cleanTitle = (tab.title || "YouTube Video")
            .replace(/ - YouTube$/, "")
            .replace(/\(\d+\)\s*/, "")
            .trim();

        const targetUrl = extractCleanYouTubeUrl(tab.url) || tab.url;

        titleEl.textContent = cleanTitle;
        card.style.display = "block";

        const activeProgress = new ProgressTracker({
            container: "activeProgressContainer",
            fill: "activeProgressFill",
            percent: "activeProgressPercent",
            stage: "activeProgressStage",
            timer: "activeProgressTimer",
            detail: "activeProgressDetail"
        });

        btn.onclick = async () => {
            btn.disabled = true;
            btn.textContent = "CHECKING BACKEND...";
            statusEl.textContent = "Connecting to ShortBot backend...";
            statusEl.className = "active-video-status pending";

            const taskId = "active_dl_" + Date.now();
            activeProgress.start("Connecting to backend...", 5);

            try {
                // Step 1: Verify backend is reachable, auto-start if needed
                let isAlive = false;
                try {
                    const pingCtrl = new AbortController();
                    const pingTimer = setTimeout(() => pingCtrl.abort(), 1800);
                    const pingRes = await fetch(`${BACKEND_URL}/health`, { signal: pingCtrl.signal });
                    clearTimeout(pingTimer);
                    isAlive = pingRes.ok;
                } catch {
                    isAlive = false;
                }

                if (!isAlive) {
                    btn.textContent = "STARTING SERVER...";
                    statusEl.textContent = "Backend offline. Launching ShortBot backend...";
                    activeProgress.update(10, "Starting backend...", "Launching backend daemon...");
                    isAlive = await checkAndAutoStartBackend();
                }

                if (!isAlive) {
                    btn.disabled = false;
                    btn.textContent = "⬇ DOWNLOAD THIS VIDEO";
                    statusEl.innerHTML = 'ShortBot backend is offline. Run <code style="background:rgba(255,255,255,0.15);padding:1px 4px;border-radius:3px;font-family:monospace;">python backend.py</code> in terminal, or click the status badge above to retry.';
                    statusEl.className = "active-video-status error";
                    activeProgress.fail("ShortBot backend is offline");
                    return;
                }

                // Step 2: Request download with real-time progress tracking
                btn.textContent = "DOWNLOADING...";
                statusEl.textContent = "Downloading & processing video with yt-dlp...";
                statusEl.className = "active-video-status pending";

                const applyWm = watermarkCheckbox ? watermarkCheckbox.checked : false;
                const watermark = applyWm ? getWatermark() : "";

                const detailMsg = watermark 
                    ? `Downloading with watermark '${watermark}'...` 
                    : "Connecting to YouTube stream...";
                activeProgress.update(15, "Starting download...", detailMsg);
                activeProgress.pollTask(taskId);

                let res;
                try {
                    res = await fetch(`${BACKEND_URL}/download`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            url: targetUrl,
                            watermark: watermark,
                            server_only: false,
                            task_id: taskId
                        })
                    });
                } catch (fetchErr) {
                    throw new Error("Could not connect to backend server at 127.0.0.1:5000. Is backend.py running?");
                }

                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.details || err.error || `Download failed with HTTP ${res.status}`);
                }

                activeProgress.update(98, "Saving file...", "Receiving media stream...");
                const blob = await res.blob();
                const blobUrl = URL.createObjectURL(blob);
                const safeName = (cleanTitle.replace(/[^a-zA-Z0-9_\-\s]/g, "").trim().slice(0, 40) || "youtube_video") + ".mp4";

                // Step 3: Trigger download via ext.downloads or anchor click
                if (ext && ext.downloads?.download) {
                    try {
                        ext.downloads.download({
                            url: blobUrl,
                            filename: safeName,
                            saveAs: false
                        }, (downloadId) => {
                            if (ext.runtime?.lastError) {
                                console.warn("downloads error, falling back to <a>:", ext.runtime.lastError.message);
                                triggerAnchorDownload(blobUrl, safeName);
                            }
                        });
                    } catch {
                        triggerAnchorDownload(blobUrl, safeName);
                    }
                } else {
                    triggerAnchorDownload(blobUrl, safeName);
                }

                const finishMsg = watermark
                    ? "Downloaded & watermarked successfully! ✓"
                    : "Downloaded successfully! ✓";
                activeProgress.complete(finishMsg);
                activeProgress.hide(6000);

                btn.disabled = false;
                btn.textContent = watermark ? "SAVED (WATERMARKED) ✓" : "DOWNLOADED ✓";
                statusEl.textContent = `Saved: ${safeName}` + (watermark ? ` (watermark: "${watermark}")` : "");
                statusEl.className = "active-video-status success";
                if (typeof refreshDownloadedFiles === "function") {
                    refreshDownloadedFiles();
                }
            } catch (err) {
                console.error("Active download error:", err);
                activeProgress.fail(err.message);
                btn.disabled = false;
                btn.textContent = "⬇ DOWNLOAD THIS VIDEO";
                statusEl.textContent = "Download failed: " + err.message;
                statusEl.className = "active-video-status error";
            }
        };
    } catch (e) {
        console.log("Could not check active tab:", e);
    }
}

function triggerAnchorDownload(url, filename) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
}

// --------------------------------------------------
// DIRECT YOUTUBE VIDEO / SHORTS DOWNLOAD HANDLER
// --------------------------------------------------

function setupDirectDownloadSection() {
    const directInput = document.getElementById("directUrlInput");
    const directBtn = document.getElementById("directDownloadButton");
    const watermarkCheckbox = document.getElementById("directWatermarkCheckbox");
    const watermarkLabel = document.getElementById("directWatermarkLabel");
    const statusEl = document.getElementById("directVideoStatus");

    if (!directInput || !directBtn || !statusEl) return;

    function updateWatermarkCheckboxUI() {
        if (!watermarkCheckbox) return;
        const currentWm = getWatermark();
        if (currentWm) {
            watermarkCheckbox.title = watermarkCheckbox.checked 
                ? `Watermark "${currentWm}" will be added to this video` 
                : `Check to add watermark "${currentWm}" to this video`;
            if (watermarkLabel) {
                const displayWm = currentWm.length > 14 ? currentWm.slice(0, 12) + "…" : currentWm;
                watermarkLabel.textContent = `Watermark (${displayWm})`;
            }
        } else {
            watermarkCheckbox.title = "Add watermark (set watermark handle in the field below)";
            if (watermarkLabel) {
                watermarkLabel.textContent = "Add watermark";
            }
        }
    }

    if (watermarkCheckbox) {
        storage.get(["savedDirectWatermarkCheckbox"]).then((data) => {
            if (data.savedDirectWatermarkCheckbox !== undefined) {
                watermarkCheckbox.checked = Boolean(data.savedDirectWatermarkCheckbox);
            } else {
                watermarkCheckbox.checked = Boolean(getWatermark());
            }
            updateWatermarkCheckboxUI();
        });

        watermarkCheckbox.onchange = () => {
            storage.set({ savedDirectWatermarkCheckbox: watermarkCheckbox.checked });
            updateWatermarkCheckboxUI();
        };
    }

    if (watermarkInput) {
        watermarkInput.addEventListener("input", updateWatermarkCheckboxUI);
    }

    const directProgress = new ProgressTracker({
        container: "directProgressContainer",
        fill: "directProgressFill",
        percent: "directProgressPercent",
        stage: "directProgressStage",
        timer: "directProgressTimer",
        detail: "directProgressDetail"
    });

    async function handleDirectDownload() {
        const rawUrl = directInput.value.trim();
        if (!rawUrl) {
            statusEl.textContent = "Please enter or paste a YouTube video or Shorts link.";
            statusEl.className = "direct-video-status error";
            directInput.focus();
            return;
        }

        const isYouTube = rawUrl.includes("youtube.com") || rawUrl.includes("youtu.be");
        if (!isYouTube) {
            statusEl.textContent = "Please enter a valid YouTube or Shorts URL (e.g. https://www.youtube.com/shorts/...).";
            statusEl.className = "direct-video-status error";
            return;
        }

        const cleanUrl = extractCleanYouTubeUrl(rawUrl) || rawUrl;
        const taskId = "direct_dl_" + Date.now();

        directBtn.disabled = true;
        directBtn.textContent = "CHECKING BACKEND...";
        statusEl.textContent = "Connecting to ShortBot backend...";
        statusEl.className = "direct-video-status pending";

        directProgress.start("Connecting to backend...", 5);

        try {
            // Step 1: Verify backend is reachable, auto-start if needed
            let isAlive = false;
            try {
                const pingCtrl = new AbortController();
                const pingTimer = setTimeout(() => pingCtrl.abort(), 1800);
                const pingRes = await fetch(`${BACKEND_URL}/health`, { signal: pingCtrl.signal });
                clearTimeout(pingTimer);
                isAlive = pingRes.ok;
            } catch {
                isAlive = false;
            }

            if (!isAlive) {
                directBtn.textContent = "STARTING SERVER...";
                statusEl.textContent = "Backend offline. Launching ShortBot backend...";
                directProgress.update(10, "Starting backend...", "Launching backend daemon...");
                isAlive = await checkAndAutoStartBackend();
            }

            if (!isAlive) {
                directBtn.disabled = false;
                directBtn.textContent = "⬇ DOWNLOAD";
                statusEl.innerHTML = 'ShortBot backend is offline. Run <code style="background:rgba(255,255,255,0.15);padding:1px 4px;border-radius:3px;font-family:monospace;">python backend.py</code> in terminal, or click the status badge above to retry.';
                statusEl.className = "direct-video-status error";
                directProgress.fail("ShortBot backend is offline");
                return;
            }

            // Step 2: Request download with real-time progress tracking
            directBtn.textContent = "DOWNLOADING...";
            statusEl.textContent = "Downloading & processing video with yt-dlp...";
            statusEl.className = "direct-video-status pending";

            const applyWm = watermarkCheckbox ? watermarkCheckbox.checked : false;
            const watermark = applyWm ? getWatermark() : "";

            const detailMsg = watermark 
                ? `Downloading with watermark '${watermark}'...` 
                : "Connecting to YouTube stream...";
            directProgress.update(15, "Starting download...", detailMsg);
            directProgress.pollTask(taskId);

            let res;
            try {
                res = await fetch(`${BACKEND_URL}/download`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        url: cleanUrl,
                        watermark: watermark,
                        server_only: false,
                        task_id: taskId
                    })
                });
            } catch (fetchErr) {
                throw new Error("Could not connect to backend server at 127.0.0.1:5000. Is backend running?");
            }

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.details || err.error || `Download failed with HTTP ${res.status}`);
            }

            directProgress.update(98, "Saving file...", "Receiving media stream...");
            const blob = await res.blob();
            const blobUrl = URL.createObjectURL(blob);
            
            // Extract a filename hint
            let safeName = "youtube_video.mp4";
            try {
                const urlObj = new URL(cleanUrl);
                const vidId = urlObj.searchParams.get("v") || urlObj.pathname.split("/").filter(Boolean).pop();
                if (vidId) safeName = `short_${vidId}.mp4`;
            } catch {}

            // Trigger download via ext.downloads or anchor click
            if (ext && ext.downloads?.download) {
                try {
                    ext.downloads.download({
                        url: blobUrl,
                        filename: safeName,
                        saveAs: false
                    }, (downloadId) => {
                        if (ext.runtime?.lastError) {
                            triggerAnchorDownload(blobUrl, safeName);
                        }
                    });
                } catch {
                    triggerAnchorDownload(blobUrl, safeName);
                }
            } else {
                triggerAnchorDownload(blobUrl, safeName);
            }

            const finishMsg = watermark
                ? "Downloaded & watermarked successfully! ✓"
                : "Downloaded successfully! ✓";
            directProgress.complete(finishMsg);
            directProgress.hide(6000);

            directBtn.disabled = false;
            directBtn.textContent = watermark ? "SAVED (WATERMARKED) ✓" : "DOWNLOADED ✓";
            statusEl.textContent = `Saved: ${safeName}` + (watermark ? ` (watermark: "${watermark}")` : "");
            statusEl.className = "direct-video-status success";
            if (typeof refreshDownloadedFiles === "function") {
                refreshDownloadedFiles();
            }
        } catch (err) {
            console.error("Direct download error:", err);
            directProgress.fail(err.message);
            directBtn.disabled = false;
            directBtn.textContent = "⬇ DOWNLOAD";
            statusEl.textContent = "Download failed: " + err.message;
            statusEl.className = "direct-video-status error";
        }
    }

    directBtn.onclick = handleDirectDownload;
    directInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            handleDirectDownload();
        }
    });
}



// --------------------------------------------------
// GET WATERMARK
// --------------------------------------------------

function getWatermark() {

    return watermarkInput.value.trim();

}


// --------------------------------------------------
// GET SELECTED SHORTS
// --------------------------------------------------

function getSelectedShorts() {

    return shorts.filter(
        function (short) {

            const checkbox =
                document.getElementById(
                    `short-checkbox-${short.index}`
                );

            return (
                checkbox &&
                checkbox.checked
            );

        }
    );

}


// --------------------------------------------------
// UPDATE SELECTION CONTROLS
// --------------------------------------------------

function updateSelectionControls() {

    const selectedShorts =
        getSelectedShorts();

    const count =
        selectedShorts.length;

    const selectionInfo =
        document.getElementById(
            "selectionInfo"
        );

    const downloadSelectedButton =
        document.getElementById(
            "downloadSelectedButton"
        );

    const compileSelectedButton =
        document.getElementById(
            "compileSelectedButton"
        );

    if (selectionInfo) {

        selectionInfo.textContent =
            `${count} selected`;

    }

    if (downloadSelectedButton) {

        downloadSelectedButton.disabled =
            count < 1;

    }

    if (compileSelectedButton) {

        compileSelectedButton.disabled =
            count < 2;

    }

}


// --------------------------------------------------
// REFRESH DOWNLOADED FILES
// --------------------------------------------------

async function refreshDownloadedFiles() {

    try {

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 4000);

        const response =
            await fetch(`${BACKEND_URL}/downloads`, {
                signal: controller.signal
            });

        clearTimeout(timeoutId);

        const data =
            await response.json();

        if (
            response.ok &&
            data.success
        ) {

            downloadedFiles = {};

            (data.files || []).forEach(
                function (filename) {

                    downloadedFiles[filename] =
                        true;

                }
            );

            updateDownloadedButtons();

        }

    }

    catch (error) {

        console.warn(
            "Could not refresh downloaded files:",
            error
        );

    }

}


// --------------------------------------------------
// UPDATE DOWNLOADED BUTTONS
// --------------------------------------------------

function updateDownloadedButtons() {

    shorts.forEach(
        function (short) {

            const button =
                document.getElementById(
                    `download-button-${short.index}`
                );

            if (!button) {
                return;
            }

            if (
                short.downloadedFilename &&
                downloadedFiles[
                    short.downloadedFilename
                ]
            ) {

                button.textContent =
                    "DOWNLOADED ✓";

                button.dataset.downloaded =
                    "true";

            }

        }
    );

}


// --------------------------------------------------
// DOWNLOAD ONE SHORT
// --------------------------------------------------

async function downloadShort(
    short,
    button,
    serverOnly = false
) {

    button.disabled =
        true;

    button.textContent =
        "DOWNLOADING...";

    let cardTracker = null;
    const progressEl = document.getElementById(`short-progress-${short.index}`);
    const taskId = `dl_short_${short.index}_${Date.now()}`;

    if (progressEl) {
        cardTracker = new ProgressTracker({
            container: `short-progress-${short.index}`,
            fill: `short-progress-fill-${short.index}`,
            percent: `short-progress-percent-${short.index}`,
            stage: `short-progress-stage-${short.index}`,
            timer: `short-progress-timer-${short.index}`,
            detail: `short-progress-detail-${short.index}`
        });
        cardTracker.start("Connecting to YouTube...", 5);
        cardTracker.pollTask(taskId);
    }

    try {

        const watermark =
            getWatermark();

        const response =
            await fetch(
                `${BACKEND_URL}/download`,
                {

                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        url:
                            short.url,

                        watermark:
                            watermark,

                        server_only:
                            serverOnly,

                        task_id:
                            taskId

                    })

                }
            );

        if (!response.ok) {

            let errorMessage =
                "Download failed.";

            try {

                const errorData =
                    await response.json();

                errorMessage =
                    errorData.error ||
                    errorData.details ||
                    errorMessage;

            }

            catch (error) {
                // Ignore JSON parsing errors.
            }

            throw new Error(
                errorMessage
            );

        }

        let filename = null;

        if (serverOnly) {
            const data = await response.json();
            filename = data.filename;
        } else {
            const disposition =
                response.headers.get(
                    "Content-Disposition"
                );

            if (disposition) {
                const match =
                    disposition.match(
                        /filename="?([^"]+)"?/i
                    );
                if (match) {
                    filename = match[1];
                }
            }

            const xFilename = response.headers.get("X-Filename");
            if (xFilename) {
                filename = xFilename;
            }

            if (!filename) {
                const urlMatch = (short.url || "").match(/(?:shorts\/|v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
                if (urlMatch) {
                    filename = `short_${urlMatch[1]}.mp4`;
                }
            }

            const saveFilename = filename || "short.mp4";
            const blob = await response.blob();
            const blobUrl = window.URL.createObjectURL(blob);

            if (ext && ext.downloads?.download) {
                try {
                    const dlPromise = ext.downloads.download({
                        url: blobUrl,
                        filename: saveFilename,
                        saveAs: false
                    }, (downloadId) => {
                        if (ext.runtime?.lastError) {
                            triggerAnchorDownload(blobUrl, saveFilename);
                        }
                    });
                    if (dlPromise && typeof dlPromise.catch === "function") {
                        dlPromise.catch(() => {
                            triggerAnchorDownload(blobUrl, saveFilename);
                        });
                    }
                } catch {
                    triggerAnchorDownload(blobUrl, saveFilename);
                }
            } else {
                triggerAnchorDownload(blobUrl, saveFilename);
            }
        }

        if (filename) {

            short.downloadedFilename =
                filename;

            downloadedFiles[filename] = true;

        }

        short.downloadedWithWatermark =
            watermark;

        button.textContent =
            "DOWNLOADED ✓";

        button.dataset.downloaded =
            "true";

        if (cardTracker) {
            cardTracker.complete("Downloaded ✓");
            cardTracker.hide(5000);
        }

        return {
            success: true,
            filename: filename
        };

    }

    catch (error) {

        console.error(
            "Download error:",
            error
        );

        button.textContent =
            "DOWNLOAD FAILED";

        if (cardTracker) {
            cardTracker.fail(error.message);
        }

        throw error;

    }

    finally {

        button.disabled =
            false;

    }

}


// --------------------------------------------------
// DOWNLOAD SELECTED IN PARALLEL
// --------------------------------------------------

async function downloadSelected() {

    const selectedShorts =
        getSelectedShorts();

    if (selectedShorts.length < 1) {

        alert(
            "Select at least one Short first."
        );

        return;

    }

    const button =
        document.getElementById(
            "downloadSelectedButton"
        );

    button.disabled =
        true;

    button.textContent =
        "DOWNLOADING...";

    const startTime =
        performance.now();

    const watermark =
        getWatermark();

    const batchTracker = new ProgressTracker({
        container: "selectionProgressContainer",
        fill: "selectionProgressFill",
        percent: "selectionProgressPercent",
        stage: "selectionProgressStage",
        timer: "selectionProgressTimer",
        detail: "selectionProgressDetail"
    });

    try {

        const shortsToDownload =
            selectedShorts.filter(
                function (short) {

                    return !(
                        short.downloadedFilename &&
                        downloadedFiles[
                            short.downloadedFilename
                        ]
                    );

                }
            );

        const alreadyDownloaded =
            selectedShorts.length -
            shortsToDownload.length;

        if (
            shortsToDownload.length === 0
        ) {

            status.textContent =
                "All selected Shorts are already downloaded. ✓";

            batchTracker.complete("All selected Shorts already downloaded! ✓");
            batchTracker.hide(4000);

            return;

        }

        batchTracker.start(`Downloading ${shortsToDownload.length} selected Shorts...`, 5);

        /*
         * Run up to 3 downloads at once.
         *
         * This is much faster than downloading
         * every Short one-by-one.
         */

        const MAX_CONCURRENT =
            3;

        let nextIndex =
            0;

        let completed =
            alreadyDownloaded;

        let failed =
            0;

        async function worker() {

            while (true) {

                const currentIndex =
                    nextIndex++;

                if (
                    currentIndex >=
                    shortsToDownload.length
                ) {

                    return;

                }

                const short =
                    shortsToDownload[
                        currentIndex
                    ];

                const individualButton =
                    document.getElementById(
                        `download-button-${short.index}`
                    );

                const currentPct = Math.round((completed / selectedShorts.length) * 100);
                batchTracker.update(
                    Math.max(5, currentPct),
                    `Downloading Shorts (${completed + 1}/${selectedShorts.length})...`,
                    short.title.slice(0, 35) + "..."
                );

                status.textContent =
                    `Downloading Shorts... ${completed + 1}/${selectedShorts.length}`;

                try {

                    if (individualButton) {

                        await downloadShort(
                            short,
                            individualButton
                        );

                    }

                }

                catch (error) {

                    failed++;

                    console.error(
                        "Selected download failed:",
                        short.title,
                        error
                    );

                }

                completed++;

                const finishPct = Math.round((completed / selectedShorts.length) * 100);
                batchTracker.update(
                    finishPct,
                    `Downloading Shorts... (${completed}/${selectedShorts.length})`,
                    `Finished: ${short.title.slice(0, 30)}`
                );

                status.textContent =
                    `Downloading Shorts... ${Math.min(
                        completed,
                        selectedShorts.length
                    )}/${selectedShorts.length}`;

            }

        }

        const workerCount =
            Math.min(
                MAX_CONCURRENT,
                shortsToDownload.length
            );

        const workers = [];

        for (
            let i = 0;
            i < workerCount;
            i++
        ) {

            workers.push(
                worker()
            );

        }

        await Promise.all(
            workers
        );

        await refreshDownloadedFiles();

        const elapsedSeconds =
            (
                performance.now() -
                startTime
            ) / 1000;

        if (failed > 0) {

            status.textContent =
                `Downloaded selected Shorts in ${elapsedSeconds.toFixed(
                    1
                )}s. ${failed} failed.`;

            batchTracker.fail(`Done in ${elapsedSeconds.toFixed(1)}s (${failed} failed)`);
            batchTracker.hide(7000);

        }
        else {

            status.textContent =
                watermark
                    ? `Downloaded ${selectedShorts.length} selected Shorts with watermark in ${elapsedSeconds.toFixed(
                        1
                    )}s. ✓`
                    : `Downloaded ${selectedShorts.length} selected Shorts in ${elapsedSeconds.toFixed(
                        1
                    )}s. ✓`;

            batchTracker.complete(`All ${selectedShorts.length} Shorts downloaded in ${elapsedSeconds.toFixed(1)}s! ✓`);
            batchTracker.hide(6000);

        }

    }

    catch (error) {

        console.error(
            "Selected download error:",
            error
        );

        batchTracker.fail(error.message);

        status.textContent =
            "Selected download failed: " +
            error.message;

    }

    finally {

        button.disabled =
            false;

        button.textContent =
            "DOWNLOAD SELECTED";

        updateSelectionControls();

    }

}


// --------------------------------------------------
// COMPILE SELECTED + OPTIONAL WATERMARK
// --------------------------------------------------

async function compileSelected() {

    const selectedShorts =
        getSelectedShorts();

    if (selectedShorts.length < 2) {

        alert(
            "Select at least 2 Shorts to compile."
        );

        return;

    }

    const watermark =
        getWatermark();

    const compileButton =
        document.getElementById(
            "compileSelectedButton"
        );

    const downloadSelectedButton =
        document.getElementById(
            "downloadSelectedButton"
        );

    compileButton.disabled =
        true;

    downloadSelectedButton.disabled =
        true;

    compileButton.textContent =
        "PREPARING...";

    const compileTracker = new ProgressTracker({
        container: "selectionProgressContainer",
        fill: "selectionProgressFill",
        percent: "selectionProgressPercent",
        stage: "selectionProgressStage",
        timer: "selectionProgressTimer",
        detail: "selectionProgressDetail"
    });

    try {
        await refreshDownloadedFiles();

        // 1. Identify which selected shorts need downloading
        const shortsToDownload = selectedShorts.filter(function (short) {
            const urlMatch = (short.url || "").match(/(?:shorts\/|v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
            const inferred = urlMatch ? `short_${urlMatch[1]}.mp4` : null;

            if (short.downloadedFilename && downloadedFiles[short.downloadedFilename]) {
                return false;
            }
            if (inferred && downloadedFiles[inferred]) {
                short.downloadedFilename = inferred;
                return false;
            }
            return true;
        });

        // 2. Download missing clips concurrently
        if (shortsToDownload.length > 0) {
            compileTracker.start(`Downloading ${shortsToDownload.length} missing clips...`, 5);
            status.textContent = `Downloading ${shortsToDownload.length} selected Shorts...`;

            const MAX_CONCURRENT = 3;
            let nextIndex = 0;
            let completed = 0;

            async function worker() {
                while (true) {
                    const currentIndex = nextIndex++;
                    if (currentIndex >= shortsToDownload.length) {
                        return;
                    }

                    const short = shortsToDownload[currentIndex];
                    const individualButton = document.getElementById(`download-button-${short.index}`);

                    const prepPct = Math.round(5 + (completed / shortsToDownload.length) * 30);
                    compileTracker.update(
                        prepPct,
                        `Preparing clips (${completed + 1}/${shortsToDownload.length})...`,
                        short.title.slice(0, 35) + "..."
                    );

                    if (individualButton) {
                        individualButton.disabled = true;
                        individualButton.textContent = "DOWNLOADING...";
                    }

                    try {
                        const res = await fetch(`${BACKEND_URL}/download`, {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json"
                            },
                            body: JSON.stringify({
                                url: short.url,
                                watermark: "",
                                server_only: true
                            })
                        });

                        if (!res.ok) {
                            const errData = await res.json().catch(() => ({}));
                            throw new Error(errData.details || errData.error || `HTTP ${res.status}`);
                        }

                        const data = await res.json();
                        if (data.success && data.filename) {
                            short.downloadedFilename = data.filename;
                            downloadedFiles[data.filename] = true;
                            if (individualButton) {
                                individualButton.textContent = "DOWNLOADED ✓";
                                individualButton.dataset.downloaded = "true";
                                individualButton.disabled = false;
                            }
                        }
                    } catch (error) {
                        console.error("Download failed during compilation preparation:", short.title, error);
                        if (individualButton) {
                            individualButton.textContent = "DOWNLOAD";
                            individualButton.disabled = false;
                        }
                    }

                    completed++;
                    const donePrepPct = Math.round(5 + (completed / shortsToDownload.length) * 30);
                    compileTracker.update(
                        donePrepPct,
                        `Prepared ${completed}/${shortsToDownload.length} clips...`,
                        `Finished: ${short.title.slice(0, 30)}`
                    );
                }
            }

            const workerCount = Math.min(MAX_CONCURRENT, shortsToDownload.length);
            const workers = [];
            for (let i = 0; i < workerCount; i++) {
                workers.push(worker());
            }
            await Promise.all(workers);
            await refreshDownloadedFiles();
        }

        // 3. Collect filenames to compile preserving search result order
        const filesToCompile = [];
        for (let i = 0; i < selectedShorts.length; i++) {
            const short = selectedShorts[i];
            const urlMatch = (short.url || "").match(/(?:shorts\/|v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
            const inferred = urlMatch ? `short_${urlMatch[1]}.mp4` : null;

            let resolvedName = null;
            if (short.downloadedFilename && downloadedFiles[short.downloadedFilename]) {
                resolvedName = short.downloadedFilename;
            } else if (inferred && downloadedFiles[inferred]) {
                resolvedName = inferred;
                short.downloadedFilename = inferred;
            }

            if (resolvedName) {
                filesToCompile.push(resolvedName);
            }
        }

        if (filesToCompile.length < 2) {
            throw new Error(
                `Only ${filesToCompile.length} of ${selectedShorts.length} clips were prepared. Please ensure at least 2 Shorts are downloaded.`
            );
        }

        const compileTaskId = "compile_" + Date.now();
        const startMsg = watermark
            ? `Compiling ${filesToCompile.length} Shorts with watermark...`
            : `Compiling ${filesToCompile.length} Shorts...`;

        compileTracker.start(startMsg, 35);
        status.textContent = startMsg;
        compileTracker.pollTask(compileTaskId);

        compileButton.textContent = "COMPILING...";
        const compileStartTime = performance.now();

        const response = await fetch(`${BACKEND_URL}/compile`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                files: filesToCompile,
                watermark: watermark,
                task_id: compileTaskId,
                return_json: true
            })
        });

        if (!response.ok) {
            let errorMessage = "Compilation failed.";
            try {
                const errorData = await response.json();
                errorMessage = errorData.error || errorData.details || errorMessage;
            } catch (error) {
                // Ignore JSON parsing errors.
            }
            throw new Error(errorMessage);
        }

        compileTracker.update(98, "Saving compiled video...", "Downloading compilation file...");

        const contentType = response.headers.get("Content-Type") || "";
        let downloadUrl = null;
        const finalFilename = "shortbot_compilation.mp4";

        if (contentType.includes("application/json")) {
            const resultData = await response.json();
            if (!resultData.success) {
                throw new Error(resultData.error || resultData.details || "Compilation failed on backend.");
            }
            const serverFilename = resultData.filename || `compilation_${compileTaskId}.mp4`;
            const base = BACKEND_URL || "http://127.0.0.1:5000";
            downloadUrl = `${base}/file/${serverFilename}`;
        } else {
            const blob = await response.blob();
            downloadUrl = window.URL.createObjectURL(blob);
        }

        // Trigger native download
        if (ext && ext.downloads?.download) {
            try {
                const dlReq = ext.downloads.download({
                    url: downloadUrl,
                    filename: finalFilename,
                    saveAs: true
                }, (downloadId) => {
                    if (ext.runtime?.lastError) {
                        triggerAnchorDownload(downloadUrl, finalFilename);
                    }
                });
                if (dlReq && typeof dlReq.catch === "function") {
                    dlReq.catch((err) => {
                        console.warn("downloads.download failed, fallback to anchor:", err);
                        triggerAnchorDownload(downloadUrl, finalFilename);
                    });
                }
            } catch (dlErr) {
                triggerAnchorDownload(downloadUrl, finalFilename);
            }
        } else {
            triggerAnchorDownload(downloadUrl, finalFilename);
        }

        const compileElapsedSeconds = (performance.now() - compileStartTime) / 1000;
        compileTracker.complete(`Compilation complete in ${compileElapsedSeconds.toFixed(1)}s! ✓`);
        compileTracker.hide(7000);

        status.textContent = watermark
            ? `Compilation complete! ${filesToCompile.length} Shorts combined with watermark in ${compileElapsedSeconds.toFixed(1)}s. ✓`
            : `Compilation complete! ${filesToCompile.length} Shorts combined in ${compileElapsedSeconds.toFixed(1)}s. ✓`;

        compileButton.textContent = "COMPILED ✓";
        setTimeout(() => {
            compileButton.textContent = "COMPILE SELECTED";
        }, 5000);
    }

    }

    catch (error) {

        console.error(
            "Compilation error:",
            error
        );

        compileTracker.fail(error.message);

        status.textContent =
            "Compilation failed: " +
            error.message;

        compileButton.textContent =
            "COMPILE SELECTED";

        alert(
            "Could not compile the selected Shorts: " +
            error.message
        );

    }

    finally {

        downloadSelectedButton.disabled =
            false;

        updateSelectionControls();

    }

}


// --------------------------------------------------
// CREATE SELECTION CONTROLS
// --------------------------------------------------

function createSelectionControls() {

    const oldControls =
        document.getElementById(
            "selectionControls"
        );

    if (oldControls) {

        oldControls.remove();

    }

    const controls =
        document.createElement(
            "div"
        );

    controls.id =
        "selectionControls";

    const info =
        document.createElement(
            "div"
        );

    info.id =
        "selectionInfo";

    info.textContent =
        "0 selected";

    const downloadButton =
        document.createElement(
            "button"
        );

    downloadButton.id =
        "downloadSelectedButton";

    downloadButton.textContent =
        "DOWNLOAD SELECTED";

    downloadButton.disabled =
        true;

    downloadButton.addEventListener(
        "click",
        downloadSelected
    );

    const compileButton =
        document.createElement(
            "button"
        );

    compileButton.id =
        "compileSelectedButton";

    compileButton.textContent =
        "COMPILE SELECTED";

    compileButton.disabled =
        true;

    compileButton.addEventListener(
        "click",
        compileSelected
    );

    controls.appendChild(
        info
    );

    controls.appendChild(
        downloadButton
    );

    controls.appendChild(
        compileButton
    );

    const clearButton =
        document.createElement(
            "button"
        );

    clearButton.id =
        "clearResultsButton";

    clearButton.textContent =
        "CLEAR RESULTS";

    clearButton.addEventListener(
        "click",
        clearResults
    );

    controls.appendChild(
        clearButton
    );

    const selProgress = document.createElement("div");
    selProgress.id = "selectionProgressContainer";
    selProgress.className = "progress-card selection-progress";
    selProgress.style.display = "none";
    selProgress.innerHTML = `
        <div class="progress-header">
            <span id="selectionProgressStage" class="progress-stage">Processing...</span>
            <span class="progress-meta">
                <span id="selectionProgressPercent" class="progress-percent">0%</span>
                <span id="selectionProgressTimer" class="progress-timer">⏱ 00:00</span>
            </span>
        </div>
        <div class="progress-track">
            <div id="selectionProgressFill" class="progress-fill" style="width: 0%;"></div>
        </div>
        <div id="selectionProgressDetail" class="progress-detail">Starting batch...</div>
    `;
    controls.appendChild(selProgress);

    results.appendChild(
        controls
    );

}


// --------------------------------------------------
// RENDER RESULTS
// --------------------------------------------------

function renderShorts(
    foundShorts
) {

    shorts =
        foundShorts.map(
            function (short, index) {
                const urlMatch = (short.url || "").match(/(?:shorts\/|v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
                const inferredFilename = urlMatch ? `short_${urlMatch[1]}.mp4` : null;
                const isDownloaded = Boolean(
                    (short.downloadedFilename && downloadedFiles[short.downloadedFilename]) ||
                    (inferredFilename && downloadedFiles[inferredFilename])
                );

                return {
                    ...short,
                    index: index,
                    downloadedFilename: short.downloadedFilename || (isDownloaded ? inferredFilename : null)
                };

            }
        );

    shorts.forEach(
        function (short) {

            const card =
                document.createElement(
                    "div"
                );

            card.className =
                "short-card";

            const topRow =
                document.createElement(
                    "div"
                );

            topRow.style.display =
                "flex";

            topRow.style.alignItems =
                "flex-start";

            topRow.style.gap =
                "12px";

            const checkbox =
                document.createElement(
                    "input"
                );

            checkbox.type =
                "checkbox";

            checkbox.id =
                `short-checkbox-${short.index}`;

            checkbox.style.width =
                "20px";

            checkbox.style.height =
                "20px";

            checkbox.style.marginTop =
                "3px";

            checkbox.addEventListener(
                "change",
                updateSelectionControls
            );

            const title =
                document.createElement(
                    "h3"
                );

            title.textContent =
                `${short.index + 1}. ${short.title}`;

            title.style.margin =
                "0";

            topRow.appendChild(
                checkbox
            );

            topRow.appendChild(
                title
            );

            const buttons =
                document.createElement(
                    "div"
                );

            buttons.className =
                "short-buttons";

            const watchButton =
                document.createElement(
                    "a"
                );

            watchButton.href =
                short.url;

            watchButton.textContent =
                "WATCH SHORT";

            watchButton.target =
                "_blank";

            watchButton.rel =
                "noopener noreferrer";

            watchButton.className =
                "watch-button";

            const downloadButton =
                document.createElement(
                    "button"
                );

            downloadButton.id =
                `download-button-${short.index}`;

            const isAlreadyDownloaded = Boolean(short.downloadedFilename && downloadedFiles[short.downloadedFilename]);
            downloadButton.textContent = isAlreadyDownloaded ? "DOWNLOADED ✓" : "DOWNLOAD";
            if (isAlreadyDownloaded) {
                downloadButton.dataset.downloaded = "true";
            }

            downloadButton.className =
                "download-button";

            downloadButton.addEventListener(
                "click",
                async function () {

                    try {

                        await downloadShort(
                            short,
                            downloadButton
                        );

                        await refreshDownloadedFiles();

                        status.textContent =
                            getWatermark()
                                ? "Short downloaded with watermark successfully. ✓"
                                : "Short downloaded successfully. ✓";

                    }

                    catch (error) {

                        status.textContent =
                            "Download failed: " +
                            error.message;

                        alert(
                            "Could not download this Short: " +
                            error.message
                        );

                        setTimeout(
                            function () {

                                downloadButton.textContent =
                                    "DOWNLOAD";

                            },
                            2000
                        );

                    }

                }
            );

            buttons.appendChild(
                watchButton
            );

            buttons.appendChild(
                downloadButton
            );

            card.appendChild(
                topRow
            );

            card.appendChild(
                buttons
            );

            const inlineProgress = document.createElement("div");
            inlineProgress.id = `short-progress-${short.index}`;
            inlineProgress.className = "progress-card short-inline-progress";
            inlineProgress.style.display = "none";
            inlineProgress.innerHTML = `
                <div class="progress-header">
                    <span id="short-progress-stage-${short.index}" class="progress-stage">Downloading...</span>
                    <span class="progress-meta">
                        <span id="short-progress-percent-${short.index}" class="progress-percent">0%</span>
                        <span id="short-progress-timer-${short.index}" class="progress-timer">⏱ 00:00</span>
                    </span>
                </div>
                <div class="progress-track">
                    <div id="short-progress-fill-${short.index}" class="progress-fill" style="width: 0%;"></div>
                </div>
                <div id="short-progress-detail-${short.index}" class="progress-detail">Connecting to YouTube...</div>
            `;
            card.appendChild(inlineProgress);

            results.appendChild(
                card
            );

        }
    );

    createSelectionControls();

    refreshDownloadedFiles();

    updateSelectionControls();

    saveAppState();

}


// --------------------------------------------------
// SEARCH
// --------------------------------------------------

searchButton.addEventListener(
    "click",
    async function () {

        const userRequest =
            requestInput.value.trim();

        const quantity =
            Number(
                quantityInput.value
            );

        if (!userRequest) {

            status.textContent =
                "Please enter what Shorts you are looking for.";

            return;

        }

        if (
            !quantity ||
            quantity < 1
        ) {

            status.textContent =
                "Please enter a valid number of Shorts.";

            return;

        }

        shorts = [];

        downloadedFiles = {};

        document
            .querySelectorAll(
                ".short-card"
            )
            .forEach(
                function (card) {

                    card.remove();

                }
            );

        const oldControls =
            document.getElementById(
                "selectionControls"
            );

        if (oldControls) {

            oldControls.remove();

        }

        status.textContent =
            "Searching for Shorts...";

        searchButton.disabled =
            true;

        searchButton.textContent =
            "SEARCHING...";

        try {

            const response =
                await fetch(
                    `${BACKEND_URL}/search`,
                    {

                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body: JSON.stringify({

                            request:
                                userRequest,

                            quantity:
                                quantity

                        })

                    }
                );

            const data =
                await response.json();

            if (
                !response.ok ||
                !data.success
            ) {

                throw new Error(
                    data.error ||
                    "Search failed."
                );

            }

            const foundShorts =
                data.results || [];

            if (
                foundShorts.length === 0
            ) {

                status.textContent =
                    "No relevant Shorts were found.";

                return;

            }

            status.textContent =
                `Found ${foundShorts.length} relevant Shorts.`;

            renderShorts(
                foundShorts
            );

            saveAppState();

        }

        catch (error) {

            console.error(
                "Search error:",
                error
            );

            status.textContent =
                "Something went wrong: " +
                error.message;

        }

        finally {

            searchButton.disabled =
                false;

            searchButton.textContent =
                "FIND SHORTS";

        }

    }
);


// --------------------------------------------------
// INITIALIZATION
// --------------------------------------------------

window.addEventListener("unhandledrejection", function (event) {
    console.warn("Unhandled promise rejection in ShortBot:", event.reason);
});

async function initApp() {
    try {
        if (openTabButton) {
            // Hide openTabButton if already running in a dedicated browser tab
            const isExtensionPopup = window.location.protocol.startsWith("chrome-extension:") || window.location.protocol.startsWith("moz-extension:");
            if (window.innerWidth > 750 || !isExtensionPopup) {
                openTabButton.style.display = "none";
            } else {
                openTabButton.addEventListener("click", function () {
                    const extUrl = (ext && ext.runtime?.getURL) ? ext.runtime.getURL("index.html") : window.location.href;
                    if (ext && ext.tabs?.create) {
                        try {
                            const res = ext.tabs.create({ url: extUrl });
                            if (res && typeof res.catch === "function") res.catch(() => {});
                        } catch {
                            window.open(window.location.href, "_blank");
                        }
                    } else {
                        window.open(window.location.href, "_blank");
                    }
                });
            }
        }

        if (requestInput) requestInput.addEventListener("input", saveAppState);
        if (quantityInput) quantityInput.addEventListener("input", saveAppState);
        if (watermarkInput) watermarkInput.addEventListener("input", saveAppState);

        await restoreAppState();
        checkAndAutoStartBackend();
        checkActiveYouTubeTab();
        setupDirectDownloadSection();
    } catch (err) {
        console.error("ShortBot initApp error:", err);
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
} else {
    initApp();
}