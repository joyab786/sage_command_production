/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        sage: {
          bg: '#020202',
          surface: '#070707',
          card: '#0a0a0a',
          border: 'rgba(255,255,255,0.05)',
        },
        neon: {
          cyan: '#22d3ee',
          purple: '#a855f7',
          amber: '#f59e0b',
          red: '#ef4444',
          green: '#22c55e',
        }
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'flow-stream': 'flowStream 1s linear infinite',
        'blast-ring': 'pulseRing 2.5s cubic-bezier(0.21, 0.6, 0.35, 1) infinite',
        'scan-line': 'scanLine 3s ease-in-out infinite',
        'breathe-glow': 'breatheGlow 2s ease-in-out infinite',
        'glitch': 'glitchText 4s ease-in-out infinite',
      },
      backdropBlur: {
        xs: '2px',
      },
      boxShadow: {
        'neon-cyan': '0 0 15px rgba(34, 211, 238, 0.3)',
        'neon-purple': '0 0 15px rgba(168, 85, 247, 0.3)',
        'neon-red': '0 0 20px rgba(239, 68, 68, 0.4)',
        'neon-amber': '0 0 15px rgba(245, 158, 11, 0.3)',
      }
    },
  },
  plugins: [],
}