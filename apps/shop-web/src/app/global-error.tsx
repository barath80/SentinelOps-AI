"use client";

// Catches errors thrown by the root layout itself. It replaces the whole document, so it must
// render its own <html>/<body> and can't rely on globals.css having loaded.
export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", textAlign: "center", padding: "80px 20px" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700 }}>Something went wrong</h1>
        <p style={{ marginTop: 8, color: "#52525b" }}>The app hit an unexpected error. Please try again.</p>
        <button
          type="button"
          onClick={() => reset()}
          style={{
            marginTop: 24,
            padding: "8px 20px",
            borderRadius: 999,
            background: "#fbbf24",
            fontWeight: 600,
            border: "none",
            cursor: "pointer",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
