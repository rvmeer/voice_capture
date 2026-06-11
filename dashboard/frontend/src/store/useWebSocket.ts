import { useEffect, useRef } from 'react';
import { useRecordingStore } from '../store/useRecordingStore';
import type { WsEvent } from '../types';

const BASE_DELAY = 1000;
const MAX_DELAY = 30000;

export function useWebSocket(recordingId: string | undefined) {
  const applyWsEvent = useRecordingStore((s) => s.applyWsEvent);
  const loadSnapshot = useRecordingStore((s) => s.loadSnapshot);
  const setWsConnected = useRecordingStore((s) => s.setWsConnected);
  const delayRef = useRef(BASE_DELAY);
  const wsRef = useRef<WebSocket | null>(null);
  const unmountedRef = useRef(false);

  useEffect(() => {
    if (!recordingId) return;
    unmountedRef.current = false;

    function connect() {
      if (unmountedRef.current) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${proto}//${window.location.host}/ws/${recordingId}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        delayRef.current = BASE_DELAY;
        setWsConnected(true);
      };

      ws.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data) as WsEvent;
          applyWsEvent(event);
        } catch {
          // ignore malformed events
        }
      };

      ws.onclose = () => {
        setWsConnected(false);
        if (!unmountedRef.current) {
          const delay = delayRef.current;
          delayRef.current = Math.min(delay * 2, MAX_DELAY);
          setTimeout(() => {
            if (!unmountedRef.current) {
              loadSnapshot(recordingId!);
              connect();
            }
          }, delay);
        }
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      unmountedRef.current = true;
      wsRef.current?.close();
    };
  }, [recordingId, applyWsEvent, loadSnapshot, setWsConnected]);
}
