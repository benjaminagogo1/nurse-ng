/*
 * Integrated classroom controller, pinned to LiveKit browser SDK 2.25.0.
 *
 * DOM contract: one [data-education-room] with session-id/is-host/csrf and
 * optional token-url/state-url. All UI hooks are data-room-* attributes; the
 * template remains readable when this script or camera permission is absent.
 * Tokens live only in this controller's memory and are never put in storage,
 * URLs or offline caches. The server, not these host buttons, authorizes actions.
 *
 * Media lifecycle: preview is an explicit permission action. Local tracks are
 * reused on join, processor output is transmitted, and all tracks/processors,
 * attached media, poll timers and device listeners are released on leave,
 * terminal disconnect, permission revocation or pagehide. Temporary LiveKit
 * reconnects retain their tracks; a terminal reconnect requires a fresh grant.
 *
 * Quality is negotiated against actual hardware. HD requests use ideal1080p30,
 * adaptive subscriptions, dynacast and simulcast. Camera settings report actual
 * dimensions. Optional gentle lighting processes captured pixels into a real
 * transmitted track; a CSS brightness filter would only mislead the preview.
 */
(() => {
  "use strict";
  const root = document.querySelector("[data-education-room]");
  if (!root) return;
  const SDK = window.LivekitClient;
  const hook = (name) => root.querySelector(`[data-room-${name}]`);
  const endpoint = `/learning/live/sessions/${encodeURIComponent(root.dataset.sessionId)}`;
  const state = {
    room: null, preview: [], camera: null, microphone: null, joining: false,
    leaving: false, previewing: false, lifecycle: 0,
    canPublish: false, audioOnly: false, handRaised: false,
    timer: null, polling: false, destroyed: false, participants: [],
  };
  const isHost = root.dataset.isHost === "true";
  const tokenURL = root.dataset.tokenUrl || `${endpoint}/token`;
  const stateURL = root.dataset.stateUrl || `${endpoint}/room-state`;
  const previewVideo = hook("local-preview");
  const previewPlaceholder = hook("preview-placeholder");
  const status = hook("status");
  const error = hook("error");
  const stageWelcome = hook("welcome") || hook("stage-placeholder");

  function notice(value, bad = false) {
    const target = bad ? error : status;
    if (target) { target.textContent = value; target.hidden = !value; }
    if (!bad && error) { error.textContent = ""; error.hidden = true; }
  }

  function quality() {
    const value = hook("quality")?.value || "1080";
    return value === "360" ? { width: 640, height: 360, frameRate: 24 }
      : value === "720" ? { width: 1280, height: 720, frameRate: 30 }
        : { width: 1920, height: 1080, frameRate: 30 };
  }

  function videoOptions() {
    const device = hook("camera-device")?.value;
    return { resolution: quality(), facingMode: "user", ...(device ? { deviceId: device } : {}) };
  }

  function audioOptions() {
    const device = hook("mic-device")?.value;
    return {
      echoCancellation: true, noiseSuppression: true, autoGainControl: true,
      ...(device ? { deviceId: device } : {}),
    };
  }

  function publishOptions(source) {
    const resolution = quality();
    const presets = [SDK.VideoPresets.h180, SDK.VideoPresets.h360, SDK.VideoPresets.h720]
      .filter((preset) => preset && preset.resolution.height < resolution.height);
    return {
      source, videoCodec: "h264", simulcast: true,
      videoEncoding: { maxBitrate: resolution.height > 720 ? 4500000 : 2500000, maxFramerate: resolution.frameRate },
      videoSimulcastLayers: presets, dtx: true, red: true,
    };
  }

  async function request(url, body = undefined) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, {
        method: body === undefined ? "GET" : "POST", credentials: "same-origin", cache: "no-store",
        signal: controller.signal,
        headers: body === undefined ? { Accept: "application/json" } : {
          Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": root.dataset.csrf || "",
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      // Member routes redirect expired sessions to the normal sign-in page.
      // Fetch follows that redirect: a 200 HTML page must not be mistaken for
      // an empty, authorized classroom state while media keeps running.
      if (response.redirected && new URL(response.url, window.location.href).pathname === "/auth/login") {
        await leave();
        throw new Error("Your sign-in has expired. Sign in again before rejoining this classroom.");
      }
      let result;
      try { result = await response.json(); }
      catch {
        if (response.ok) throw new Error("The classroom returned an unreadable response. Please retry.");
        result = {};
      }
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) await leave();
        throw new Error(typeof result.detail === "string" ? result.detail : result.error || "This classroom action could not be completed.");
      }
      return result;
    } catch (failure) {
      if (failure.name === "AbortError") throw new Error("The classroom request timed out. Check your connection and retry.");
      throw failure;
    } finally { window.clearTimeout(timeout); }
  }

  function friendlyCameraError(failure) {
    if (failure.name === "NotAllowedError" || failure.name === "PermissionDeniedError") {
      return "Camera or microphone permission was declined. You can still listen; allow access in your browser to speak or use video.";
    }
    if (failure.name === "NotFoundError" || failure.name === "DevicesNotFoundError") {
      return "No matching camera or microphone was found. Connect a device, choose another one, or join to listen.";
    }
    return "Your camera could not start with these settings. Try another device or 720p, or join using audio only.";
  }

  /** Real pixel processor. Its output is swapped into the SDK sender and preview. */
  class GentleLightingProcessor {
    constructor() {
      this.name = "nurse-gentle-lighting";
      this.video = null; this.canvas = null; this.processedTrack = null;
      this.callback = null; this.timeout = null; this.active = false; this.lifecycle = 0;
    }
    async init({ track }) {
      const lifecycle = ++this.lifecycle;
      if (!HTMLCanvasElement.prototype.captureStream) throw new Error("Lighting adjustment is unavailable in this browser.");
      const video = document.createElement("video");
      video.autoplay = true; video.muted = true; video.playsInline = true;
      video.srcObject = new MediaStream([track]);
      this.video = video;
      await video.play();
      // A permission prompt or video startup may finish after the participant
      // has stopped capture. Never recreate a processed stream after cleanup.
      if (lifecycle !== this.lifecycle || track.readyState === "ended") {
        video.pause(); video.srcObject = null;
        throw new Error("Camera preview was stopped.");
      }
      const actual = track.getSettings();
      const canvas = document.createElement("canvas");
      canvas.width = actual.width || video.videoWidth || 1280;
      canvas.height = actual.height || video.videoHeight || 720;
      const context = canvas.getContext("2d", { alpha: false, desynchronized: true });
      if (!context || !('filter' in context)) {
        video.pause(); video.srcObject = null;
        throw new Error("Lighting adjustment is unavailable in this browser.");
      }
      this.video = video; this.canvas = canvas; this.active = true;
      const draw = () => {
        if (!this.active) return;
        // A modest correction preserves natural skin tones; neutral is default.
        context.filter = "brightness(1.10) contrast(1.02)";
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        if (video.requestVideoFrameCallback) this.callback = video.requestVideoFrameCallback(draw);
        else this.timeout = window.setTimeout(draw, 1000 / Math.min(actual.frameRate || 30, 30));
      };
      draw();
      this.processedTrack = canvas.captureStream(Math.min(actual.frameRate || 30, 30)).getVideoTracks()[0];
      if (!this.processedTrack) { await this.destroy(); throw new Error("Camera processing could not start."); }
    }
    async restart(options) { await this.destroy(); await this.init(options); }
    async destroy() {
      this.lifecycle += 1;
      this.active = false;
      if (this.callback !== null && this.video?.cancelVideoFrameCallback) this.video.cancelVideoFrameCallback(this.callback);
      if (this.timeout !== null) window.clearTimeout(this.timeout);
      this.processedTrack?.stop();
      if (this.video) { this.video.pause(); this.video.srcObject = null; }
      this.video = null; this.canvas = null; this.processedTrack = null;
      this.callback = null; this.timeout = null;
    }
  }

  async function applyCameraEnhancement(track) {
    if (!track) return;
    const media = track.mediaStreamTrack;
    const capabilities = media.getCapabilities?.() || {};
    const advanced = {};
    // Only use controls explicitly reported by this physical device. Unsupported
    // controls are skipped; visual quality still depends on the camera and light.
    for (const control of ["exposureMode", "whiteBalanceMode"]) {
      if (Array.isArray(capabilities[control]) && capabilities[control].includes("continuous")) advanced[control] = "continuous";
    }
    if (Object.keys(advanced).length) {
      try { await media.applyConstraints({ advanced: [advanced] }); } catch { /* Device default remains usable. */ }
    }
    if (hook("lighting")?.value === "gentle") {
      try { await track.setProcessor(new GentleLightingProcessor(), true); }
      catch (failure) { notice(failure.message + " Your original camera feed is being used.", true); }
    } else if (track.getProcessor?.()) await track.stopProcessor();
    showCameraSettings();
  }

  function showCameraSettings() {
    const target = hook("camera-settings");
    if (!target) return;
    const actual = state.camera?.mediaStreamTrack?.getSettings?.();
    const network = state.room?.localParticipant.connectionQuality;
    target.textContent = actual?.width
      ? `Camera: ${actual.width} × ${actual.height}${actual.frameRate ? ` · ${Math.round(actual.frameRate)} fps` : ""}${network ? ` · Connection: ${network}` : ""}. Video adapts to each learner’s connection.`
      : "Preview your camera to check its actual resolution. Camera quality also depends on lighting and your device.";
  }

  function showPreview(track) {
    if (!previewVideo) return;
    if (track) {
      track.attach(previewVideo); previewVideo.hidden = false;
      if (previewPlaceholder) previewPlaceholder.hidden = true;
    } else {
      previewVideo.pause(); previewVideo.srcObject = null; previewVideo.hidden = true;
      if (previewPlaceholder) previewPlaceholder.hidden = false;
    }
  }

  async function refreshDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    const devices = await navigator.mediaDevices.enumerateDevices();
    for (const [hookName, kind] of [["camera-device", "videoinput"], ["mic-device", "audioinput"], ["speaker-device", "audiooutput"]]) {
      const select = hook(hookName);
      if (!select) continue;
      const selected = select.value;
      select.replaceChildren();
      const fallback = new Option("Use device default", ""); select.append(fallback);
      devices.filter((device) => device.kind === kind).forEach((device, index) => {
        select.append(new Option(device.label || `${kind === "videoinput" ? "Camera" : "Microphone"} ${index + 1}`, device.deviceId));
      });
      if ([...select.options].some((option) => option.value === selected)) select.value = selected;
    }
  }

  async function startPreview() {
    if (!SDK) { notice("The classroom media library could not load. Refresh the page to retry.", true); return; }
    if (state.camera || state.microphone || state.previewing || state.room || state.joining || state.destroyed) return;
    const lifecycle = ++state.lifecycle;
    const current = () => lifecycle === state.lifecycle && !state.destroyed;
    state.previewing = true; controls();
    let captured = [];
    try {
      try { captured = await SDK.createLocalTracks({ audio: audioOptions(), video: state.audioOnly ? false : videoOptions() }); }
      catch (failure) {
        if (!current()) return;
        if (failure.name === "OverconstrainedError" || failure.name === "ConstraintNotSatisfiedError") {
          captured = await SDK.createLocalTracks({ audio: audioOptions(), video: state.audioOnly ? false : { ...videoOptions(), resolution: SDK.VideoPresets.h720.resolution } });
        } else throw failure;
      }
      // getUserMedia cannot be cancelled while its permission prompt is open.
      // Dispose late tracks instead of attaching them to a stopped/hidden page.
      if (!current()) { for (const track of captured) track.stop(); return; }
      state.preview = captured;
      state.camera = state.preview.find((track) => track.kind === SDK.Track.Kind.Video) || null;
      state.microphone = state.preview.find((track) => track.kind === SDK.Track.Kind.Audio) || null;
      await applyCameraEnhancement(state.camera);
      if (!current()) { for (const track of captured) { track.detach(); track.stop(); } return; }
      showPreview(state.camera); await refreshDevices();
      if (current()) notice(state.audioOnly ? "Your microphone is ready. Your camera remains off in audio-only mode." : "Preview is ready. Your microphone and camera are not shared until you join and enable them.");
    } catch (failure) {
      if (current()) { await stopPreview(); notice(friendlyCameraError(failure), true); }
    } finally { if (current()) state.previewing = false; controls(); }
  }

  async function stopPreview() {
    if (state.room) return; // Published capture belongs to leave/camera controls.
    state.lifecycle += 1; state.previewing = false;
    for (const track of state.preview) { track.detach(); track.stop(); }
    state.preview = []; state.camera = null; state.microphone = null;
    showPreview(null); showCameraSettings();
    if (hook("preview-start")) hook("preview-start").disabled = false;
    controls();
  }

  function controls() {
    const connected = Boolean(state.room?.state === "connected");
    for (const name of ["leave", "hand"]) if (hook(name)) hook(name).disabled = !connected;
    for (const name of ["mic", "camera"]) if (hook(name)) hook(name).disabled = !connected || !state.canPublish || (name === "camera" && state.audioOnly);
    if (hook("screen")) hook("screen").disabled = !connected || !isHost;
    if (hook("preview-start")) hook("preview-start").disabled = state.previewing || state.joining || Boolean(state.room || state.camera || state.microphone) || state.destroyed;
    if (hook("preview-stop")) hook("preview-stop").disabled = (!state.preview.length && !state.previewing) || connected;
    if (hook("send")) hook("send").disabled = !connected;
    if (hook("audio")) {
      hook("audio").disabled = !connected;
      hook("audio").hidden = !connected || state.room.canPlaybackAudio;
    }
    if (hook("join")) hook("join").disabled = connected || state.joining || state.previewing || state.destroyed || root.dataset.liveUnavailable === "true";
    for (const [name, on] of [["mic", state.room?.localParticipant.isMicrophoneEnabled], ["camera", state.room?.localParticipant.isCameraEnabled], ["screen", state.room?.localParticipant.isScreenShareEnabled], ["audio-only", state.audioOnly], ["hand", state.handRaised]]) {
      if (hook(name)) { hook(name).setAttribute("aria-pressed", String(Boolean(on))); hook(name).classList.toggle("is-active", Boolean(on)); }
    }
  }

  function detachTrack(track) {
    for (const element of track.detach()) {
      const tile = element.closest("[data-room-track]");
      if (tile) tile.remove(); else element.remove();
    }
    if (stageWelcome && !hook("stage")?.querySelector("[data-room-track]")) stageWelcome.hidden = false;
  }

  function attachRemoteTrack(track, publication, participant) {
    if (track.kind === SDK.Track.Kind.Video && state.audioOnly) { publication.setSubscribed(false); return; }
    const media = track.attach();
    media.autoplay = true; media.playsInline = true;
    media.dataset.roomTrack = publication.trackSid;
    if (track.kind === SDK.Track.Kind.Audio) {
      media.hidden = true; root.append(media);
      const speaker = hook("speaker-device")?.value;
      if (speaker && media.setSinkId) media.setSinkId(speaker).catch(() => {});
    } else {
      const tile = document.createElement("figure"); tile.dataset.roomTrack = publication.trackSid;
      tile.className = publication.source === SDK.Track.Source.ScreenShare ? "education-room-video is-screen-share" : "education-room-video";
      const caption = document.createElement("figcaption"); caption.textContent = participant.name || "Learner";
      tile.append(media, caption); hook("stage")?.append(tile);
      if (stageWelcome) stageWelcome.hidden = true;
    }
  }

  function renderParticipants() {
    const container = hook("participants");
    if (!container || !state.room) return;
    const participants = [state.room.localParticipant, ...state.room.remoteParticipants.values()];
    container.replaceChildren();
    for (const participant of participants) {
      const row = document.createElement("div"); row.className = "education-room-person";
      const label = document.createElement("span");
      label.textContent = participant.name || "Learner";
      if (participant.isLocal) label.textContent += " (you)";
      const domain = state.participants.find((item) => item.identity === participant.identity);
      if (domain?.hand_raised) label.textContent += " · Hand raised";
      row.append(label);
      if (isHost && !participant.isLocal) {
        for (const [action, title] of [["mute", "Mute"], [domain?.can_speak ? "revoke_speaking" : "allow_speaking", domain?.can_speak ? "Stop speaking" : "Allow speaking"], ["remove", "Remove"]]) {
          const button = document.createElement("button"); button.type = "button"; button.className = "education-room-person-action"; button.textContent = title;
          button.addEventListener("click", async () => {
            button.disabled = true;
            try { await request(`${endpoint}/moderation`, { action, identity: participant.identity }); await pollOnce(); }
            catch (failure) { notice(failure.message, true); } finally { button.disabled = false; }
          });
          row.append(button);
        }
      }
      container.append(row);
    }
    const count = hook("participant-count"); if (count) count.textContent = String(participants.length);
  }

  /** Keep camera rendering bounded even in a large lecture. Screen shares and
   * the current active speakers take priority; hidden participants retain audio.
   * LiveKit adaptiveStream then selects a layer suitable for each visible tile.
   */
  function updateVideoSubscriptions() {
    if (!state.room) return;
    const speakers = new Set((state.room.activeSpeakers || []).map((participant) => participant.identity));
    const participants = [...state.room.remoteParticipants.values()].sort((left, right) => {
      const weight = (participant) => (state.participants.find((item) => item.identity === participant.identity)?.is_host ? 2 : 0) + (speakers.has(participant.identity) ? 1 : 0);
      return weight(right) - weight(left);
    });
    const visible = new Set(participants.slice(0, 12).map((participant) => participant.identity));
    for (const participant of participants) for (const publication of participant.videoTrackPublications.values()) {
      publication.setSubscribed(!state.audioOnly && (publication.source === SDK.Track.Source.ScreenShare || visible.has(participant.identity)));
    }
  }

  function renderMessages(messages) {
    for (const [targetName, isQuestion] of [["chat-list", false], ["question-list", true]]) {
      const target = hook(targetName); if (!target) continue;
      const scrollAtEnd = target.scrollHeight - target.scrollTop - target.clientHeight < 80;
      target.replaceChildren();
      const rows = messages.filter((item) => (item.kind === "question") === isQuestion && !item.removed);
      if (!rows.length) {
        const empty = document.createElement("p"); empty.className = "education-room-empty";
        empty.textContent = isQuestion ? "Questions for your educator will appear here." : "The session conversation will appear here.";
        target.append(empty);
      }
      for (const item of rows) {
        const article = document.createElement("article"); article.className = "education-room-message";
        const name = document.createElement("strong"); name.textContent = item.display_name || "Learner";
        const body = document.createElement("p"); body.textContent = item.body;
        article.append(name, body);
        if (item.answered) { const answered = document.createElement("span"); answered.textContent = "Answered"; article.append(answered); }
        if (isHost) {
          for (const [action, title] of [["answer", "Mark answered"], ["remove_message", "Remove"]]) {
            if (action === "answer" && (!isQuestion || item.answered)) continue;
            const button = document.createElement("button"); button.type = "button"; button.textContent = title;
            button.addEventListener("click", async () => {
              button.disabled = true;
              try { await request(`${endpoint}/moderation`, { action, message_id: item.id }); await pollOnce(); }
              catch (failure) { notice(failure.message, true); } finally { button.disabled = false; }
            }); article.append(button);
          }
        }
        target.append(article);
      }
      if (scrollAtEnd) target.scrollTop = target.scrollHeight;
    }
  }

  async function pollOnce() {
    if (!state.room || state.polling || state.destroyed) return;
    state.polling = true;
    try {
      const data = await request(stateURL);
      if (["ended", "cancelled"].includes(data.status)) { await leave(); notice("This learning session has ended."); return; }
      state.participants = data.participants || [];
      renderMessages(data.messages || []); renderParticipants(); updateVideoSubscriptions();
    } catch (failure) { notice(failure.message, true); }
    finally { state.polling = false; }
  }

  function schedulePoll() {
    window.clearTimeout(state.timer);
    if (!state.room || state.destroyed) return;
    state.timer = window.setTimeout(async () => { await pollOnce(); schedulePoll(); }, document.hidden ? 20000 : 6000 + Math.random() * 1000);
  }

  async function join() {
    if (!SDK) { notice("The classroom media library could not load. Refresh the page to retry.", true); return; }
    if (state.room || state.joining || state.previewing || state.destroyed) return;
    const lifecycle = ++state.lifecycle;
    const checkCurrent = () => {
      if (lifecycle !== state.lifecycle || state.destroyed) throw new Error("Classroom entry was stopped. Join again when you are ready.");
    };
    const recordingConsent = hook("recording-consent");
    if (recordingConsent && !recordingConsent.checked) {
      notice("Please acknowledge the recording notice before joining this lecture.", true); return;
    }
    state.joining = true; controls(); notice("Connecting to your classroom…");
    try {
      const grant = await request(tokenURL, { recording_consent: recordingConsent?.checked === true });
      checkCurrent();
      if (!grant.url || !grant.token) throw new Error("The classroom could not issue a connection grant.");
      state.canPublish = Boolean(grant.can_publish);
      const room = new SDK.Room({
        adaptiveStream: true, dynacast: true,
        videoCaptureDefaults: videoOptions(), audioCaptureDefaults: audioOptions(),
        publishDefaults: publishOptions(SDK.Track.Source.Camera),
      });
      state.room = room;
      room.on(SDK.RoomEvent.TrackSubscribed, attachRemoteTrack);
      room.on(SDK.RoomEvent.TrackUnsubscribed, detachTrack);
      for (const event of [SDK.RoomEvent.ParticipantConnected, SDK.RoomEvent.ParticipantDisconnected, SDK.RoomEvent.TrackMuted, SDK.RoomEvent.TrackUnmuted, SDK.RoomEvent.TrackPublished, SDK.RoomEvent.ActiveSpeakersChanged]) room.on(event, () => { renderParticipants(); controls(); updateVideoSubscriptions(); });
      room.on(SDK.RoomEvent.LocalTrackPublished, () => { controls(); showCameraSettings(); });
      room.on(SDK.RoomEvent.LocalTrackUnpublished, controls);
      room.on(SDK.RoomEvent.ConnectionQualityChanged, showCameraSettings);
      room.on(SDK.RoomEvent.ParticipantPermissionsChanged, (previous, participant) => {
        if (participant?.isLocal) {
          state.canPublish = Boolean(participant.permissions?.canPublish);
          if (!state.canPublish) {
            state.camera?.stop(); state.microphone?.stop();
            state.camera = null; state.microphone = null; showPreview(null);
            notice("Your educator has returned your participation to listening mode.");
          }
          controls();
        }
      });
      room.on(SDK.RoomEvent.Reconnecting, () => { notice("Reconnecting… Your session will resume when the connection returns."); controls(); });
      room.on(SDK.RoomEvent.Reconnected, () => { notice("Connection restored."); controls(); schedulePoll(); });
      room.on(SDK.RoomEvent.Disconnected, () => { leave(); notice("You have left the live classroom. Join again to reconnect."); });
      room.on(SDK.RoomEvent.MediaDevicesError, (failure) => notice(friendlyCameraError(failure), true));
      room.on(SDK.RoomEvent.AudioPlaybackStatusChanged, () => {
        controls();
        if (!room.canPlaybackAudio) notice("Tap the audio button to enable classroom sound.", true);
      });
      await room.connect(grant.url, grant.token, { autoSubscribe: true });
      checkCurrent();
      await room.startAudio();
      checkCurrent();
      // Preview tracks are private until explicitly publishing. Microphone stays
      // muted on entry; a previewed camera can be shared by an authorized speaker.
      if (state.canPublish) {
        if (state.microphone) {
          await state.microphone.mute();
          checkCurrent();
          await room.localParticipant.publishTrack(state.microphone, { source: SDK.Track.Source.Microphone, dtx: true, red: true });
          checkCurrent();
        }
        if (state.camera && !state.audioOnly) {
          await state.camera.mute();
          checkCurrent();
          await room.localParticipant.publishTrack(state.camera, publishOptions(SDK.Track.Source.Camera));
          checkCurrent();
          showPreview(null);
        }
      } else {
        for (const track of state.preview) { track.detach(); track.stop(); }
        state.preview = []; state.camera = null; state.microphone = null; showPreview(null);
      }
      notice(state.canPublish ? "You’re in the classroom. Your microphone and camera start off; enable them when you’re ready." : "You’re in the classroom. Raise your hand when you would like to speak.");
      renderParticipants(); updateVideoSubscriptions(); await pollOnce(); schedulePoll();
    } catch (failure) { await leave(); notice(failure.message || "The classroom could not connect. Please retry.", true); }
    finally { state.joining = false; controls(); }
  }

  async function leave() {
    state.lifecycle += 1; state.previewing = false;
    if (state.leaving) return;
    state.leaving = true; window.clearTimeout(state.timer); state.timer = null;
    const room = state.room; state.room = null;
    // Stop capture synchronously before awaiting network shutdown. pagehide can
    // freeze promises while a browser places the page in its back-forward cache.
    for (const track of state.preview) { track.detach(); track.stop(); }
    try {
      if (room) {
        room.removeAllListeners();
        for (const participant of room.remoteParticipants.values()) for (const publication of participant.trackPublications.values()) if (publication.track) detachTrack(publication.track);
        for (const publication of room.localParticipant.trackPublications.values()) publication.track?.stop();
        await room.disconnect(true);
      }
    } finally {
      for (const track of state.preview) { track.detach(); track.stop(); }
      state.preview = []; state.camera = null; state.microphone = null;
      state.canPublish = false; state.handRaised = false;
      showPreview(null); showCameraSettings();
      hook("participants")?.replaceChildren();
      hook("stage")?.querySelectorAll("[data-room-track]").forEach((element) => element.remove());
      if (stageWelcome) stageWelcome.hidden = false;
      root.querySelectorAll("audio[data-room-track]").forEach((element) => { element.pause(); element.srcObject = null; element.remove(); });
      if (hook("preview-start")) hook("preview-start").disabled = false;
      state.leaving = false; controls();
    }
  }

  function action(name, callback) {
    hook(name)?.addEventListener("click", async (event) => {
      const button = event.currentTarget; button.disabled = true;
      try { await callback(); } catch (failure) { notice(failure.message || "This classroom action could not complete.", true); }
      finally { controls(); if (name === "audio-only") button.disabled = false; }
    });
  }

  action("join", join);
  action("leave", async () => { await leave(); notice("You have left the classroom. Your camera and microphone are stopped."); });
  action("preview-start", startPreview); action("preview-stop", stopPreview);
  action("mic", async () => {
    const local = state.room?.localParticipant; if (!local) return;
    await local.setMicrophoneEnabled(!local.isMicrophoneEnabled, audioOptions());
    state.microphone = local.getTrackPublication(SDK.Track.Source.Microphone)?.track || state.microphone;
  });
  action("camera", async () => {
    const local = state.room?.localParticipant; if (!local) return;
    const enable = !local.isCameraEnabled;
    await local.setCameraEnabled(enable, videoOptions(), publishOptions(SDK.Track.Source.Camera));
    state.camera = local.getTrackPublication(SDK.Track.Source.Camera)?.track || null;
    if (enable) await applyCameraEnhancement(state.camera);
    showPreview(enable ? state.camera : null);
  });
  action("screen", async () => {
    const local = state.room?.localParticipant; if (!local || !isHost) return;
    await local.setScreenShareEnabled(!local.isScreenShareEnabled, { audio: true, resolution: SDK.VideoPresets.h1080.resolution }, { source: SDK.Track.Source.ScreenShare, videoEncoding: { maxBitrate: 4000000, maxFramerate: 15 } });
  });
  action("audio-only", async () => {
    state.audioOnly = !state.audioOnly;
    if (state.audioOnly) {
      if (state.previewing) await stopPreview();
      if (state.room?.localParticipant.isCameraEnabled) await state.room.localParticipant.setCameraEnabled(false);
      const camera = state.camera;
      if (camera) {
        const local = state.room?.localParticipant;
        if (local?.getTrackPublication(SDK.Track.Source.Camera)) await local.unpublishTrack(camera, true);
        camera.detach(); camera.stop();
        state.preview = state.preview.filter((track) => track !== camera);
        state.camera = null;
      }
    }
    updateVideoSubscriptions();
    if (state.audioOnly) showPreview(null);
    notice(state.audioOnly ? "Audio-only mode is on. Video is paused to reduce data use." : "Video reception is enabled; it adapts to your connection.");
  });
  action("hand", async () => {
    const raised = !state.handRaised; await request(`${endpoint}/hand`, { raised }); state.handRaised = raised;
    notice(raised ? "Your educator can see your raised hand." : "Your hand is lowered.");
  });
  action("audio", async () => { await state.room?.startAudio(); });

  hook("message-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget;
    const body = form.elements.namedItem("body"); const kind = form.elements.namedItem("kind");
    const button = form.querySelector('button[type="submit"]');
    if (!body?.value.trim()) return;
    if (button) button.disabled = true;
    try { await request(`${endpoint}/messages`, { body: body.value, kind: kind?.value || "chat" }); body.value = ""; await pollOnce(); }
    catch (failure) { notice(failure.message, true); }
    finally { if (button) button.disabled = false; }
  });

  for (const name of ["quality", "camera-device", "lighting"]) hook(name)?.addEventListener("change", async () => {
    if (!state.camera) { showCameraSettings(); return; }
    try {
      if (name !== "lighting") await state.camera.restartTrack(videoOptions());
      await applyCameraEnhancement(state.camera); showPreview(state.camera);
    } catch (failure) { notice(friendlyCameraError(failure), true); }
  });
  hook("mic-device")?.addEventListener("change", async () => {
    try { await state.microphone?.restartTrack(audioOptions()); } catch (failure) { notice(friendlyCameraError(failure), true); }
  });
  const deviceListener = () => refreshDevices().catch(() => {});
  navigator.mediaDevices?.addEventListener("devicechange", deviceListener);
  window.addEventListener("pagehide", () => {
    state.destroyed = true; navigator.mediaDevices?.removeEventListener("devicechange", deviceListener); leave();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      state.destroyed = false; navigator.mediaDevices?.addEventListener("devicechange", deviceListener); controls();
    }
  });
  controls(); showCameraSettings();
  if (!SDK) notice("The classroom media library could not load. Refresh this page to retry.", true);
})();
