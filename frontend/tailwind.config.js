/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        stone: {
          50: "#FFFFFF",
          100: "#F4F6F2",
          200: "#E9EEE8",
          300: "#DDE3DA",
          400: "#B8C4BA",
          500: "#87948B",
          600: "#65736A",
          700: "#45544B",
          800: "#26332D",
          900: "#111815",
          950: "#0B100E",
        },
        forest: {
          50: "#EEF5EB",
          100: "#DDEBDD",
          200: "#C5DCC1",
          300: "#A8C79E",
          400: "#8EBF75",
          500: "#789F6C",
          600: "#648B63",
          700: "#466E55",
          800: "#163A32",
          900: "#102820",
        },
        clay: {
          400: "#C98A5B",
          500: "#B4744A",
          600: "#95593A",
        },
        signal: {
          amber: "#D9A441",
          red: "#D86C64",
          blue: "#6398C8",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "IBM Plex Sans",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "sans-serif",
        ],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.02em" }],
      },
      boxShadow: {
        panel: "0 1px 2px rgba(17,24,21,0.04), 0 1px 1px rgba(17,24,21,0.03)",
        raised: "0 4px 12px rgba(17,24,21,0.08), 0 1px 2px rgba(17,24,21,0.04)",
      },
      borderRadius: { card: "0.5rem" },
    },
  },
  plugins: [],
};
