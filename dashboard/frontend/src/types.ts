export interface Recording {
  id: string; // uuid
  recording_id: string;
  title: string;
  started_at: string;
  ended_at: string | null;
  status: 'planned' | 'live' | 'ended';
}

export interface Participant {
  id: number;
  name: string;
  initials: string | null;
  is_user: boolean;
  role: string | null;
  speaking_time_ratio: number;
  speaking_seconds: number;
  source: string;
}

export interface Goal {
  id: number;
  recording_id: string;
  description: string;
  coaching_tip: string | null;
  status: 'open' | 'achieved' | 'at_risk';
  topic_label: string | null;
  achieved_at: string | null;
  created_at: string;
}

export interface AgendaItem {
  id: number;
  recording_id: string;
  title: string;
  position: number;
  status: 'pending' | 'active' | 'done';
  topic_label: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  source: string;
}

export interface Decision {
  id: number;
  recording_id: string;
  description: string;
  status: 'agreed' | 'concept' | 'rejected';
  decided_at: string;
  topic_label: string | null;
  segment_id: number | null;
}

export interface ActionItem {
  id: number;
  recording_id: string;
  description: string;
  owner_name: string | null;
  owner_is_user: boolean;
  due_date: string | null;
  status: 'open' | 'done' | 'overdue';
  topic_label: string | null;
}

export interface KeyMoment {
  id: number;
  recording_id: string;
  type: 'commitment' | 'decision' | 'tension' | 'insight';
  quote: string;
  speaker_name: string | null;
  speaker_label: string | null;
  flagged_by: 'ai' | 'user';
  ts: string;
}

export interface PastReference {
  id: number;
  recording_id: string;
  topic_id: number;
  topic_label: string;
  source_recording_id: string;
  source_recording_title: string;
  source_recording_started_at: string;
  signal: 'repeated' | 'resolved' | 'new_context';
  summary: string;
  source: 'auto' | 'dig_deeper';
  created_at: string;
}

export interface ToneInfo {
  window_avg: number;
  label: 'constructive' | 'neutral' | 'tense';
}

export interface HeaderStats {
  participants: number;
  goals_achieved: number;
  goals_total: number;
  action_items: number;
  decisions: number;
}

export interface Snapshot {
  recording: Recording;
  participants: Participant[];
  goals: Goal[];
  agenda_items: AgendaItem[];
  decisions: Decision[];
  action_items: ActionItem[];
  key_moments: KeyMoment[];
  past_references: PastReference[];
  tone: ToneInfo;
  header_stats: HeaderStats;
}

export type WsEvent =
  | { type: 'segment.created'; recording_id: string; payload: Record<string, unknown> }
  | { type: 'segment.analyzed'; recording_id: string; payload: { segment_id: number; sentiment: number } }
  | { type: 'topic.tagged'; recording_id: string; payload: Record<string, unknown> }
  | { type: 'goal.updated'; recording_id: string; payload: Goal }
  | { type: 'agenda.updated'; recording_id: string; payload: { items: AgendaItem[] } }
  | { type: 'decision.upserted'; recording_id: string; payload: Decision }
  | { type: 'action_item.upserted'; recording_id: string; payload: ActionItem }
  | { type: 'key_moment.created'; recording_id: string; payload: KeyMoment }
  | { type: 'participant.stats'; recording_id: string; payload: { participants: Participant[] } }
  | { type: 'sentiment.updated'; recording_id: string; payload: ToneInfo }
  | { type: 'past_reference.created'; recording_id: string; payload: PastReference }
  | { type: 'recording.status'; recording_id: string; payload: { status: string; ended_at: string | null } }
  | { type: 'header.stats'; recording_id: string; payload: HeaderStats };
