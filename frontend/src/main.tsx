import { Component, StrictMode, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

type BoundaryState = { error: Error | null };

class AppErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("EdgeOrtho UI error", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="flex min-h-screen items-center justify-center bg-stone-100 p-6">
          <section className="max-w-lg rounded-card border border-signal-red/40 bg-stone-50 p-5 shadow-panel">
            <h1 className="text-sm font-semibold text-signal-red">The interface could not render this view</h1>
            <p className="mt-2 text-xs leading-relaxed text-stone-600">
              The backend data is still safe. Refresh the page or return to Overview. Technical detail:
            </p>
            <pre className="mt-3 overflow-auto rounded border border-stone-200 bg-stone-100 p-3 text-2xs text-stone-700">
              {this.state.error.message}
            </pre>
            <button
              type="button"
              className="mt-4 rounded-[4px] border border-stone-300 bg-stone-50 px-3 py-1.5 text-xs text-stone-700 hover:bg-stone-200"
              onClick={() => window.location.reload()}
            >
              Reload interface
            </button>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}

const container = document.getElementById("root");
if (!container) throw new Error("#root element is missing from index.html");

createRoot(container).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
