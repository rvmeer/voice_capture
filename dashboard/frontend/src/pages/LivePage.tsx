import { useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useRecordingStore } from '../store/useRecordingStore';
import { useWebSocket } from '../store/useWebSocket';
import StatsHeader from '../components/StatsHeader';
import GoalsPanel from '../components/GoalsPanel';
import AgendaPanel from '../components/AgendaPanel';
import ActionItemsPanel from '../components/ActionItemsPanel';
import DecisionsPanel from '../components/DecisionsPanel';
import PastRecordingsPanel from '../components/PastRecordingsPanel';
import KeyMomentsPanel from '../components/KeyMomentsPanel';
import SpeakingTonePanel from '../components/SpeakingTonePanel';

export default function LivePage() {
  const { recordingId } = useParams<{ recordingId: string }>();
  const navigate = useNavigate();
  const { snapshot, loading, error, loadSnapshot, wsConnected } = useRecordingStore();

  useEffect(() => {
    if (recordingId) loadSnapshot(recordingId);
  }, [recordingId, loadSnapshot]);

  useWebSocket(recordingId);

  if (loading) return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center text-gray-400">
      Loading…
    </div>
  );

  if (error || !snapshot) return (
    <div className="min-h-screen bg-gray-950 flex flex-col items-center justify-center gap-4 text-gray-400">
      <p>{error ?? 'Recording not found.'}</p>
      <button onClick={() => navigate('/')} className="text-sm underline hover:text-white">
        ← Back to recordings
      </button>
    </div>
  );

  const { recording, participants, goals, agenda_items, decisions, action_items, key_moments, past_references, tone, header_stats } = snapshot;

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      <StatsHeader
        recording={recording}
        stats={header_stats}
        participants={participants}
        wsConnected={wsConnected}
      />

      <main className="flex-1 p-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 auto-rows-min">
        {/* Row 1: Goals, Agenda, Speaking+Tone */}
        <GoalsPanel goals={goals} />
        <AgendaPanel items={agenda_items} agendaMode={recording.agenda_mode} />
        <SpeakingTonePanel participants={participants} tone={tone} />

        {/* Row 2: Actions, Decisions, Key Moments */}
        <ActionItemsPanel items={action_items} />
        <DecisionsPanel decisions={decisions} />
        <KeyMomentsPanel moments={key_moments} recordingId={recording.recording_id} />

        {/* Row 3: Past Recordings — full width */}
        <div className="md:col-span-2 xl:col-span-3">
          <PastRecordingsPanel refs={past_references} recordingId={recording.recording_id} />
        </div>
      </main>
    </div>
  );
}
