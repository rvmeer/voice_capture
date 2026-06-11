import { create } from 'zustand';
import type {
  Snapshot, Goal, AgendaItem, Decision, ActionItem, KeyMoment,
  PastReference, ToneInfo, HeaderStats, Participant, WsEvent,
} from '../types';

interface RecordingStore {
  snapshot: Snapshot | null;
  loading: boolean;
  error: string | null;
  wsConnected: boolean;

  loadSnapshot: (recordingId: string) => Promise<void>;
  applyWsEvent: (event: WsEvent) => void;
  setWsConnected: (v: boolean) => void;
}

export const useRecordingStore = create<RecordingStore>((set, get) => ({
  snapshot: null,
  loading: false,
  error: null,
  wsConnected: false,

  setWsConnected: (v) => set({ wsConnected: v }),

  loadSnapshot: async (recordingId: string) => {
    set({ loading: true, error: null });
    try {
      const res = await fetch(`/recordings/${recordingId}/snapshot`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Snapshot = await res.json();
      set({ snapshot: data, loading: false });
    } catch (e: unknown) {
      set({ error: String(e), loading: false });
    }
  },

  applyWsEvent: (event: WsEvent) => {
    const s = get().snapshot;
    if (!s) return;

    switch (event.type) {
      case 'goal.updated': {
        const goal = event.payload as Goal;
        const goals = s.goals.map((g) => (g.id === goal.id ? goal : g));
        if (!goals.find((g) => g.id === goal.id)) goals.push(goal);
        const sorted = goals.sort((a, b) => {
          const o: Record<string, number> = { at_risk: 0, open: 1, achieved: 2 };
          return (o[a.status] ?? 1) - (o[b.status] ?? 1);
        });
        set({ snapshot: { ...s, goals: sorted } });
        break;
      }
      case 'agenda.updated': {
        const items = (event.payload as { items: AgendaItem[] }).items;
        set({ snapshot: { ...s, agenda_items: items } });
        break;
      }
      case 'decision.upserted': {
        const d = event.payload as Decision;
        const decisions = s.decisions.map((x) => (x.id === d.id ? d : x));
        if (!decisions.find((x) => x.id === d.id)) decisions.unshift(d);
        set({ snapshot: { ...s, decisions } });
        break;
      }
      case 'action_item.upserted': {
        const ai = event.payload as ActionItem;
        const items = s.action_items.map((x) => (x.id === ai.id ? ai : x));
        if (!items.find((x) => x.id === ai.id)) items.push(ai);
        set({ snapshot: { ...s, action_items: items } });
        break;
      }
      case 'key_moment.created': {
        const km = event.payload as KeyMoment;
        if (!s.key_moments.find((x) => x.id === km.id)) {
          set({ snapshot: { ...s, key_moments: [km, ...s.key_moments] } });
        }
        break;
      }
      case 'participant.stats': {
        const participants = ((event.payload as { participants?: Participant[] }).participants ?? []);
        set({ snapshot: { ...s, participants } });
        break;
      }
      case 'sentiment.updated': {
        set({ snapshot: { ...s, tone: event.payload as ToneInfo } });
        break;
      }
      case 'past_reference.created': {
        const pr = event.payload as PastReference;
        if (!s.past_references.find((x) => x.id === pr.id)) {
          set({ snapshot: { ...s, past_references: [...s.past_references, pr] } });
        }
        break;
      }
      case 'recording.status': {
        const { status, ended_at } = event.payload as { status: string; ended_at: string | null };
        set({ snapshot: { ...s, recording: { ...s.recording, status: status as 'live' | 'ended' | 'planned', ended_at } } });
        break;
      }
      case 'header.stats': {
        set({ snapshot: { ...s, header_stats: event.payload as HeaderStats } });
        break;
      }
      default:
        break;
    }
  },
}));
