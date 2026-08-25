import React from 'react';
import { CalendarClock, Laptop, Moon, PhoneCall, Sun } from 'lucide-react';
import { useTheme } from '../../../context/ThemeContext';

interface HeaderProps {
  scheduledCount: number;
}

export const Header: React.FC<HeaderProps> = ({ scheduledCount }) => {
  const { theme, setTheme } = useTheme();

  return (
    <header className="bg-white/80 dark:bg-slate-900/80 border-b border-slate-200 dark:border-slate-800 backdrop-blur sticky top-0 z-20 px-4 sm:px-8 py-4 mb-8 transition-colors">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        {/* Title and Branding */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-indigo-50 dark:bg-indigo-600/20 text-indigo-600 dark:text-indigo-400 rounded-xl border border-indigo-200 dark:border-indigo-500/30">
            <PhoneCall className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
              Scheduled Calls
              <span className="text-xs font-semibold px-2 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-500/20">
                Internal Ops
              </span>
            </h1>
            <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400">
              Manage outbound customer calling batches and launch schedules
            </p>
          </div>
        </div>

        {/* Controls & Theme Switcher */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700 text-xs">
            <CalendarClock className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
            <span className="text-slate-600 dark:text-slate-400">Active Batches:</span>
            <span className="font-bold text-indigo-600 dark:text-indigo-300">{scheduledCount}</span>
          </div>

          {/* Theme Switcher Toggle */}
          <div className="flex items-center p-1 rounded-xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs">
            <button
              type="button"
              onClick={() => setTheme('light')}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-lg font-medium transition-all ${
                theme === 'light'
                  ? 'bg-white text-indigo-600 shadow-sm'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
              title="Light Mode"
            >
              <Sun className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Light</span>
            </button>

            <button
              type="button"
              onClick={() => setTheme('dark')}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-lg font-medium transition-all ${
                theme === 'dark'
                  ? 'bg-slate-700 text-indigo-300 shadow-sm'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
              title="Dark Mode"
            >
              <Moon className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Dark</span>
            </button>

            <button
              type="button"
              onClick={() => setTheme('system')}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-lg font-medium transition-all ${
                theme === 'system'
                  ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-300 shadow-sm'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
              }`}
              title="System Mode"
            >
              <Laptop className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">System</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
