import React, { useState } from 'react';
import type { ActiveSessionStatus, SessionMetadata } from '../types/session';

interface ReplayControlsProps {
  sessionStatus: ActiveSessionStatus | null;
  sessions: SessionMetadata[];
  onStartReplay: (sessionId: string, speed?: number, seekSeq?: number) => Promise<void>;
  onPause: () => Promise<void>;
  onResume: () => Promise<void>;
  onSeek: (targetSeq: number) => Promise<void>;
  onSetSpeed: (multiplier: number) => Promise<void>;
  onReturnToLive: () => Promise<void>;
  onRefreshSessions: () => Promise<void>;
}

const SPEED_OPTIONS = [
  { label: '0.5x', value: 0.5 },
  { label: '1x', value: 1.0 },
  { label: '2x', value: 2.0 },
  { label: '5x', value: 5.0 },
  { label: '10x', value: 10.0 },
  { label: 'MAX', value: 1000.0 },
];

export const ReplayControls: React.FC<ReplayControlsProps> = ({
  sessionStatus,
  sessions,
  onStartReplay,
  onPause,
  onResume,
  onSeek,
  onSetSpeed,
  onReturnToLive,
  onRefreshSessions,
}) => {
  const [showSessionModal, setShowSessionModal] = useState<boolean>(false);
  const [isScrubbing, setIsScrubbing] = useState<boolean>(false);
  const [scrubValue, setScrubValue] = useState<number>(1);

  const mode = sessionStatus?.mode || 'LIVE';
  const isReplayMode = mode === 'REPLAY' || mode === 'PAUSED' || (mode === 'STOPPED' && sessionStatus?.total_events && sessionStatus.total_events > 0);
  const isPaused = sessionStatus?.is_paused || mode === 'PAUSED' || mode === 'STOPPED';
  const currentSeq = isScrubbing ? scrubValue : (sessionStatus?.current_seq || 1);
  const totalEvents = sessionStatus?.total_events || 1;
  const currentSpeed = sessionStatus?.speed_multiplier || 1.0;

  const handleScrubberChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setScrubValue(parseInt(e.target.value, 10));
  };

  const handleScrubberStart = () => {
    setIsScrubbing(true);
    setScrubValue(sessionStatus?.current_seq || 1);
  };

  const handleScrubberEnd = async () => {
    setIsScrubbing(false);
    await onSeek(scrubValue);
  };

  const handleOpenModal = async () => {
    await onRefreshSessions();
    setShowSessionModal(true);
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg px-3.5 py-2.5 shadow-md flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        {/* Left: Mode Badge & Session Selector */}
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-2 px-2.5 py-1 rounded bg-slate-950 border border-slate-800">
            {mode === 'LIVE' && (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
                <span className="text-xs font-semibold text-emerald-400 tracking-wide">LIVE FEED</span>
              </>
            )}
            {mode === 'REPLAY' && (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-sky-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-sky-500"></span>
                </span>
                <span className="text-xs font-semibold text-sky-400 tracking-wide">REPLAY</span>
              </>
            )}
            {mode === 'PAUSED' && (
              <>
                <span className="h-2 w-2 rounded-full bg-amber-400"></span>
                <span className="text-xs font-semibold text-amber-400 tracking-wide">PAUSED</span>
              </>
            )}
            {mode === 'STOPPED' && (
              <>
                <span className="h-2 w-2 rounded-full bg-slate-500"></span>
                <span className="text-xs font-semibold text-slate-400 tracking-wide">COMPLETED</span>
              </>
            )}
          </div>

          <button
            onClick={handleOpenModal}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white rounded border border-slate-700/60 transition-colors"
            title="Browse recorded simulation sessions"
          >
            <span>📁 Sessions</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-slate-700 text-slate-300 font-mono">
              {sessions.length}
            </span>
          </button>

          {isReplayMode && (
            <button
              onClick={onReturnToLive}
              className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-emerald-950/80 hover:bg-emerald-900/90 text-emerald-300 rounded border border-emerald-700/50 transition-colors"
            >
              <span>🔴 Exit to Live</span>
            </button>
          )}
        </div>

        {/* Center/Right: Replay Transport Buttons & Speed Pills */}
        <div className="flex items-center gap-3">
          {isReplayMode ? (
            <>
              {/* Transport buttons */}
              <div className="flex items-center bg-slate-950 border border-slate-800 rounded p-0.5">
                <button
                  onClick={() => onSeek(1)}
                  className="px-2 py-1 text-xs text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-colors"
                  title="Rewind to Start (Sequence 1)"
                >
                  ⏮
                </button>
                {isPaused ? (
                  <button
                    onClick={onResume}
                    className="px-2.5 py-1 text-xs text-emerald-400 hover:text-emerald-300 hover:bg-slate-800 rounded font-semibold transition-colors flex items-center gap-1"
                    title="Play"
                  >
                    <span>▶</span>
                    <span>Play</span>
                  </button>
                ) : (
                  <button
                    onClick={onPause}
                    className="px-2.5 py-1 text-xs text-amber-400 hover:text-amber-300 hover:bg-slate-800 rounded font-semibold transition-colors flex items-center gap-1"
                    title="Pause"
                  >
                    <span>⏸</span>
                    <span>Pause</span>
                  </button>
                )}
              </div>

              {/* Speed Selector Pills */}
              <div className="flex items-center gap-1 bg-slate-950 border border-slate-800 p-0.5 rounded">
                {SPEED_OPTIONS.map((opt) => {
                  const isActive = Math.abs(currentSpeed - opt.value) < 0.01 || (opt.value >= 1000 && currentSpeed >= 1000);
                  return (
                    <button
                      key={opt.label}
                      onClick={() => onSetSpeed(opt.value)}
                      className={`px-2 py-0.5 text-[11px] font-mono rounded transition-colors ${
                        isActive
                          ? 'bg-sky-600 text-white font-bold shadow-sm'
                          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="text-xs text-slate-400 flex items-center gap-2">
              <span className="text-slate-500 font-mono text-[11px]">Recording active events to SQLite log</span>
              <span className="font-mono text-slate-300 text-xs">Seq: #{currentSeq}</span>
            </div>
          )}
        </div>
      </div>

      {/* Scrubber Timeline Bar (Active during Replay) */}
      {isReplayMode && (
        <div className="flex items-center gap-3 pt-1 border-t border-slate-800/80">
          <div className="flex-1 flex items-center gap-2.5">
            <span className="text-[11px] font-mono text-slate-400 shrink-0">
              Seq {currentSeq}
            </span>
            <input
              type="range"
              min={1}
              max={Math.max(totalEvents, 1)}
              value={currentSeq}
              onChange={handleScrubberChange}
              onMouseDown={handleScrubberStart}
              onMouseUp={handleScrubberEnd}
              onTouchStart={handleScrubberStart}
              onTouchEnd={handleScrubberEnd}
              className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-sky-500 hover:accent-sky-400 transition-all"
            />
            <span className="text-[11px] font-mono text-slate-500 shrink-0">
              / {totalEvents} events
            </span>
          </div>

          <div className="text-[11px] font-mono text-slate-400 shrink-0">
            Progress: {totalEvents > 0 ? Math.round((currentSeq / totalEvents) * 100) : 0}%
          </div>
        </div>
      )}

      {/* Recorded Sessions Modal */}
      {showSessionModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] flex flex-col overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-950">
              <div className="flex items-center gap-2">
                <span className="text-lg">📁</span>
                <h3 className="text-sm font-bold text-slate-100">Recorded Simulation Sessions</h3>
                <span className="text-xs text-slate-400 font-mono">({sessions.length} saved)</span>
              </div>
              <button
                onClick={() => setShowSessionModal(false)}
                className="text-slate-400 hover:text-white text-lg p-1"
              >
                ✕
              </button>
            </div>

            {/* Sessions Table */}
            <div className="flex-1 overflow-y-auto p-4 divide-y divide-slate-800">
              {sessions.length === 0 ? (
                <div className="text-center py-8 text-sm text-slate-400">
                  No sessions recorded yet. Run live simulation to record market sessions.
                </div>
              ) : (
                sessions.map((sess) => {
                  const isCurrent = sess.session_id === sessionStatus?.session_id;
                  const dateStr = new Date(sess.created_at_utc).toLocaleString();
                  return (
                    <div
                      key={sess.session_id}
                      className={`py-3 flex items-center justify-between gap-3 ${
                        isCurrent ? 'bg-sky-950/20 -mx-2 px-2 rounded' : ''
                      }`}
                    >
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs font-semibold text-slate-200">
                            {sess.session_id}
                          </span>
                          <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-slate-800 text-sky-400">
                            {sess.symbol}
                          </span>
                          <span className="px-1.5 py-0.2 rounded text-[10px] bg-slate-800 text-slate-400 font-mono">
                            Seed: {sess.seed}
                          </span>
                          {isCurrent && (
                            <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                              ACTIVE
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-slate-400 flex items-center gap-3">
                          <span>Recorded: {dateStr}</span>
                          <span>•</span>
                          <span className="font-mono">{sess.total_events} events</span>
                          <span>•</span>
                          <span className={`text-[10px] uppercase font-bold ${
                            sess.status === 'ACTIVE' ? 'text-emerald-400' : 'text-slate-400'
                          }`}>
                            {sess.status}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          onClick={async () => {
                            setShowSessionModal(false);
                            await onStartReplay(sess.session_id, 1.0, 1);
                          }}
                          className="px-3 py-1.5 text-xs font-semibold rounded bg-sky-600 hover:bg-sky-500 text-white transition-colors flex items-center gap-1 shadow-sm"
                        >
                          <span>⏪ Replay</span>
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Modal Footer */}
            <div className="px-4 py-2.5 border-t border-slate-800 bg-slate-950 flex justify-end">
              <button
                onClick={() => setShowSessionModal(false)}
                className="px-4 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 rounded transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
