"use client";

import { useEffect, useRef, useState } from "react";

import { DICTATION_LANGUAGES, preferredLanguage } from "@/lib/dictation";
import type { DictationLanguage } from "@/lib/dictation";

/**
 * Dictate instead of type.
 *
 * Uses the browser's own speech recognition rather than a transcription model.
 * Three reasons, in order of weight: it costs nothing, which matters because a
 * request describing a production job is exactly the kind of thing somebody
 * writes on a phone between meetings and not the kind of thing worth a bill;
 * it needs no key, no backend route and no new dependency; and it starts
 * producing words while you are still speaking, which a round trip cannot.
 *
 * What it is NOT is private. Chrome and Edge send the audio to a speech
 * service to recognise it - the microphone does not stay on the device the way
 * the phrase "browser speech recognition" suggests. That is disclosed in the
 * interface rather than buried here, because somebody dictating a customer's
 * brief deserves to know before they start, not after.
 *
 * Support is genuinely partial: Chrome and Edge yes, Firefox no, Safari
 * inconsistently. Where it is missing this says so plainly instead of showing
 * a button that does nothing.
 */

// The DOM lib does not carry these, and pulling in a types package for one
// interface would be a dependency for a definition. Narrowed to what is used.
interface SpeechRecognitionAlternative {
  transcript: string;
}
interface SpeechRecognitionResult {
  isFinal: boolean;
  0: SpeechRecognitionAlternative;
}
interface SpeechRecognitionEvent {
  resultIndex: number;
  results: { length: number; [index: number]: SpeechRecognitionResult };
}
interface SpeechRecognitionErrorEvent {
  error: string;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function recogniserConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const candidate = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  return candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null;
}

const ERROR_MESSAGES: Record<string, string> = {
  "not-allowed": "The microphone is blocked. Allow it in your browser's address bar, then try again.",
  "service-not-allowed": "This browser would not start its speech service. Typing still works.",
  network: "Speech recognition needs a connection and could not reach it.",
  "audio-capture": "No microphone was found.",
};

export function VoiceDictation({
  onText,
  label = "Dictate",
}: {
  /** Called with each finished phrase, never with interim guesses. */
  onText: (fragment: string) => void;
  label?: string;
}) {
  // Resolved in an effect, not during render: the server has no `window`, and
  // deciding this while rendering would make the server and client disagree.
  const [supported, setSupported] = useState<boolean | null>(null);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState<DictationLanguage>("en-US");

  const recogniser = useRef<SpeechRecognitionLike | null>(null);
  // The callback is read at event time rather than captured, so a re-render
  // between starting and speaking cannot leave the recogniser talking to a
  // stale target.
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  useEffect(() => {
    setSupported(recogniserConstructor() !== null);
    setLanguage(preferredLanguage(navigator.language));
  }, []);

  useEffect(() => {
    // Stop listening if this leaves the page - an open microphone that nobody
    // can see is the one failure mode here that is worse than not working.
    return () => recogniser.current?.stop();
  }, []);

  function start() {
    const Recogniser = recogniserConstructor();
    if (!Recogniser) return;

    setError(null);
    const instance = new Recogniser();
    instance.lang = language;
    instance.continuous = true;
    instance.interimResults = true;

    instance.onresult = (event) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        // The index type cannot promise a result is there, and a recogniser
        // that skipped one should cost a missing word, not a thrown error
        // inside an event handler nobody is catching.
        if (!result) continue;
        if (result.isFinal) {
          onTextRef.current(result[0].transcript);
        } else {
          pending += result[0].transcript;
        }
      }
      setInterim(pending);
    };

    instance.onerror = (event) => {
      // Silence is not an error worth a message: it happens whenever somebody
      // pauses to think, and a red box for thinking would be absurd.
      if (event.error === "no-speech" || event.error === "aborted") return;
      setError(ERROR_MESSAGES[event.error] ?? "Dictation stopped unexpectedly.");
    };

    instance.onend = () => {
      setListening(false);
      setInterim("");
    };

    recogniser.current = instance;
    instance.start();
    setListening(true);
  }

  function stop() {
    recogniser.current?.stop();
    setListening(false);
    setInterim("");
  }

  // Nothing at all until the effect has run, so the button does not appear and
  // then vanish on browsers that cannot use it.
  if (supported === null) return null;

  if (!supported) {
    return (
      <p className="text-xs text-ink-muted">
        Dictation needs Chrome, Edge or Safari. Typing works everywhere.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={listening ? stop : start}
          aria-pressed={listening}
          className={
            listening
              ? "inline-flex items-center gap-2 rounded-lg border border-blocked/40 bg-blocked/5 px-3.5 py-2 text-sm font-medium text-blocked transition-colors"
              : "inline-flex items-center gap-2 rounded-lg border border-line px-3.5 py-2 text-sm font-medium text-ink-soft transition-colors hover:border-ink-muted hover:text-ink"
          }
        >
          <span aria-hidden className={listening ? "animate-pulse" : undefined}>
            {listening ? "●" : "🎙"}
          </span>
          {listening ? "Stop dictating" : label}
        </button>

        <label className="sr-only" htmlFor="dictation-language">
          Dictation language
        </label>
        <select
          id="dictation-language"
          value={language}
          disabled={listening}
          onChange={(event) => setLanguage(event.target.value as DictationLanguage)}
          className="rounded-lg border border-line bg-surface px-2.5 py-2 text-xs text-ink-soft disabled:opacity-50"
        >
          {DICTATION_LANGUAGES.map((option) => (
            <option key={option.code} value={option.code}>
              {option.label}
            </option>
          ))}
        </select>

        {listening ? (
          <span className="text-xs text-ink-muted">
            Speak; the words appear as you go. Punctuation: say &ldquo;comma&rdquo;,
            &ldquo;full stop&rdquo;.
          </span>
        ) : null}
      </div>

      {interim ? (
        <p className="text-xs italic text-ink-muted" aria-live="polite">
          {interim}…
        </p>
      ) : null}

      {error ? <p className="text-xs text-blocked">{error}</p> : null}

      {listening ? (
        <p className="text-xs text-ink-muted">
          Your browser sends the audio to its own speech service to recognise it.
        </p>
      ) : null}
    </div>
  );
}
