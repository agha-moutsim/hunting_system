"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import StatusDots from "@/components/StatusDots";
import IconAnalyze from "@/components/icons/IconAnalyze";
import IconDeepDive from "@/components/icons/IconDeepDive";
import IconBulk from "@/components/icons/IconBulk";
import IconCategories from "@/components/icons/IconCategories";
import IconPricing from "@/components/icons/IconPricing";
import IconWishlist from "@/components/icons/IconWishlist";
import IconDashboard from "@/components/icons/IconDashboard";
import IconHistory from "@/components/icons/IconHistory";
import IconDeals from "@/components/icons/IconDeals";
import IconFees from "@/components/icons/IconFees";
import IconAlerts from "@/components/icons/IconAlerts";
import { fetchAlertCount, unreadBadge } from "@/lib/alerts";

type NavIcon = (props: { className?: string }) => ReactNode;

const NAV: {
  href: string;
  label: string;
  key: string;
  group: string;
  Icon: NavIcon;
}[] = [
  {
    href: "/analyze",
    label: "Analyze",
    key: "1",
    group: "Research",
    Icon: IconAnalyze,
  },
  {
    href: "/deep-search",
    label: "Deep Search",
    key: "2",
    group: "Research",
    Icon: IconDeepDive,
  },
  {
    href: "/bulk",
    label: "Bulk Analysis",
    key: "3",
    group: "Research",
    Icon: IconBulk,
  },
  {
    href: "/hunter",
    label: "Category Hunter",
    key: "4",
    group: "Research",
    Icon: IconCategories,
  },
  {
    href: "/tracker",
    label: "Price Tracker",
    key: "5",
    group: "Track",
    Icon: IconPricing,
  },
  {
    href: "/watchlist",
    label: "Watchlist",
    key: "6",
    group: "Track",
    Icon: IconWishlist,
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    key: "7",
    group: "Review",
    Icon: IconDashboard,
  },
  {
    href: "/history",
    label: "History",
    key: "8",
    group: "Review",
    Icon: IconHistory,
  },
  // Appended LAST on purpose: the Ctrl+number handler above indexes this array
  // positionally (NAV[Number - 1]), so the entry for ^9 has to be the ninth
  // one. It is grouped under Research because that is where it belongs on
  // screen, not because of where it sits in the array — the two are separate,
  // and the render below filters by `group`.
  {
    href: "/deals",
    label: "Deals",
    key: "9",
    group: "Research",
    Icon: IconDeals,
  },
  // The tenth entry, appended for the same positional reason as ^9 above:
  // Ctrl+0 opens it (the handler maps "0" to index 9), so the shortcut and
  // the on-screen group stay decoupled.
  {
    href: "/fees",
    label: "Fee Calculator",
    key: "0",
    group: "Research",
    Icon: IconFees,
  },
  // The eleventh entry has no digit shortcut left: ^0 already opens Fees and
  // the handler addresses entries positionally, so the shortcut range is
  // derived from the entries that DO have a digit rather than from this
  // array's length. Appended last for the same positional reason as ^9/^0,
  // grouped under Review because the inbox is where you look at what happened.
  {
    href: "/alerts",
    label: "Alerts",
    key: "",
    group: "Review",
    Icon: IconAlerts,
  },
];

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="w-9 h-9 rounded-card bg-brand-blue flex items-center justify-center shrink-0">
        <span className="font-bold text-brand-lime text-sm tracking-tight">
          EH
        </span>
      </div>
      <div className="min-w-0">
        <div className="font-bold text-white text-[15px] leading-tight">
          eBay <span className="text-brand-lime">Hunter</span>
        </div>
        <div className="text-[10px] text-text-dim leading-tight">
          Sourcing Intelligence
        </div>
      </div>
    </div>
  );
}

function MenuIcon({ open }: { open: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden>
      {open ? (
        <path
          d="M4 4l10 10M14 4L4 14"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
        />
      ) : (
        <path
          d="M3 5h12M3 9h12M3 13h12"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
        />
      )}
    </svg>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [alertCount, setAlertCount] = useState(0);

  // The badge polls rather than living only on the alerts page: the point of
  // an inbox is that you can see it arrive. 60 s against a local backend is
  // cheap; a stopped backend is StatusDots' story, not this one's.
  useEffect(() => {
    let alive = true;
    const load = () => {
      fetchAlertCount()
        .then((body) => {
          if (alive) setAlertCount(body.unread ?? 0);
        })
        .catch(() => {
          /* leave the last known count; do not invent zero */
        });
    };
    load();
    const timer = window.setInterval(load, 60_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [pathname]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key >= "0" && e.key <= "9") {
        e.preventDefault();
        // "0" is the tenth entry (index 9); 1-9 index positionally as before.
        const item = NAV[e.key === "0" ? 9 : parseInt(e.key) - 1];
        if (item) window.location.href = item.href;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const groups = ["Research", "Track", "Review"];

  // "Ctrl+1…10" has to count the entries that actually own a digit - the
  // alerts entry has no shortcut, and a label derived from NAV.length would
  // promise "Ctrl+1…11" with nothing behind it.
  const shortcutCount = NAV.filter((item) => /^[0-9]$/.test(item.key)).length;

  return (
    <div className="flex min-h-screen">
      <button
        className="fixed top-3 left-3 z-50 md:hidden bg-bg-surface border border-border rounded-control px-3 py-2 text-text-secondary hover:text-white focus-visible:outline-solid focus-visible:outline-2 focus-visible:outline-brand-lime"
        onClick={() => setSidebarOpen(!sidebarOpen)}
        aria-label="Toggle menu"
      >
        <MenuIcon open={sidebarOpen} />
      </button>

      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed md:static inset-y-0 left-0 z-40 w-60 bg-bg-sidebar border-r border-border flex flex-col transform transition-transform duration-150 ease-out md:transform-none ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
      >
        <div className="p-4 border-b border-border">
          <Brand />
        </div>

        <div className="px-4 py-3 border-b border-border">
          <StatusDots />
        </div>

        <nav className="flex-1 overflow-y-auto p-2">
          {groups.map((group) => {
            const items = NAV.filter((n) => n.group === group);
            if (!items.length) return null;
            return (
              <div key={group} className="mb-3">
                <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">
                  {group}
                </div>
                {items.map((item) => {
                  const active = pathname === item.href;
                  const badge =
                    item.href === "/alerts" ? unreadBadge(alertCount) : null;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setSidebarOpen(false)}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-control text-sm mb-0.5 transition-colors duration-150 ${
                        active
                          ? "bg-brand-blue/20 text-brand-lime font-semibold"
                          : "text-text-secondary hover:bg-bg-surface hover:text-white"
                      }`}
                    >
                      <item.Icon
                        className={`w-5 h-5 shrink-0 ${active ? "text-brand-lime" : ""}`}
                      />
                      <span className="flex-1">{item.label}</span>
                      {badge && (
                        <span className="rounded-full bg-brand-lime px-1.5 py-0.5 text-[10px] font-bold leading-none text-brand-blue">
                          {badge}
                        </span>
                      )}
                      {item.key && (
                        <kbd className="hidden lg:inline text-[10px] text-text-dim border border-border rounded-sm px-1 font-mono">
                          ^{item.key}
                        </kbd>
                      )}
                    </Link>
                  );
                })}
              </div>
            );
          })}
        </nav>

        <div className="p-3 border-t border-border text-[10px] text-text-dim text-center">
          {/* Derived from the entries that own a digit rather than written
              out: it said "Ctrl+1…8" after a ninth entry was added, which is
              the kind of label that quietly stops being true. */}
          Ctrl+1…{shortcutCount} shortcuts
        </div>
      </aside>

      <main className="flex-1 min-w-0 pt-14 md:pt-6 lg:pt-8 px-4 pb-6 md:px-6 lg:px-8">
        {children}
      </main>
    </div>
  );
}
