import { useEffect, useRef, useState } from "react";

/** Browser microphone. Stops tracks on completion/unmount; no raw audio storage. */
export function useAudioRecorder(onAudio: (uri: string, name: string, mime: string) => Promise<void>,
                                 onError: (message: string) => void) {
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  function release() {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    if (timer.current) clearTimeout(timer.current);
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (recorder.current?.state === "recording") recorder.current.stop();
      release();
    };
  }, []);
  async function toggle() {
    if (recorder.current?.state === "recording") {
      recorder.current.stop();
      return;
    }
    try {
      if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia)
        throw new Error("Microfone indisponível. Use localhost/HTTPS ou envie um arquivo de áudio.");
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!alive.current) { media.getTracks().forEach((t) => t.stop()); return; }
      stream.current = media;
      const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"]
        .find((type) => MediaRecorder.isTypeSupported(type));
      const instance = new MediaRecorder(media, mimeType ? { mimeType } : undefined);
      recorder.current = instance;
      const chunks: BlobPart[] = [];
      instance.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      instance.onerror = () => { release(); setRecording(false); onError("Falha ao gravar áudio."); };
      instance.onstop = async () => {
        release();
        if (!alive.current) return;
        setRecording(false);
        const mime = instance.mimeType || "audio/webm";
        const blob = new Blob(chunks, { type: mime });
        const uri = URL.createObjectURL(blob);
        try { await onAudio(uri, mime.includes("mp4") ? "gravacao.m4a" : "gravacao.webm", mime); }
        finally { URL.revokeObjectURL(uri); }
      };
      instance.start();
      setRecording(true);
      timer.current = setTimeout(() => {
        if (instance.state === "recording") instance.stop();
      }, 115000);
    } catch (e) {
      release();
      onError(String(e));
    }
  }
  return { recording, toggle };
}
