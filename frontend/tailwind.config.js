/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: "#0B1120",
          secondary: "#111827",
          surface: "#1E293B",
          hover: "#334155",
        },
        border: {
          DEFAULT: "#334155",
          focus: "#3B82F6",
        },
        text: {
          primary: "#F8FAFC",
          secondary: "#94A3B8",
          dim: "#64748B",
        },
        accent: {
          blue: "#3B82F6",
          red: "#EF4444",
          green: "#10B981",
          amber: "#F59E0B",
          purple: "#8B5CF6",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
      },
    },
  },
  plugins: [],
};
