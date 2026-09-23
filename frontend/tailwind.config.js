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
          primary: "#27233F",
          secondary: "#312C4D",
          surface: "#3B3560",
          hover: "#4A4470",
          sidebar: "#211E35",
        },
        border: {
          DEFAULT: "#4B525E",
          strong: "#5E6575",
          focus: "#0D1CC4",
        },
        text: {
          primary: "#FFFFFF",
          secondary: "#B7BBC6",
          dim: "#8A90A0",
        },
        accent: {
          blue: "#0D1CC4",
          "blue-dark": "#0B17A8",
          red: "#FF5C5C",
          green: "#CBFD03",
          "green-soft": "#BEC97D",
          amber: "#FFC857",
          purple: "#8B5CF6",
        },
        brand: {
          blue: "#0D1CC4",
          "blue-dark": "#0B17A8",
          lime: "#CBFD03",
          "lime-soft": "#BEC97D",
          dark: "#27233F",
          gray: "#4B525E",
        },
      },
      fontFamily: {
        sans: ["var(--font-jakarta)", "system-ui", "-apple-system", "sans-serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        control: "6px",
        card: "10px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(13,28,196,.08)",
        elev:
          "0 4px 6px rgba(0,0,0,.35), 0 12px 32px rgba(13,28,196,.12)",
        focus: "0 0 0 2px #27233F, 0 0 0 4px #CBFD03",
      },
      transitionDuration: {
        DEFAULT: "150ms",
      },
    },
  },
  plugins: [],
};
