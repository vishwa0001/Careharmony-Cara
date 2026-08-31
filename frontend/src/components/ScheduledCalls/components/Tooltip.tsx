import React from 'react';

interface TooltipProps {
  content: string;
  children: React.ReactNode;
}

export const Tooltip: React.FC<TooltipProps> = ({ content, children }) => {
  return (
    <div className="relative group inline-flex" title={content}>
      {children}
      <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:flex items-center justify-center z-50 min-w-[180px] max-w-[260px] px-2.5 py-1.5 text-[11px] font-medium text-slate-100 bg-slate-900/95 dark:bg-slate-800/95 rounded-lg shadow-xl border border-slate-700/80 dark:border-slate-700 transition-all duration-150">
        <span className="text-center leading-snug whitespace-normal">{content}</span>
      </div>
    </div>
  );
};
