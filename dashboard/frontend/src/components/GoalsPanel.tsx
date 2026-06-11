import { useEffect, useRef } from 'react';
import type { Goal } from '../types';

const STATUS_CLASSES: Record<Goal['status'], string> = {
  at_risk: 'bg-red-600 text-white',
  open: 'bg-amber-400 text-gray-900',
  achieved: 'bg-green-600 text-white',
};
const STATUS_LABELS: Record<Goal['status'], string> = {
  at_risk: 'At risk',
  open: 'Open',
  achieved: 'Achieved',
};

interface Props { goals: Goal[] }

export default function GoalsPanel({ goals }: Props) {
  const prevStatusRef = useRef<Record<number, string>>({});

  useEffect(() => {
    goals.forEach((g) => { prevStatusRef.current[g.id] = g.status; });
  });

  if (!goals.length) return (
    <PanelShell title="🎯 Goals">
      <p className="text-gray-400 text-sm italic">No goals defined yet.</p>
    </PanelShell>
  );

  return (
    <PanelShell title="🎯 Goals">
      <div className="flex flex-col gap-3">
        {goals.map((g) => (
          <div key={g.id}
            className={`rounded-lg p-4 border transition-all duration-500 ${
              g.status === 'at_risk' ? 'border-red-600 bg-red-950/40' :
              g.status === 'achieved' ? 'border-green-700 bg-green-950/40' :
              'border-gray-700 bg-gray-800/50'
            }`}
          >
            <div className="flex items-start gap-3">
              <span className={`mt-0.5 shrink-0 text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_CLASSES[g.status]}`}>
                {STATUS_LABELS[g.status]}
              </span>
              <p className="text-base font-medium text-gray-100 leading-snug">{g.description}</p>
            </div>
            {g.coaching_tip && (
              <blockquote className="mt-2 ml-1 pl-3 border-l-2 border-amber-400 text-amber-200 text-sm italic">
                {g.coaching_tip}
              </blockquote>
            )}
            {g.topic_label && (
              <span className="mt-2 inline-block text-xs text-gray-400"># {g.topic_label}</span>
            )}
          </div>
        ))}
      </div>
    </PanelShell>
  );
}

function PanelShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-gray-900 rounded-xl p-5 h-full flex flex-col gap-3">
      <h2 className="text-sm font-bold uppercase tracking-wider text-gray-400">{title}</h2>
      {children}
    </section>
  );
}
