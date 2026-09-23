"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import StatusDots from "@/components/StatusDots";

const NAV = [
  { href: "/analyze", label: "Analyze", icon: "🔍", key: "1" },
  { href: "/deep-search", label: "Deep Search", icon: "🔬", key: "2" },
  { href: "/bulk", label: "Bulk Analysis", icon: "📦", key: "3" },
  { href: "/hunter", label: "Category Hunter", icon: "🎯", key: "4" },
  { href: "/tracker", label: "Price Tracker", icon: "📈", key: "5" },
  { href: "/watchlist", label: "Watchlist", icon: "⭐", key: "6" },
  { href: "/dashboard", label: "Dashboard", icon: "📊", key: "7" },
  { href: "/history", label: "History", icon: "📋", key: "8" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Ctrl+1..8 keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key >= "1" && e.key <= "8") {
        e.preventDefault();
        const item = NAV[parseInt(e.key) - 1];
        if (item) window.location.href = item.href;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <div className="flex min-h-screen">
      {/* Mobile hamburger */}
      <button
        className="fixed top-3 left-3 z-50 md:hidden bg-bg-surface border border-border rounded-lg px-3 py-2 text-text-secondary"
        onClick={() => setSidebarOpen(!sidebarOpen)}
        aria-label="Toggle menu"
      >
        ☰
      </button>

      {/* Overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed md:static inset-y-0 left-0 z-40 w-60 bg-bg-secondary border-r border-border flex flex-col transform transition-transform md:transform-none ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
      >
        <div className="p-4 border-b border-border text-center">
          <div className="w-10 h-10 mx-auto rounded-xl bg-gradient-to-br from-accent-blue to-blue-700 flex items-center justify-center text-lg mb-2">
            🎯
          </div>
          <div className="font-bold text-text-primary text-lg">eBay Hunter</div>
          <div className="text-xs text-text-secondary">
            Product Sourcing Intelligence
          </div>
        </div>

        <div className="px-4 py-3 border-b border-border">
          <StatusDots />
        </div>

        <nav className="flex-1 overflow-y-auto p-2">
          {NAV.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setSidebarOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm mb-1 ${
                  active
                    ? "bg-accent-blue/15 text-accent-blue border border-accent-blue/30"
                    : "text-text-secondary hover:bg-bg-surface hover:text-text-primary border border-transparent"
                }`}
              >
                <span>{item.icon}</span>
                <span className="flex-1">{item.label}</span>
                <kbd className="hidden lg:inline text-[10px] text-text-dim border border-border rounded px-1">
                  ^{item.key}
                </kbd>
              </Link>
            );
          })}
        </nav>

        <div className="p-3 border-t border-border text-[10px] text-text-dim text-center">
          Ctrl+1…8 shortcuts
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 pt-14 md:pt-6 lg:pt-8 px-4 pb-6 md:px-6 lg:px-8">
        {children}
      </main>
    </div>
  );
}
