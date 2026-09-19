// Hand-mirrored from shared/schemas.py's UISpec / UIComponentSpec. Keep in sync by hand
// for the hackathon — if it drifts, backend-api's /ui-spec response is the source of truth.

export interface UIComponentSpec {
  component: string; // must match a key in COMPONENT_REGISTRY (src/registry.tsx)
  props: Record<string, unknown>;
}

export interface UISpec {
  requester_id: string;
  panels: UIComponentSpec[];
  generated_at: string;
}
