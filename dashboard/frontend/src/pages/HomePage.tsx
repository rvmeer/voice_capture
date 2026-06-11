import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Recording } from '../types';

export default function HomePage() {
  const navigate = useNavigate();
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [loading, setLoading] = useState(true);
  const [setupOpen, setSetupOpen] = useState(false);
  const [setupForm, setSetupForm] = useState({
    title: '',
    participants: '',
    agenda: '',
    goals: '',
    topics: '',
  });
  const [setupSent, setSetupSent] = useState(false);

  useEffect(() => {
    function load() {
      fetch('/recordings')
        .then((r) => r.json())
        .then((data) => { setRecordings(data); setLoading(false); })
        .catch(() => setLoading(false));
    }
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  const live = recordings.filter((r) => r.status === 'live');
  const ended = recordings.filter((r) => r.status !== 'live');

  async function submitSetup() {
    const participants = setupForm.participants
      .split('\n').map((s) => s.trim()).filter(Boolean)
      .map((s) => {
        const parts = s.split('|').map((p) => p.trim());
        return { name: parts[0], initials: parts[1] ?? undefined };
      });
    const agenda = setupForm.agenda
      .split('\n').map((s) => s.trim()).filter(Boolean)
      .map((s, i) => ({ title: s, position: i + 1 }));
    const goals = setupForm.goals
      .split('\n').map((s) => s.trim()).filter(Boolean)
      .map((s) => ({ description: s }));
    const topics = setupForm.topics
      .split('\n').map((s) => s.trim()).filter(Boolean)
      .map((s) => ({ label: s }));

    await fetch('/recordings/precreate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        recording_title_hint: setupForm.title || undefined,
        participants,
        agenda,
        goals,
        topics,
      }),
    });
    setSetupSent(true);
    setSetupOpen(false);
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 px-6 py-8 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold">🎤 Voice Capture Dashboard</h1>
        <button
          onClick={() => { setSetupOpen(!setupOpen); setSetupSent(false); }}
          className="text-sm bg-purple-700 hover:bg-purple-600 px-4 py-2 rounded-lg transition"
        >
          {setupOpen ? 'Cancel setup' : '+ Pre-configure meeting'}
        </button>
      </div>

      {setupSent && (
        <div className="mb-6 bg-green-900/40 border border-green-700 rounded-lg px-4 py-3 text-green-300 text-sm">
          ✅ Meeting configuration saved — it will be applied when the next recording starts.
        </div>
      )}

      {setupOpen && (
        <div className="mb-8 bg-gray-900 rounded-xl p-6 border border-gray-700">
          <h2 className="text-base font-bold mb-4 text-purple-300">Pre-configure next meeting</h2>
          <div className="flex flex-col gap-4">
            <FormField
              label="Meeting title (optional)"
              hint="Used to match this config to the recording"
              value={setupForm.title}
              onChange={(v) => setSetupForm({ ...setupForm, title: v })}
              placeholder="Team standup"
            />
            <FormField
              label="Participants"
              hint="One per line: Name | Initials (initials optional)"
              value={setupForm.participants}
              onChange={(v) => setSetupForm({ ...setupForm, participants: v })}
              placeholder={"Ralf van Meer | RvM\nEllis Leijte | EL"}
              multiline
            />
            <FormField
              label="Agenda items"
              hint="One per line, in order"
              value={setupForm.agenda}
              onChange={(v) => setSetupForm({ ...setupForm, agenda: v })}
              placeholder={"Sprint review\nRetrospective\nPlanning"}
              multiline
            />
            <FormField
              label="Goals"
              hint="One per line"
              value={setupForm.goals}
              onChange={(v) => setSetupForm({ ...setupForm, goals: v })}
              placeholder={"Decide on sprint capacity\nAssign all open action items"}
              multiline
            />
            <FormField
              label="Topics"
              hint="One per line"
              value={setupForm.topics}
              onChange={(v) => setSetupForm({ ...setupForm, topics: v })}
              placeholder={"Performance\nDeployment\nBudget"}
              multiline
            />
            <button
              onClick={submitSetup}
              className="self-start bg-purple-700 hover:bg-purple-600 text-white px-6 py-2 rounded-lg font-semibold transition"
            >
              Save configuration
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-gray-400">Loading recordings…</p>
      ) : (
        <>
          {live.length > 0 && (
            <section className="mb-8">
              <h2 className="text-xs font-bold uppercase tracking-wider text-red-400 mb-3">🔴 Live now</h2>
              <div className="flex flex-col gap-2">
                {live.map((r) => <RecordingCard key={r.id} recording={r} onClick={() => navigate(`/live/${r.recording_id}`)} />)}
              </div>
            </section>
          )}
          <section>
            <h2 className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-3">
              {ended.length ? 'Past recordings' : 'No recordings yet'}
            </h2>
            <div className="flex flex-col gap-2">
              {ended.map((r) => <RecordingCard key={r.id} recording={r} onClick={() => navigate(`/live/${r.recording_id}`)} />)}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function RecordingCard({ recording, onClick }: { recording: Recording; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left bg-gray-900 hover:bg-gray-800 border border-gray-700 rounded-xl px-5 py-4 transition flex items-center gap-4"
    >
      {recording.status === 'live' && (
        <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse shrink-0" />
      )}
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-gray-100 truncate">{recording.title}</p>
        <p className="text-xs text-gray-400 mt-0.5">
          {new Date(recording.started_at).toLocaleString()} · {recording.recording_id}
        </p>
      </div>
      <span className={`text-xs px-2 py-0.5 rounded-full ${
        recording.status === 'live' ? 'bg-red-700 text-white' :
        recording.status === 'ended' ? 'bg-gray-700 text-gray-300' :
        'bg-gray-800 text-gray-400'
      }`}>
        {recording.status}
      </span>
    </button>
  );
}

function FormField({
  label, hint, value, onChange, placeholder, multiline,
}: {
  label: string; hint: string; value: string;
  onChange: (v: string) => void; placeholder?: string; multiline?: boolean;
}) {
  const cls = "w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-purple-500 placeholder:text-gray-600";
  return (
    <div>
      <label className="block text-sm font-medium text-gray-200 mb-1">{label}</label>
      <p className="text-xs text-gray-500 mb-1">{hint}</p>
      {multiline ? (
        <textarea
          rows={3}
          className={cls}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
      ) : (
        <input
          type="text"
          className={cls}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
      )}
    </div>
  );
}
