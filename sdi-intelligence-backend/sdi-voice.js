/* SDI VOICE: ask by voice or text; hear the answer, always see it (D-622).

   JG, 1 Nov 2026: "can the prompting be by voice user only, or text only? both ways would be
   ideal. summary voiced or texted back or both". The review: type or speak; show the recognised
   words so job numbers can be corrected; always display the written answer and its source;
   Listen / Stop with optional automatic spoken replies; speak the same saved answer; reuse the
   AM CRM's speech, because browser recognition alone is not consistently supported.

   One script for the e-mail walkthrough page, the desk estimating page and the phone.

   HEARING. Where the service has Azure AI Speech configured (SDI_SPEECH_KEY / SDI_SPEECH_REGION,
   the AM CRM's settings, voicecrm_speech.py), iPhones, and any browser without recognition,
   record the question as a 16 kHz WAV and the service turns it into words (the CRM's
   /api/voicecrm/transcribe). Elsewhere the browser's own recognition is used. Neither is ever
   sent as a question: the words go into the box, to be checked and corrected, and the person
   taps Ask.

   SPEAKING. The answer on screen, and the record's own figures, are what is read: nothing new
   is generated to be spoken. Azure's neural voice where configured (/api/voicecrm/speak), else
   the device's own voice, a sentence at a time; a sentence ends at a stop followed by a space,
   so "£421.37" is read as one figure.
*/
(function () {
  "use strict";
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition || null;
  var SYNTH = ("speechSynthesis" in window) ? window.speechSynthesis : null;
  var UA = navigator.userAgent || "";
  var IOS = /iPad|iPhone|iPod/.test(UA) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var ST = {speech_ready: false, speech_stt: "off", speech_tts: false};
  var asked = null, active = null, playing = null, audio = null;

  function status() {
    if (!asked) {
      asked = fetch("/api/estimate/speech", {credentials: "same-origin", cache: "no-store"})
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (j) { for (var k in (j || {})) ST[k] = j[k]; return ST; })
        .catch(function () { return ST; });
    }
    return asked;
  }

  function serverEars() {
    return !!(ST.speech_ready && navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
              (ST.speech_stt === "all" || (ST.speech_stt === "ios" && (IOS || !SR))));
  }
  function canListen() { return !!(SR || serverEars()); }
  function canSpeak() { return !!(SYNTH || ST.speech_tts); }

  // ── speaking ──────────────────────────────────────────────────────────────────────────
  function plain(text) {
    return String(text || "").replace(/[*_#`>|]/g, " ").replace(/\s+/g, " ").trim();
  }
  function sentences(text) {
    return plain(text).replace(/([.!?])\s+/g, "$1\u0000").split("\u0000")
      .filter(function (x) { return x.trim(); });
  }
  function reset(btn) {
    if (btn) { btn.textContent = btn.getAttribute("data-label") || "Listen"; btn.classList.remove("on"); }
  }
  function stop() {
    if (SYNTH) SYNTH.cancel();
    if (audio) { try { audio.pause(); } catch (e) {} }
    if (playing) reset(playing);
    playing = null;
  }
  function deviceVoice(text, btn) {
    if (!SYNTH) { reset(btn); playing = null; return; }
    var parts = sentences(text);
    var all = SYNTH.getVoices() || [];
    var v = null;
    for (var i = 0; i < all.length && !v; i++) if (/^en-GB/i.test(all[i].lang) && all[i].localService) v = all[i];
    for (i = 0; i < all.length && !v; i++) if (/^en-GB/i.test(all[i].lang)) v = all[i];
    for (i = 0; i < all.length && !v; i++) if (/^en/i.test(all[i].lang)) v = all[i];
    parts.forEach(function (part, n) {
      var u = new SpeechSynthesisUtterance(part.trim());
      if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = "en-GB"; }
      if (n === parts.length - 1) u.onend = function () { if (playing === btn) stop(); };
      u.onerror = function () { if (playing === btn) stop(); };
      SYNTH.speak(u);
    });
  }
  /* speak(text, btn): read `text`; the same button again stops it. */
  function speak(text, btn) {
    var again = btn && playing === btn;
    stop();
    if (again || !plain(text)) return;
    playing = btn || null;
    if (btn) {
      if (!btn.getAttribute("data-label")) btn.setAttribute("data-label", btn.textContent);
      btn.textContent = "Stop"; btn.classList.add("on");
    }
    if (!ST.speech_tts) return deviceVoice(text, btn);
    if (!audio) { audio = new Audio(); audio.setAttribute("playsinline", ""); }
    fetch("/api/voicecrm/speak", {method: "POST", credentials: "same-origin",
                                  headers: {"Content-Type": "application/json"},
                                  body: JSON.stringify({text: plain(text).slice(0, 4000)})})
      .then(function (r) {
        var type = r.headers.get("content-type") || "";
        if (!r.ok || type.indexOf("audio") < 0) throw new Error("no server voice");
        return r.blob();
      })
      .then(function (blob) {
        if (playing !== (btn || null)) return;
        audio.src = URL.createObjectURL(blob);
        audio.onended = function () { if (playing === (btn || null)) stop(); };
        return audio.play();
      })
      .catch(function () { if (playing === (btn || null)) deviceVoice(text, btn); });
  }

  // ── hearing ───────────────────────────────────────────────────────────────────────────
  function encodeWav(chunks, inRate, outRate) {          // the AM CRM's encoder
    var len = 0; chunks.forEach(function (c) { len += c.length; });
    var all = new Float32Array(len), o = 0;
    chunks.forEach(function (c) { all.set(c, o); o += c.length; });
    if (inRate < outRate) outRate = inRate;
    var ratio = inRate / outRate, outLen = Math.floor(len / ratio);
    var buf = new ArrayBuffer(44 + outLen * 2), v = new DataView(buf);
    function w(p, t) { for (var i = 0; i < t.length; i++) v.setUint8(p + i, t.charCodeAt(i)); }
    w(0, "RIFF"); v.setUint32(4, 36 + outLen * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, outRate, true); v.setUint32(28, outRate * 2, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, outLen * 2, true);
    for (var i = 0; i < outLen; i++) {
      var a = Math.floor(i * ratio), b = Math.min(len, Math.floor((i + 1) * ratio)), sum = 0;
      for (var j = a; j < b; j++) sum += all[j];
      var x = Math.max(-1, Math.min(1, b > a ? sum / (b - a) : (all[a] || 0)));
      v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7FFF, true);
    }
    return new Blob([buf], {type: "audio/wav"});
  }

  function micMessage(err) {
    return (err === "not-allowed" || err === "service-not-allowed" || err === "NotAllowedError")
      ? "The microphone is blocked for this page. Allow it in the browser's site settings, or type the question."
      : err === "no-speech" ? "Nothing was heard. Tap Speak and ask again, or type."
      : "The question was not caught (" + err + "). Try again, or type it.";
  }

  function viaServer(o) {
    var me = {stopped: false}, stream = null, ctx = null, src = null, proc = null, timer = null;
    var chunks = [], heard = false, lastVoice = 0, noise = 0, t0 = Date.now();
    function cleanup() {
      clearInterval(timer);
      try { if (proc) { proc.onaudioprocess = null; proc.disconnect(); } } catch (e) {}
      try { if (src) src.disconnect(); } catch (e) {}
      if (stream) stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) {} });
      try { if (ctx) ctx.close(); } catch (e) {}
    }
    function send() {
      if (me.stopped) return; me.stopped = true; cleanup(); active = null;
      o.onEnd && o.onEnd();
      if (!heard) { o.onState(micMessage("no-speech"), "err"); return; }
      o.onState("Working out what you said…");
      var wav = encodeWav(chunks, ctx.sampleRate, 16000);
      fetch("/api/voicecrm/transcribe", {method: "POST", credentials: "same-origin",
                                         headers: {"Content-Type": "audio/wav"}, body: wav})
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.state === "ok" && j.text) o.onDone(j.text);
          else o.onState(j.state === "no_speech" ? micMessage("no-speech")
                         : (j.detail || "The speech service could not read that. Type it instead."), "err");
        })
        .catch(function () { o.onState("The speech service could not be reached. Type the question.", "err"); });
    }
    me.stop = send;
    navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true,
                                                 autoGainControl: true, channelCount: 1}})
      .then(function (s) {
        stream = s;
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        if (me.stopped) { cleanup(); return; }
        src = ctx.createMediaStreamSource(stream);
        proc = ctx.createScriptProcessor(4096, 1, 1);
        proc.onaudioprocess = function (e) {
          if (me.stopped) return;
          var d = e.inputBuffer.getChannelData(0), sq = 0;
          chunks.push(new Float32Array(d));
          for (var i = 0; i < d.length; i++) sq += d[i] * d[i];
          var rms = Math.sqrt(sq / d.length), now = Date.now();
          if (now - t0 < 650) { noise = Math.max(noise, rms); return; }
          if (rms > Math.max(0.012, noise * 2.5)) {
            if (!heard) { heard = true; o.onState("Listening… pause when you are done, or tap to stop."); }
            lastVoice = now;
          }
          if (!heard && chunks.length > 12) chunks.splice(0, chunks.length - 12);
        };
        src.connect(proc); proc.connect(ctx.destination);
        o.onState("Listening… ask your question.");
        timer = setInterval(function () {
          var now = Date.now();
          if ((heard && now - lastVoice > 2500) || (!heard && now - t0 > 9000) || now - t0 > 45000) send();
        }, 200);
      })
      .catch(function (e) { me.stopped = true; active = null; o.onEnd && o.onEnd();
                            o.onState(micMessage(e && e.name || "mic"), "err"); });
    return me;
  }

  function viaBrowser(o) {
    var rec = new SR(), me = {stopped: false}, final = "";
    rec.lang = "en-GB"; rec.interimResults = true; rec.continuous = false; rec.maxAlternatives = 1;
    rec.onresult = function (e) {
      var interim = "";
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var t = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += t; else interim += t;
      }
      o.onInterim && o.onInterim((final + interim).trim());
    };
    rec.onerror = function (e) { me.error = e.error; };
    rec.onend = function () {
      active = null; o.onEnd && o.onEnd();
      if (final.trim()) o.onDone(final.trim());
      else o.onState(micMessage(me.error || "no-speech"), "err");
    };
    me.stop = function () { try { rec.stop(); } catch (e) {} };
    o.onState("Listening… ask your question.");
    rec.start();
    return me;
  }

  /* listen(o): o.onState(text, kind), o.onInterim(text), o.onDone(text), o.onEnd().
     Calling it again while listening stops and uses what was heard. Never submits. */
  function listen(o) {
    if (active) { active.stop(); return; }
    stop();
    if (serverEars()) { active = viaServer(o); return; }
    if (SR) { active = viaBrowser(o); return; }
    o.onState("This browser cannot take a spoken question. On a phone, the microphone key on "
              + "the keyboard types what you say into the box; then check it and tap Ask.", "err");
  }

  window.SDIVoice = {status: status, listen: listen, speak: speak, stop: stop,
                     canListen: canListen, canSpeak: canSpeak,
                     listening: function () { return !!active; },
                     settings: function () { return ST; }};
})();
